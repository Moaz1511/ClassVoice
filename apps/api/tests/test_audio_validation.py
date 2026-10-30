from __future__ import annotations

import struct

import pytest
from app.workers.audio_validation import (
    AudioProbe,
    AudioValidationCode,
    AudioValidator,
    sniff_audio_format,
)


class FakeInspector:
    def __init__(self, probe: AudioProbe, samples: tuple[int, ...]) -> None:
        self.probe_result = probe
        self.samples = samples
        self.decode_calls = 0

    def probe(self, _path: object) -> AudioProbe:
        return self.probe_result

    def decode_pcm(self, _path: object) -> tuple[int, ...]:
        self.decode_calls += 1
        return self.samples


class OversizedBytes(bytes):
    def __len__(self) -> int:
        return 25_000_001


def wav_bytes() -> bytes:
    sample_data = b"\x01\x00\xff\xff"
    format_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
    data_chunk = b"data" + struct.pack("<I", len(sample_data)) + sample_data
    body = b"WAVE" + format_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def mp3_bytes() -> bytes:
    return b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" + b"\x00" * 16


def m4a_bytes() -> bytes:
    def box(name: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload) + 8) + name + payload

    return (
        box(b"ftyp", b"M4A \x00\x00\x00\x00M4A ")
        + box(b"moov", b"\x00" * 8)
        + box(b"mdat", b"\x01" * 8)
    )


def validator(
    *,
    duration: float = 8.0,
    channels: int = 1,
    samples: tuple[int, ...] = (1000, -1000, 2000, -2000),
    speaker_count: int | None = None,
) -> AudioValidator:
    return AudioValidator(
        FakeInspector(
            AudioProbe(duration, channels, 16_000, "pcm_s16le", speaker_count),
            samples,
        )
    )


def test_magic_byte_sniffing_accepts_wav_mp3_and_m4a() -> None:
    assert sniff_audio_format(wav_bytes()) == "wav"
    assert sniff_audio_format(mp3_bytes()) == "mp3"
    assert sniff_audio_format(m4a_bytes()) == "m4a"
    assert sniff_audio_format(b"not audio") is None


@pytest.mark.parametrize(
    ("data", "filename", "content_type"),
    [
        (wav_bytes(), "lecture.wav", "audio/wav"),
        (mp3_bytes(), "lecture.mp3", "audio/mpeg"),
        (m4a_bytes(), "lecture.m4a", "audio/mp4"),
    ],
)
def test_supported_formats_are_accepted_with_quality_metrics(
    data: bytes, filename: str, content_type: str
) -> None:
    result = validator().validate(data, filename=filename, content_type=content_type)

    assert result.accepted is True
    assert result.code == AudioValidationCode.ACCEPTED
    assert result.silence_ratio == 0.0
    assert result.clipping_ratio == 0.0


class CorruptInspector:
    def probe(self, _path: object) -> AudioProbe:
        return AudioProbe(8.0, 1, 16_000, "pcm_s16le")

    def decode_pcm(self, _path: object) -> tuple[int, ...]:
        raise ValueError("decode failed")


def test_decode_failures_are_classified_as_corrupt_audio() -> None:
    result = AudioValidator(CorruptInspector()).validate(
        wav_bytes(), filename="lecture.wav", content_type="audio/wav"
    )
    assert result.code == AudioValidationCode.CORRUPT_AUDIO
    assert result.accepted is False


@pytest.mark.parametrize(
    ("duration", "code"),
    [
        (5.99, AudioValidationCode.DURATION_TOO_SHORT),
        (30.01, AudioValidationCode.DURATION_TOO_LONG),
    ],
)
def test_duration_boundaries_are_enforced(duration: float, code: AudioValidationCode) -> None:
    result = validator(duration=duration).validate(
        wav_bytes(), filename="lecture.wav", content_type="audio/wav"
    )
    assert result.code == code
    assert result.accepted is False


def test_silence_clipping_channels_and_speaker_warning_are_classified() -> None:
    silent = validator(samples=(0, 0, 100, -100)).validate(
        wav_bytes(), filename="lecture.wav", content_type="audio/wav"
    )
    clipped = validator(samples=(32767, -32768, 32760, -32760)).validate(
        wav_bytes(), filename="lecture.wav", content_type="audio/wav"
    )
    channels = validator(channels=3).validate(
        wav_bytes(), filename="lecture.wav", content_type="audio/wav"
    )
    speakers = validator(speaker_count=2).validate(
        wav_bytes(), filename="lecture.wav", content_type="audio/wav"
    )

    assert silent.code == AudioValidationCode.SILENCE_DETECTED
    assert clipped.code == AudioValidationCode.CLIPPING_DETECTED
    assert channels.code == AudioValidationCode.INVALID_CHANNELS
    assert "multiple_speakers_detected" in speakers.warnings


@pytest.mark.parametrize(
    ("data", "filename", "content_type", "code"),
    [
        (b"bad", "lecture.wav", "audio/wav", AudioValidationCode.MAGIC_BYTES_MISMATCH),
        (wav_bytes(), "lecture.mp3", "audio/mpeg", AudioValidationCode.MAGIC_BYTES_MISMATCH),
        (OversizedBytes(b"x"), "lecture.wav", "audio/wav", AudioValidationCode.INVALID_SIZE),
    ],
)
def test_container_and_size_mismatches_are_rejected(
    data: bytes, filename: str, content_type: str, code: AudioValidationCode
) -> None:
    result = validator().validate(data, filename=filename, content_type=content_type)
    assert result.code == code
    assert result.accepted is False
