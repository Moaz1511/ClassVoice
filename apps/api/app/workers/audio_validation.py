"""Deterministic audio validation for quarantined voice samples.

The validator deliberately separates container probing/decoding from policy so
fixture tests never need a real FFmpeg process, while the production inspector
uses the sandboxed ``ffprobe``/``ffmpeg`` binaries in the worker image.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

MAX_REFERENCE_BYTES = 25_000_000
MIN_DURATION_SECONDS = 6.0
MAX_DURATION_SECONDS = 30.0
_SILENCE_SAMPLE_THRESHOLD = 500
_SILENCE_RATIO_LIMIT = 0.98
_CLIPPING_SAMPLE_THRESHOLD = 32_760
_CLIPPING_RATIO_LIMIT = 0.01


class AudioValidationCode(StrEnum):
    ACCEPTED = "accepted"
    INVALID_SIZE = "invalid_size"
    INVALID_FILENAME = "invalid_filename"
    MAGIC_BYTES_MISMATCH = "magic_bytes_mismatch"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CORRUPT_AUDIO = "corrupt_audio"
    DURATION_TOO_SHORT = "duration_too_short"
    DURATION_TOO_LONG = "duration_too_long"
    INVALID_CHANNELS = "invalid_channels"
    SILENCE_DETECTED = "silence_detected"
    CLIPPING_DETECTED = "clipping_detected"


@dataclass(frozen=True, slots=True)
class AudioProbe:
    duration_seconds: float
    channels: int
    sample_rate: int
    codec: str
    speaker_count: int | None = None


@dataclass(frozen=True, slots=True)
class AudioValidationResult:
    accepted: bool
    code: AudioValidationCode
    format: str | None
    duration_seconds: float | None
    channels: int | None
    sample_rate: int | None
    codec: str | None
    silence_ratio: float | None
    clipping_ratio: float | None
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "code": self.code.value,
            "format": self.format,
            "duration_seconds": self.duration_seconds,
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "codec": self.codec,
            "silence_ratio": self.silence_ratio,
            "clipping_ratio": self.clipping_ratio,
            "warnings": list(self.warnings),
        }


class AudioInspector(Protocol):
    def inspect(self, path: Path) -> tuple[AudioProbe, tuple[int, ...]]: ...


class FFmpegAudioInspector:
    """Probe and decode audio through bounded subprocess calls."""

    def __init__(self, *, ffprobe_binary: str = "ffprobe", ffmpeg_binary: str = "ffmpeg") -> None:
        self._ffprobe = ffprobe_binary
        self._ffmpeg = ffmpeg_binary

    def inspect(self, path: Path) -> tuple[AudioProbe, tuple[int, ...]]:
        probe = self._probe(path)
        decoded = subprocess.run(
            [
                self._ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-i",
                os.fspath(path),
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
            timeout=20,
        )
        if decoded.returncode != 0 or len(decoded.stdout) < 2:
            raise ValueError("FFmpeg could not decode audio")
        samples = tuple(
            int.from_bytes(decoded.stdout[index : index + 2], "little", signed=True)
            for index in range(0, len(decoded.stdout) - 1, 2)
        )
        return probe, samples

    def _probe(self, path: Path) -> AudioProbe:
        result = subprocess.run(
            [
                self._ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_name,codec_type,channels,sample_rate",
                "-of",
                "json",
                os.fspath(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise ValueError("FFprobe could not inspect audio")
        payload = json.loads(result.stdout)
        streams = [
            stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"
        ]
        if not streams:
            raise ValueError("No audio stream found")
        stream = streams[0]
        duration = float(payload.get("format", {}).get("duration", 0.0))
        channels = int(stream.get("channels", 0))
        sample_rate = int(stream.get("sample_rate", 0))
        codec = str(stream.get("codec_name", ""))
        if duration <= 0 or channels <= 0 or sample_rate <= 0 or not codec:
            raise ValueError("Audio metadata is incomplete")
        return AudioProbe(duration, channels, sample_rate, codec)


class AudioValidator:
    def __init__(self, inspector: AudioInspector | None = None) -> None:
        self._inspector = inspector or FFmpegAudioInspector()

    def validate(self, data: bytes, *, filename: str, content_type: str) -> AudioValidationResult:
        if not data or len(data) > MAX_REFERENCE_BYTES:
            return self._rejected(AudioValidationCode.INVALID_SIZE)
        format_name = sniff_audio_format(data)
        if format_name is None:
            return self._rejected(AudioValidationCode.MAGIC_BYTES_MISMATCH)
        if not _format_matches(filename, content_type, format_name):
            return self._rejected(AudioValidationCode.MAGIC_BYTES_MISMATCH, format_name)
        suffix = Path(filename).suffix.lower()
        try:
            with tempfile.NamedTemporaryFile(
                prefix="classvoice-audio-", suffix=suffix, delete=True
            ) as handle:
                handle.write(data)
                handle.flush()
                probe, samples = self._inspector.inspect(Path(handle.name))
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            return self._rejected(AudioValidationCode.CORRUPT_AUDIO, format_name)
        if probe.duration_seconds < MIN_DURATION_SECONDS:
            return self._result(
                AudioValidationCode.DURATION_TOO_SHORT, format_name, probe, None, None
            )
        if probe.duration_seconds > MAX_DURATION_SECONDS:
            return self._result(
                AudioValidationCode.DURATION_TOO_LONG, format_name, probe, None, None
            )
        if probe.channels <= 0 or probe.channels > 2:
            return self._result(
                AudioValidationCode.INVALID_CHANNELS, format_name, probe, None, None
            )
        silence_ratio = _ratio(samples, lambda sample: abs(sample) <= _SILENCE_SAMPLE_THRESHOLD)
        clipping_ratio = _ratio(samples, lambda sample: abs(sample) >= _CLIPPING_SAMPLE_THRESHOLD)
        if silence_ratio >= _SILENCE_RATIO_LIMIT:
            return self._result(
                AudioValidationCode.SILENCE_DETECTED,
                format_name,
                probe,
                silence_ratio,
                clipping_ratio,
            )
        if clipping_ratio >= _CLIPPING_RATIO_LIMIT:
            return self._result(
                AudioValidationCode.CLIPPING_DETECTED,
                format_name,
                probe,
                silence_ratio,
                clipping_ratio,
            )
        warnings: tuple[str, ...] = ("stereo_input",) if probe.channels == 2 else ()
        if probe.speaker_count is not None and probe.speaker_count > 1:
            warnings += ("multiple_speakers_detected",)
        return self._result(
            AudioValidationCode.ACCEPTED,
            format_name,
            probe,
            silence_ratio,
            clipping_ratio,
            warnings,
        )

    @staticmethod
    def _rejected(
        code: AudioValidationCode, format_name: str | None = None
    ) -> AudioValidationResult:
        return AudioValidationResult(
            False, code, format_name, None, None, None, None, None, None, ()
        )

    @staticmethod
    def _result(
        code: AudioValidationCode,
        format_name: str,
        probe: AudioProbe,
        silence_ratio: float | None,
        clipping_ratio: float | None,
        warnings: tuple[str, ...] = (),
    ) -> AudioValidationResult:
        return AudioValidationResult(
            code == AudioValidationCode.ACCEPTED,
            code,
            format_name,
            probe.duration_seconds,
            probe.channels,
            probe.sample_rate,
            probe.codec,
            silence_ratio,
            clipping_ratio,
            warnings,
        )


def sniff_audio_format(data: bytes) -> str | None:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a"
    return None


def _format_matches(filename: str, content_type: str, format_name: str) -> bool:
    suffix = Path(filename).suffix.lower()
    type_matches = {
        "wav": {".wav", "audio/wav", "audio/x-wav"},
        "mp3": {".mp3", "audio/mpeg", "audio/mp3"},
        "m4a": {".m4a", "audio/mp4", "audio/x-m4a"},
    }
    allowed = type_matches.get(format_name, set())
    return suffix in allowed and content_type.lower() in allowed


def _ratio(samples: tuple[int, ...], predicate: object) -> float:
    if not samples:
        return 1.0
    check = predicate
    if not callable(check):
        return 0.0
    return sum(1 for sample in samples if check(sample)) / len(samples)
