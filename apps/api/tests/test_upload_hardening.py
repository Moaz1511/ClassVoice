from __future__ import annotations

import io
import math
import shutil
import struct
import subprocess
import wave
from array import array
from pathlib import Path
from uuid import UUID

import pytest
from app.domains.generations.jobs import GenerationError, _validate_request
from app.inference.adapter import InferenceError, InferenceRequest, SmokeCpuAdapter
from app.workers.audio_validation import (
    FFMPEG_TIMEOUT_SECONDS,
    MAX_CAPTURED_PCM_BYTES,
    MAX_DECODED_PCM_BYTES,
    MAX_FFMPEG_ALLOCATION_BYTES,
    AudioInspectionError,
    AudioProbe,
    AudioValidationCode,
    AudioValidator,
    FFmpegAudioInspector,
)


def wav_bytes() -> bytes:
    samples = b"\x01\x00\xff\xff"
    format_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
    data_chunk = b"data" + struct.pack("<I", len(samples)) + samples
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


class SpyInspector:
    def __init__(
        self,
        *,
        probe: AudioProbe | None = None,
        decode_error: AudioInspectionError | None = None,
    ) -> None:
        self.probe_result = probe or AudioProbe(8.0, 1, 16_000, "pcm_s16le")
        self.decode_error = decode_error
        self.probe_calls = 0
        self.decode_calls = 0

    def probe(self, _path: Path) -> AudioProbe:
        self.probe_calls += 1
        return self.probe_result

    def decode_pcm(self, _path: Path) -> tuple[int, ...]:
        self.decode_calls += 1
        if self.decode_error is not None:
            raise self.decode_error
        return (1_000, -1_000, 2_000, -2_000)


@pytest.mark.parametrize(
    ("payload", "filename", "content_type"),
    [
        (wav_bytes() + b"PK\x03\x04archive", "lesson.wav", "audio/wav"),
        (mp3_bytes() + b"%PDF-1.7", "lesson.mp3", "audio/mpeg"),
        (m4a_bytes() + b"PK\x03\x04archive", "lesson.m4a", "audio/mp4"),
    ],
)
def test_polyglot_payloads_are_rejected_before_external_inspection(
    payload: bytes, filename: str, content_type: str
) -> None:
    inspector = SpyInspector()

    result = AudioValidator(inspector).validate(
        payload, filename=filename, content_type=content_type
    )

    assert result.code == AudioValidationCode.POLYGLOT_DETECTED
    assert result.accepted is False
    assert inspector.probe_calls == 0
    assert inspector.decode_calls == 0


@pytest.mark.parametrize(
    ("payload", "filename", "content_type"),
    [
        (
            wav_bytes()[:4] + struct.pack("<I", 9_999) + wav_bytes()[8:],
            "lesson.wav",
            "audio/wav",
        ),
        (
            b"ID3\x04\x00\x00\x80\x00\x00\x00" + b"\xff\xfb\x90\x64",
            "lesson.mp3",
            "audio/mpeg",
        ),
        (b"\x00\x00\x00\x04ftypM4A ", "lesson.m4a", "audio/mp4"),
    ],
)
def test_malformed_container_headers_have_a_stable_classification(
    payload: bytes, filename: str, content_type: str
) -> None:
    inspector = SpyInspector()

    result = AudioValidator(inspector).validate(
        payload, filename=filename, content_type=content_type
    )

    assert result.code == AudioValidationCode.MALFORMED_CONTAINER
    assert result.accepted is False
    assert inspector.probe_calls == 0


def test_deterministic_header_mutations_never_escape_as_worker_exceptions() -> None:
    valid_wav = wav_bytes()
    mutations = (
        valid_wav[: index] for index in (1, 4, 8, 11, 12, 20, 35, len(valid_wav) - 1)
    )
    payloads = (*mutations, b"RIFF" + b"\xff" * 40, b"ID3" + b"\xff" * 20, bytes(range(64)))
    allowed_codes = {
        AudioValidationCode.MAGIC_BYTES_MISMATCH,
        AudioValidationCode.MALFORMED_CONTAINER,
    }

    for payload in payloads:
        result = AudioValidator(SpyInspector()).validate(
            payload, filename="lesson.wav", content_type="audio/wav"
        )
        assert result.accepted is False
        assert result.code in allowed_codes


def test_probe_policy_rejects_long_audio_before_decode_expansion() -> None:
    inspector = SpyInspector(probe=AudioProbe(30.01, 1, 16_000, "pcm_s16le"))

    result = AudioValidator(inspector).validate(
        wav_bytes(), filename="lesson.wav", content_type="audio/wav"
    )

    assert result.code == AudioValidationCode.DURATION_TOO_LONG
    assert inspector.probe_calls == 1
    assert inspector.decode_calls == 0


