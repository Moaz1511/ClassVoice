"""Deterministic, resource-bounded validation for quarantined voice samples.

Container validation runs before FFprobe/FFmpeg. Metadata is then probed before
PCM decoding so duration/channel policy can reject an input without expanding
it. The production decoder has independent time and output-size ceilings.
"""

from __future__ import annotations

import json
import math
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
DECODE_SAMPLE_RATE_HZ = 16_000
MAX_DECODED_PCM_BYTES = int(MAX_DURATION_SECONDS * DECODE_SAMPLE_RATE_HZ * 2)
DECODE_GUARD_SECONDS = 1.0
MAX_CAPTURED_PCM_BYTES = int(
    (MAX_DURATION_SECONDS + DECODE_GUARD_SECONDS) * DECODE_SAMPLE_RATE_HZ * 2
)
MAX_PROBE_OUTPUT_CHARACTERS = 64_000
MAX_FFMPEG_ALLOCATION_BYTES = 64 * 1024 * 1024
FFPROBE_TIMEOUT_SECONDS = 10.0
FFMPEG_TIMEOUT_SECONDS = 20.0
_SILENCE_SAMPLE_THRESHOLD = 500
_SILENCE_RATIO_LIMIT = 0.98
_CLIPPING_SAMPLE_THRESHOLD = 32_760
_CLIPPING_RATIO_LIMIT = 0.01
_FOREIGN_PAYLOAD_MAGICS = (
    b"PK\x03\x04",  # ZIP/JAR/OOXML
    b"%PDF-",
    b"\x7fELF",
    b"\x89PNG\r\n\x1a\n",
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
)


class AudioValidationCode(StrEnum):
    ACCEPTED = "accepted"
    INVALID_SIZE = "invalid_size"
    INVALID_FILENAME = "invalid_filename"
    MAGIC_BYTES_MISMATCH = "magic_bytes_mismatch"
    UNSUPPORTED_FORMAT = "unsupported_format"
    MALFORMED_CONTAINER = "malformed_container"
    POLYGLOT_DETECTED = "polyglot_detected"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    CORRUPT_AUDIO = "corrupt_audio"
    DURATION_TOO_SHORT = "duration_too_short"
    DURATION_TOO_LONG = "duration_too_long"
    INVALID_CHANNELS = "invalid_channels"
    SILENCE_DETECTED = "silence_detected"
    CLIPPING_DETECTED = "clipping_detected"


