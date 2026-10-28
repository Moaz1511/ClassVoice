"""OpenVoice V2 adapter boundary with explicit CPU/CUDA selection.

The adapter does not download weights or import PyTorch.  A runtime factory
must be supplied by deployment code after the model registry has verified the
allowlisted checkpoint.  This keeps model execution replaceable and makes the
CPU smoke path usable in CI.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import wave
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.inference.adapter import InferenceError, InferenceRequest, InferenceResult
from app.inference.model_registry import ModelManifestEntry, ModelRegistry, ModelRegistryError

OPENVOICE_MODEL_KEY = "openvoice-v2"
OPENVOICE_MODEL_VERSION = "2.0.0"
_SUPPORTED_DEVICES = frozenset({"cpu", "cuda"})


class OpenVoiceRuntime(Protocol):
    async def synthesize(self, request: InferenceRequest) -> bytes: ...


RuntimeFactory = Callable[[ModelManifestEntry, str], Awaitable[OpenVoiceRuntime]]


class OpenVoiceV2Adapter:
    """Validate registry provenance, invoke OpenVoice, and normalize WAV output."""

    def __init__(
        self,
        registry: ModelRegistry,
        runtime_factory: RuntimeFactory,
        *,
        device: str = "cpu",
        max_output_bytes: int = 25_000_000,
        max_duration_ms: int = 120_000,
    ) -> None:
        if device not in _SUPPORTED_DEVICES:
            raise ValueError("device must be cpu or cuda")
        if max_output_bytes <= 0 or max_duration_ms <= 0:
            raise ValueError("output limits must be positive")
        self._registry = registry
        self._runtime_factory = runtime_factory
        self.device = device
        self.max_output_bytes = max_output_bytes
        self.max_duration_ms = max_duration_ms

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        if not request.input_text.strip() or len(request.input_text) > 10_000:
            raise InferenceError(
                "INFERENCE_INPUT_INVALID", "Inference text is empty or exceeds the limit."
            )
        if request.output_format != "wav":
            raise InferenceError(
                "INFERENCE_FORMAT_UNSUPPORTED", "OpenVoice output must be normalized as WAV."
            )
        try:
            entry = self._registry.resolve(
                request.model_key,
                request.model_version,
                request.checkpoint_sha256,
            )
        except ModelRegistryError as error:
            raise InferenceError(error.code, str(error)) from error
        if entry.model_key != OPENVOICE_MODEL_KEY or entry.version != OPENVOICE_MODEL_VERSION:
            raise InferenceError(
                "INFERENCE_MODEL_UNSUPPORTED", "The configured adapter only supports OpenVoice V2."
            )
        try:
            runtime = await self._runtime_factory(entry, self.device)
            audio = await runtime.synthesize(request)
        except InferenceError:
            raise
        except Exception as error:
            raise InferenceError(
                "INFERENCE_RUNTIME_ERROR",
                "The OpenVoice runtime failed while synthesizing audio.",
                retryable=True,
            ) from error
        _validate_wav(audio, self.max_output_bytes, self.max_duration_ms)
        return InferenceResult(
            audio_bytes=audio,
            content_type="audio/wav",
            sample_rate_hz=_wav_sample_rate(audio),
            channels=_wav_channels(audio),
            duration_ms=_wav_duration_ms(audio),
            sha256=hashlib.sha256(audio).hexdigest(),
            metadata={
                "adapter": OPENVOICE_MODEL_KEY,
                "device": self.device,
                "model_key": entry.model_key,
                "model_version": entry.version,
                "checkpoint_sha256": entry.checkpoint_sha256,
                "settings": {
                    "speed": request.speed,
                    "stability": request.stability,
                    "style": request.style,
                    "seed": request.seed,
                },
            },
        )


class SmokeOpenVoiceRuntime:
    """Deterministic runtime stand-in used to exercise the OpenVoice boundary."""

    def __init__(self, waveform_factory: Callable[[InferenceRequest], bytes]) -> None:
        self._waveform_factory = waveform_factory

    async def synthesize(self, request: InferenceRequest) -> bytes:
        await asyncio.sleep(0)
        return self._waveform_factory(request)


def _validate_wav(audio: bytes, max_bytes: int, max_duration_ms: int) -> None:
    if len(audio) == 0 or len(audio) > max_bytes:
        raise InferenceError("INFERENCE_OUTPUT_INVALID", "Inference output exceeds the size limit.")
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                raise InferenceError("INFERENCE_OUTPUT_INVALID", "Output must be mono 16-bit WAV.")
            duration_ms = int(handle.getnframes() * 1000 / handle.getframerate())
    except (EOFError, wave.Error) as error:
        raise InferenceError(
            "INFERENCE_OUTPUT_INVALID", "Inference output is not valid WAV."
        ) from error
    if duration_ms <= 0 or duration_ms > max_duration_ms:
        raise InferenceError("INFERENCE_OUTPUT_INVALID", "Inference output duration is invalid.")


def _wav_sample_rate(audio: bytes) -> int:
    with wave.open(io.BytesIO(audio), "rb") as handle:
        return handle.getframerate()


def _wav_channels(audio: bytes) -> int:
    with wave.open(io.BytesIO(audio), "rb") as handle:
        return handle.getnchannels()


def _wav_duration_ms(audio: bytes) -> int:
    with wave.open(io.BytesIO(audio), "rb") as handle:
        return int(handle.getnframes() * 1000 / handle.getframerate())