def test_decoder_resource_failures_are_classified_without_crashing() -> None:
    inspector = SpyInspector(
        decode_error=AudioInspectionError(
            AudioValidationCode.RESOURCE_LIMIT_EXCEEDED,
            "bounded decoder output exceeded",
        )
    )

    result = AudioValidator(inspector).validate(
        wav_bytes(), filename="lesson.wav", content_type="audio/wav"
    )

    assert result.code == AudioValidationCode.RESOURCE_LIMIT_EXCEEDED
    assert result.accepted is False


def test_ffmpeg_decoder_uses_fixed_time_thread_and_output_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def completed(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=b"\x01\x00\xff\xff", stderr=b"")

    monkeypatch.setattr(subprocess, "run", completed)

    samples = FFmpegAudioInspector().decode_pcm(tmp_path / "sample.wav")

    assert samples == (1, -1)
    command, kwargs = calls[0]
    assert command[command.index("-threads") + 1] == "1"
    assert command[command.index("-t") + 1] == "31.0"
    assert command[command.index("-fs") + 1] == str(MAX_CAPTURED_PCM_BYTES)
    assert command[command.index("-max_alloc") + 1] == str(MAX_FFMPEG_ALLOCATION_BYTES)
    assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["timeout"] == FFMPEG_TIMEOUT_SECONDS


def test_ffmpeg_output_above_decoded_ceiling_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def oversized(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"\x00" * (MAX_DECODED_PCM_BYTES + 2),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", oversized)

    with pytest.raises(AudioInspectionError) as error:
        FFmpegAudioInspector().decode_pcm(tmp_path / "sample.wav")

    assert error.value.code == AudioValidationCode.RESOURCE_LIMIT_EXCEEDED


def test_ffprobe_timeout_is_a_resource_limit_not_an_unhandled_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def timeout(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 10.0)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(AudioInspectionError) as error:
        FFmpegAudioInspector().probe(tmp_path / "sample.wav")

    assert error.value.code == AudioValidationCode.RESOURCE_LIMIT_EXCEEDED


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg binaries are not installed",
)
def test_real_six_second_wav_fixture_passes_the_bounded_decoder() -> None:
    sample_rate = 16_000
    samples = array(
        "h",
        (
            int(2_000 * math.sin(2 * math.pi * 220 * index / sample_rate))
            for index in range(sample_rate * 6)
        ),
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())

    result = AudioValidator().validate(
        output.getvalue(), filename="lesson.wav", content_type="audio/wav"
    )

    assert result.code == AudioValidationCode.ACCEPTED
    assert result.accepted is True


def validate_generation_text(text: str) -> str:
    result = _validate_request(
        input_text=text,
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=None,
        style=None,
        checkpoint_sha256="a" * 64,
        idempotency_key="p4-unicode-validation-key-01",
    )
    return result[0]


@pytest.mark.parametrize(
    "text",
    [
        "শিক্ষার্থীদের জন্য বাংলা পাঠ",
        "درس أكاديمي للطلاب\u200f",
        "Mathematics: e\u0301 = é and 👩🏽‍🏫 explains 📚",
        "漢" * 10_000,
    ],
    ids=("bangla", "rtl", "combining-emoji", "max-cjk"),
)
def test_valid_unicode_text_is_preserved_and_bounded_by_code_points(text: str) -> None:
    assert validate_generation_text(text) == text


@pytest.mark.parametrize(
    "text",
    ["🙂" * 10_001, "lesson\x00hidden", "lesson\ud800"],
    ids=("too-long", "nul-control", "unpaired-surrogate"),
)
def test_long_or_unsafe_unicode_text_has_a_stable_error(text: str) -> None:
    with pytest.raises(GenerationError) as error:
        validate_generation_text(text)

    assert error.value.code == "INPUT_TEXT_INVALID"


@pytest.mark.asyncio
async def test_worker_adapter_rejects_unencodable_unicode_without_crashing() -> None:
    request = InferenceRequest(
        job_id=UUID("00000000-0000-0000-0000-000000000401"),
        input_text="lesson\ud800",
        language_code="en-US",
        output_format="wav",
        speed=1.0,
        stability=None,
        style=None,
        seed=None,
        model_key="smoke",
        model_version="1.0.0",
        checkpoint_sha256="a" * 64,
        model_metadata={},
    )

    with pytest.raises(InferenceError) as error:
        await SmokeCpuAdapter().generate(request)

    assert error.value.code == "INFERENCE_INPUT_INVALID"
