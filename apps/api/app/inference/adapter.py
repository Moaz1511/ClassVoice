"""Provider-neutral inference contract and deterministic CPU smoke adapter."""

from __future__ import annotations

import hashlib
import io
import math
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domains.generations.jobs import GenerationJob


class InferenceError(ValueError):
    """Safe, stable inference error suitable for job state persistence."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    job_id: UUID
    input_text: str
    language_code: str
    output_format: str
    speed: float
    stability: float | None
    style: float | None
    seed: int | None
    model_key: str
    model_version: str
    checkpoint_sha256: str
    model_metadata: Mapping[str, object]

    @classmethod
    def from_job(cls, job: GenerationJob) -> InferenceRequest:
        return cls(
            job.id,
            job.input_text,
            job.language_code,
            job.output_format,
            job.speed,
            job.stability,
            job.style,
            job.seed,
            job.model_key,
            job.model_version,
            job.checkpoint_sha256,
            job.model_metadata,
        )


@dataclass(frozen=True, slots=True)
class InferenceResult:
    audio_bytes: bytes
    content_type: str
    sample_rate_hz: int
    channels: int
    duration_ms: int
    sha256: str
    metadata: Mapping[str, object]


class InferenceAdapter(Protocol):
    async def generate(self, request: InferenceRequest) -> InferenceResult: ...


class SmokeCpuAdapter:
    """Generate a small deterministic mono WAV without loading a model."""

    sample_rate_hz = 24_000
    duration_ms = 500
    channels = 1
    max_characters = 10_000

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        if not request.input_text.strip() or len(request.input_text) > self.max_characters:
            raise InferenceError(
                "INFERENCE_INPUT_INVALID", "Inference text is empty or exceeds the limit."
            )
        if request.output_format != "wav":
            raise InferenceError(
                "INFERENCE_FORMAT_UNSUPPORTED",
                "The CPU smoke adapter only produces WAV output.",
            )
        audio = deterministic_wav_for_request(request)
        return InferenceResult(
            audio_bytes=audio,
            content_type="audio/wav",
            sample_rate_hz=self.sample_rate_hz,
            channels=self.channels,
            duration_ms=self.duration_ms,
            sha256=hashlib.sha256(audio).hexdigest(),
            metadata={
                "adapter": "smoke-cpu",
                "model_key": request.model_key,
                "model_version": request.model_version,
                "checkpoint_sha256": request.checkpoint_sha256,
                "deterministic": True,
            },
        )


def deterministic_wav_for_request(request: InferenceRequest) -> bytes:
    seed_material = "|".join(
        (
            request.input_text,
            request.language_code,
            request.model_key,
            request.model_version,
            request.checkpoint_sha256,
            str(request.speed),
            str(request.stability),
            str(request.style),
            str(request.seed),
        )
    ).encode()
    digest = hashlib.sha256(seed_material).digest()
    frequency = 180 + int.from_bytes(digest[:2], "big") % 220
    amplitude = 2_400 + digest[2] * 8
    frame_count = SmokeCpuAdapter.sample_rate_hz * SmokeCpuAdapter.duration_ms // 1000
    frames = bytearray()
    for index in range(frame_count):
        sample = int(
            amplitude
            * math.sin(2 * math.pi * frequency * index / SmokeCpuAdapter.sample_rate_hz)
        )
        frames.extend(sample.to_bytes(2, "little", signed=True))
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(SmokeCpuAdapter.channels)
        handle.setsampwidth(2)
        handle.setframerate(SmokeCpuAdapter.sample_rate_hz)
        handle.writeframes(bytes(frames))
    return output.getvalue()
