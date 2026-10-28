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
        self.probe = probe
        self.samples = samples

    def inspect(self, _path: object) -> tuple[AudioProbe, tuple[int, ...]]:
        return self.probe, self.samples


class OversizedBytes(bytes):
    def __len__(self) -> int:
        return 25_000_001


def wav_bytes() -> bytes:
    return b"RIFF" + struct.pack("<I", 36) + b"WAVE" + b"fmt " + b"\x00" * 24


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
    assert sniff_audio_format(b"ID3" + b"\x00" * 20) == "mp3"
    assert sniff_audio_format(b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 8) == "m4a"
    assert sniff_audio_format(b"not audio") is None


@pytest.mark.parametrize(
    ("data", "filename", "content_type"),
    [
        (wav_bytes(), "lecture.wav", "audio/wav"),
        (b"ID3" + b"\x00" * 20, "lecture.mp3", "audio/mpeg"),
        (b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 8, "lecture.m4a", "audio/mp4"),
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
    def inspect(self, _path: object) -> tuple[AudioProbe, tuple[int, ...]]:
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