class AudioInspectionError(ValueError):
    """A classified, user-safe failure from the media inspection boundary."""

    def __init__(self, code: AudioValidationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    def probe(self, path: Path) -> AudioProbe: ...

    def decode_pcm(self, path: Path) -> tuple[int, ...]: ...


class FFmpegAudioInspector:
    """Probe and decode audio through fixed, resource-bounded subprocesses."""

    def __init__(self, *, ffprobe_binary: str = "ffprobe", ffmpeg_binary: str = "ffmpeg") -> None:
        self._ffprobe = ffprobe_binary
        self._ffmpeg = ffmpeg_binary

    def probe(self, path: Path) -> AudioProbe:
        try:
            result = subprocess.run(
                [
                    self._ffprobe,
                    "-max_alloc",
                    str(MAX_FFMPEG_ALLOCATION_BYTES),
                    "-protocol_whitelist",
                    "file,pipe",
                    "-v",
                    "error",
                    "-probesize",
                    "1000000",
                    "-analyzeduration",
                    "5000000",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "format=duration:stream=codec_name,codec_type,channels,sample_rate,duration",
                    "-of",
                    "json",
                    os.fspath(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=FFPROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise AudioInspectionError(
                AudioValidationCode.RESOURCE_LIMIT_EXCEEDED,
                "Audio probing exceeded its resource limit.",
            ) from error
        if result.returncode != 0:
            raise AudioInspectionError(
                AudioValidationCode.CORRUPT_AUDIO, "FFprobe could not inspect audio."
            )
        if len(result.stdout) > MAX_PROBE_OUTPUT_CHARACTERS:
            raise AudioInspectionError(
                AudioValidationCode.RESOURCE_LIMIT_EXCEEDED,
                "Audio metadata exceeded its resource limit.",
            )
        try:
            payload = json.loads(result.stdout)
            streams = [
                stream
                for stream in payload.get("streams", [])
                if stream.get("codec_type") == "audio"
            ]
            if not streams:
                raise ValueError("No audio stream found")
            stream = streams[0]
            duration_value = payload.get("format", {}).get("duration") or stream.get("duration")
            duration = float(duration_value or 0.0)
            channels = int(stream.get("channels", 0))
            sample_rate = int(stream.get("sample_rate", 0))
            codec = str(stream.get("codec_name", ""))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AudioInspectionError(
                AudioValidationCode.CORRUPT_AUDIO, "Audio metadata is malformed."
            ) from error
        if (
            not math.isfinite(duration)
            or duration <= 0
            or channels <= 0
            or sample_rate <= 0
            or not codec
        ):
            raise AudioInspectionError(
                AudioValidationCode.CORRUPT_AUDIO, "Audio metadata is incomplete."
            )
        return AudioProbe(duration, channels, sample_rate, codec)

    def decode_pcm(self, path: Path) -> tuple[int, ...]:
        try:
            decoded = subprocess.run(
                [
                    self._ffmpeg,
                    "-max_alloc",
                    str(MAX_FFMPEG_ALLOCATION_BYTES),
                    "-protocol_whitelist",
                    "file,pipe",
                    "-nostdin",
                    "-v",
                    "error",
                    "-xerror",
                    "-err_detect",
                    "explode",
                    "-i",
                    os.fspath(path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-threads",
                    "1",
                    "-t",
                    str(MAX_DURATION_SECONDS + DECODE_GUARD_SECONDS),
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ac",
                    "1",
                    "-ar",
                    str(DECODE_SAMPLE_RATE_HZ),
                    "-fs",
                    str(MAX_CAPTURED_PCM_BYTES),
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=FFMPEG_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise AudioInspectionError(
                AudioValidationCode.RESOURCE_LIMIT_EXCEEDED,
                "Audio decoding exceeded its resource limit.",
            ) from error
        if decoded.returncode != 0 or len(decoded.stdout) < 2 or len(decoded.stdout) % 2:
            raise AudioInspectionError(
                AudioValidationCode.CORRUPT_AUDIO, "FFmpeg could not decode audio."
            )
        if len(decoded.stdout) > MAX_DECODED_PCM_BYTES:
            raise AudioInspectionError(
                AudioValidationCode.RESOURCE_LIMIT_EXCEEDED,
                "Decoded audio exceeded its resource limit.",
            )
        return tuple(
            int.from_bytes(decoded.stdout[index : index + 2], "little", signed=True)
            for index in range(0, len(decoded.stdout), 2)
        )


class AudioValidator:
    def __init__(self, inspector: AudioInspector | None = None) -> None:
        self._inspector = inspector or FFmpegAudioInspector()

    def validate(self, data: bytes, *, filename: str, content_type: str) -> AudioValidationResult:
        if not data or len(data) > MAX_REFERENCE_BYTES:
            return self._rejected(AudioValidationCode.INVALID_SIZE)
        format_name = sniff_audio_format(data)
        if format_name is None:
            return self._rejected(AudioValidationCode.MAGIC_BYTES_MISMATCH)
        container_error = _validate_container(data, format_name)
        if container_error is not None:
            return self._rejected(container_error, format_name)
        if not _format_matches(filename, content_type, format_name):
            return self._rejected(AudioValidationCode.MAGIC_BYTES_MISMATCH, format_name)
        suffix = Path(filename).suffix.lower()
        try:
            with tempfile.NamedTemporaryFile(
                prefix="classvoice-audio-", suffix=suffix, delete=True
            ) as handle:
                handle.write(data)
                handle.flush()
                path = Path(handle.name)
                probe = self._inspector.probe(path)
                if probe.duration_seconds < MIN_DURATION_SECONDS:
                    return self._result(
                        AudioValidationCode.DURATION_TOO_SHORT,
                        format_name,
                        probe,
                        None,
                        None,
                    )
                if probe.duration_seconds > MAX_DURATION_SECONDS:
                    return self._result(
                        AudioValidationCode.DURATION_TOO_LONG,
                        format_name,
                        probe,
                        None,
                        None,
                    )
                if probe.channels <= 0 or probe.channels > 2:
                    return self._result(
                        AudioValidationCode.INVALID_CHANNELS,
                        format_name,
                        probe,
                        None,
                        None,
                    )
                samples = self._inspector.decode_pcm(path)
        except AudioInspectionError as error:
            return self._rejected(error.code, format_name)
        except subprocess.TimeoutExpired:
            return self._rejected(AudioValidationCode.RESOURCE_LIMIT_EXCEEDED, format_name)
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            return self._rejected(AudioValidationCode.CORRUPT_AUDIO, format_name)
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
    if data.startswith(b"ID3") or _valid_mp3_frame_header(data, 0):
        return "mp3"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a"
    return None


def _validate_container(data: bytes, format_name: str) -> AudioValidationCode | None:
    if format_name == "wav":
        return _validate_wav_container(data)
    if format_name == "mp3":
        return _validate_mp3_container(data)
    if format_name == "m4a":
        return _validate_m4a_container(data)
    return AudioValidationCode.UNSUPPORTED_FORMAT


def _validate_wav_container(data: bytes) -> AudioValidationCode | None:
    if len(data) < 44:
        return AudioValidationCode.MALFORMED_CONTAINER
    declared_end = int.from_bytes(data[4:8], "little") + 8
    if declared_end != len(data):
        if declared_end < len(data) and _starts_with_foreign_payload(data, declared_end):
            return AudioValidationCode.POLYGLOT_DETECTED
        return AudioValidationCode.MALFORMED_CONTAINER
    offset = 12
    has_format = False
    has_audio = False
    while offset < len(data):
        if _starts_with_foreign_payload(data, offset):
            return AudioValidationCode.POLYGLOT_DETECTED
        if offset + 8 > len(data):
            return AudioValidationCode.MALFORMED_CONTAINER
        chunk_name = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        chunk_end = offset + 8 + chunk_size
        padded_end = chunk_end + (chunk_size % 2)
        if chunk_end > len(data) or padded_end > len(data):
            return AudioValidationCode.MALFORMED_CONTAINER
        if chunk_name == b"fmt ":
            if chunk_size < 16:
                return AudioValidationCode.MALFORMED_CONTAINER
            has_format = True
        elif chunk_name == b"data":
            if chunk_size == 0:
                return AudioValidationCode.MALFORMED_CONTAINER
            has_audio = True
        offset = padded_end
    if offset != len(data) or not has_format or not has_audio:
        return AudioValidationCode.MALFORMED_CONTAINER
    return None


def _validate_mp3_container(data: bytes) -> AudioValidationCode | None:
    frame_offset = 0
    if data.startswith(b"ID3"):
        if len(data) < 14 or data[3] == 0xFF or data[4] == 0xFF:
            return AudioValidationCode.MALFORMED_CONTAINER
        size_bytes = data[6:10]
        if any(value & 0x80 for value in size_bytes):
            return AudioValidationCode.MALFORMED_CONTAINER
        tag_size = sum(
            value << shift
            for value, shift in zip(size_bytes, (21, 14, 7, 0), strict=True)
        )
        footer_size = 10 if data[5] & 0x10 else 0
        frame_offset = 10 + tag_size + footer_size
    if not _valid_mp3_frame_header(data, frame_offset):
        return AudioValidationCode.MALFORMED_CONTAINER
    if _find_foreign_payload(data, frame_offset + 4) is not None:
        return AudioValidationCode.POLYGLOT_DETECTED
    return None


def _valid_mp3_frame_header(data: bytes, offset: int) -> bool:
    if offset < 0 or offset + 4 > len(data):
        return False
    header = int.from_bytes(data[offset : offset + 4], "big")
    sync = (header >> 21) & 0x7FF
    version = (header >> 19) & 0x3
    layer = (header >> 17) & 0x3
    bitrate_index = (header >> 12) & 0xF
    sample_rate_index = (header >> 10) & 0x3
    return (
        sync == 0x7FF
        and version != 0x1
        and layer != 0x0
        and bitrate_index not in {0x0, 0xF}
        and sample_rate_index != 0x3
    )


def _validate_m4a_container(data: bytes) -> AudioValidationCode | None:
    offset = 0
    box_names: set[bytes] = set()
    first_box = True
    while offset < len(data):
        if _starts_with_foreign_payload(data, offset):
            return AudioValidationCode.POLYGLOT_DETECTED
        if offset + 8 > len(data):
            return AudioValidationCode.MALFORMED_CONTAINER
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_name = data[offset + 4 : offset + 8]
        header_size = 8
        if size == 1:
            if offset + 16 > len(data):
                return AudioValidationCode.MALFORMED_CONTAINER
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(data) - offset
        if size < header_size or offset + size > len(data):
            return AudioValidationCode.MALFORMED_CONTAINER
        if first_box and box_name != b"ftyp":
            return AudioValidationCode.MALFORMED_CONTAINER
        if box_name == b"ftyp" and size < 16:
            return AudioValidationCode.MALFORMED_CONTAINER
        box_names.add(box_name)
        offset += size
        first_box = False
    if offset != len(data) or b"ftyp" not in box_names or b"mdat" not in box_names:
        return AudioValidationCode.MALFORMED_CONTAINER
    if b"moov" not in box_names and b"moof" not in box_names:
        return AudioValidationCode.MALFORMED_CONTAINER
    return None


def _starts_with_foreign_payload(data: bytes, offset: int) -> bool:
    return any(data.startswith(magic, offset) for magic in _FOREIGN_PAYLOAD_MAGICS)


def _find_foreign_payload(data: bytes, start: int) -> int | None:
    offsets = [
        offset
        for magic in _FOREIGN_PAYLOAD_MAGICS
        if (offset := data.find(magic, start)) >= 0
    ]
    return min(offsets, default=None)


def _format_matches(filename: str, content_type: str, format_name: str) -> bool:
    suffix = Path(filename).suffix.lower()
    type_matches = {
        "wav": ({".wav"}, {"audio/wav", "audio/x-wav"}),
        "mp3": ({".mp3"}, {"audio/mpeg", "audio/mp3"}),
        "m4a": ({".m4a"}, {"audio/mp4", "audio/x-m4a"}),
    }
    allowed_suffixes, allowed_content_types = type_matches.get(format_name, (set(), set()))
    return suffix in allowed_suffixes and content_type.lower() in allowed_content_types


def _ratio(samples: tuple[int, ...], predicate: object) -> float:
    if not samples:
        return 1.0
    check = predicate
    if not callable(check):
        return 0.0
    return sum(1 for sample in samples if check(sample)) / len(samples)
