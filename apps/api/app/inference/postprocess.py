"""Bounded audio post-processing for generation outputs.

Inference adapters produce a validated mono WAV.  The worker owns the output
format conversion so model runtimes do not need to know about storage formats.
FFmpeg is invoked with fixed arguments and receives audio through stdin; no
user-controlled shell command or filesystem path is ever interpolated.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from collections.abc import Callable

from app.inference.adapter import InferenceError, InferenceResult

MAX_OUTPUT_BYTES = 25_000_000
MAX_OUTPUT_DURATION_MS = 120_000


class AudioPostProcessor:
    """Normalize an inference result to the requested private output format."""

    def __init__(
        self,
        *,
        converter: Callable[[bytes], bytes] | None = None,
        ffmpeg_binary: str = "ffmpeg",
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._converter = converter
        self._ffmpeg_binary = ffmpeg_binary
        self._timeout_seconds = timeout_seconds

    async def normalize(
        self,
        result: InferenceResult,
        output_format: str,
    ) -> InferenceResult:
        if output_format == "wav":
            if result.content_type != "audio/wav":
                raise InferenceError(
                    "INFERENCE_FORMAT_INVALID", "The worker expected a WAV inference result."
                )
            _validate_wav_header(result.audio_bytes)
            _validate_limits(result.audio_bytes, result.duration_ms)
            return result
        if output_format != "mp3":
            raise InferenceError("INFERENCE_FORMAT_UNSUPPORTED", "Output format is unsupported.")

        if result.content_type == "audio/mpeg":
            audio = result.audio_bytes
            converter_name = "inference-adapter"
        elif result.content_type == "audio/wav":
            _validate_wav_header(result.audio_bytes)
            _validate_limits(result.audio_bytes, result.duration_ms)
            try:
                audio = await asyncio.to_thread(self._convert, result.audio_bytes)
            except InferenceError:
                raise
            except (OSError, subprocess.SubprocessError) as error:
                raise InferenceError(
                    "INFERENCE_POSTPROCESS_FAILED",
                    "Audio could not be converted to MP3.",
                    retryable=True,
                ) from error
            converter_name = "injected" if self._converter is not None else "ffmpeg"
        else:
            raise InferenceError(
                "INFERENCE_FORMAT_INVALID", "The inference result has an unsupported MIME type."
            )

        _validate_mp3_header(audio)
        _validate_limits(audio, result.duration_ms)
        metadata = dict(result.metadata)
        metadata["postprocessing"] = {
            "source_content_type": result.content_type,
            "source_sha256": result.sha256,
            "target_content_type": "audio/mpeg",
            "converter": converter_name,
        }
        return InferenceResult(
            audio_bytes=audio,
            content_type="audio/mpeg",
            sample_rate_hz=result.sample_rate_hz,
            channels=result.channels,
            duration_ms=result.duration_ms,
            sha256=hashlib.sha256(audio).hexdigest(),
            metadata=metadata,
        )

    def _convert(self, source_wav: bytes) -> bytes:
        if self._converter is not None:
            converted = self._converter(source_wav)
            if not isinstance(converted, bytes):
                raise InferenceError(
                    "INFERENCE_POSTPROCESS_FAILED", "The audio converter returned invalid bytes."
                )
            return converted
        completed = subprocess.run(
            [
                self._ffmpeg_binary,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "wav",
                "-i",
                "pipe:0",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=source_wav,
            capture_output=True,
            check=False,
            timeout=self._timeout_seconds,
        )
        if completed.returncode != 0 or not completed.stdout:
            raise InferenceError(
                "INFERENCE_POSTPROCESS_FAILED", "Audio could not be converted to MP3."
            )
        return completed.stdout


def _validate_limits(audio: bytes, duration_ms: int) -> None:
    if not audio or len(audio) > MAX_OUTPUT_BYTES:
        raise InferenceError("INFERENCE_OUTPUT_INVALID", "Audio output exceeds the size limit.")
    if duration_ms <= 0 or duration_ms > MAX_OUTPUT_DURATION_MS:
        raise InferenceError("INFERENCE_OUTPUT_INVALID", "Audio output duration is invalid.")


def _validate_wav_header(audio: bytes) -> None:
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise InferenceError("INFERENCE_OUTPUT_INVALID", "Audio output is not a valid WAV file.")


def _validate_mp3_header(audio: bytes) -> None:
    if len(audio) < 4:
        raise InferenceError("INFERENCE_OUTPUT_INVALID", "Audio output is not a valid MP3 file.")
    if audio[:3] == b"ID3":
        return
    for index in range(min(len(audio) - 1, 4096)):
        if audio[index] == 0xFF and audio[index + 1] & 0xE0 == 0xE0:
            return
    raise InferenceError("INFERENCE_OUTPUT_INVALID", "Audio output is not a valid MP3 file.")
