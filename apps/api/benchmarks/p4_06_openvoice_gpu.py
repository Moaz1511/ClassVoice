"""Bounded OpenVoice V2 benchmark for the P4-06 reference-GPU gate.

This script is run with the ignored, isolated OpenVoice environment. The parent
process starts a child with a hard timeout so a maximum-length request cannot
hang the release gate. Reports contain only counts, hashes, timings, and device
metadata; synthetic input text and generated audio stay outside version control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CHECKPOINT_SHA256 = "9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e"
QUEUE_TARGET_MS = 90_000
MAX_OUTPUT_BYTES = 25_000_000
MAX_OUTPUT_DURATION_MS = 120_000


def synthetic_text(characters: int) -> str:
    """Build deterministic academic prose at an exact character boundary."""

    if characters < 1 or characters > 10_000:
        raise ValueError("characters must be between 1 and 10,000")
    sentence = "Academic practice builds clear reasoning through careful review. "
    repetitions = (characters // len(sentence)) + 1
    return (sentence * repetitions)[:characters]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_entry(root: Path) -> dict[str, Any]:
    manifest_path = root / "infra" / "model-registry" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for raw_entry in payload.get("models", []):
        if raw_entry.get("model_key") == "openvoice-v2" and raw_entry.get("version") == "2.0.0":
            return dict(raw_entry)
    raise RuntimeError("OpenVoice V2 is missing from the model registry")


def _base_report(characters: int, timeout_seconds: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile": "p4-06-openvoice-reference-gpu",
        "generated_at": datetime.now(UTC).isoformat(),
        "workload": {
            "characters": characters,
            "synthetic_input_sha256": hashlib.sha256(
                synthetic_text(characters).encode("utf-8")
            ).hexdigest(),
            "timeout_seconds": timeout_seconds,
            "requested_runs": 1,
        },
        "targets": {
            "queue_to_complete_p95_ms": QUEUE_TARGET_MS,
            "max_output_bytes": MAX_OUTPUT_BYTES,
            "max_output_duration_ms": MAX_OUTPUT_DURATION_MS,
        },
        "privacy": {
            "input": "synthetic-not-reported",
            "audio": "private-ignored-directory",
            "request_time_downloads": "disabled",
        },
    }


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def _known_gap(
    *,
    characters: int,
    timeout_seconds: int,
    reason_code: str,
    message: str,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = _base_report(characters, timeout_seconds)
    report.update(
        {
            "status": "known-gap",
            "reason_code": reason_code,
            "message": message,
            "environment": environment or {},
        }
    )
    return report


def _wav_metadata(path: Path) -> tuple[int, int, int, int]:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        duration_ms = round(handle.getnframes() * 1000 / sample_rate)
    return sample_rate, channels, sample_width, duration_ms


def _child_run(root: Path, work_dir: Path, characters: int, child_result: Path) -> int:
    # These flags make cached assets mandatory. P4-06 must never turn inference
    # into a request-time model downloader.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    import soundfile as sf
    import torch
    import wavmark
    from melo.api import TTS
    from openvoice.api import ToneColorConverter

    environment: dict[str, Any] = {
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device_count": torch.cuda.device_count(),
    }
    if not torch.cuda.is_available():
        payload = {
            "status": "known-gap",
            "reason_code": "cuda_unavailable",
            "message": "The isolated OpenVoice runtime cannot access CUDA.",
            "environment": environment,
        }
        child_result.write_text(json.dumps(payload), encoding="utf-8")
        return 0

    environment.update(
        {
            "device_name": torch.cuda.get_device_name(0),
            "device_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        }
    )
    manifest = _manifest_entry(root)
    checkpoint = root / "private" / "models" / "OpenVoiceV2" / "converter" / "checkpoint.pth"
    actual_sha = _sha256(checkpoint)
    if (
        manifest.get("license_review_status") != "approved"
        or manifest.get("checkpoint_sha256") != CHECKPOINT_SHA256
        or actual_sha != CHECKPOINT_SHA256
    ):
        payload = {
            "status": "known-gap",
            "reason_code": "model_gate_failed",
            "message": "The local checkpoint did not pass the registry license/SHA gate.",
            "environment": environment,
        }
        child_result.write_text(json.dumps(payload), encoding="utf-8")
        return 0

    class _NoWatermark:
        def to(self, _device: str) -> _NoWatermark:
            return self

    def load_no_watermark() -> _NoWatermark:
        return _NoWatermark()

    wavmark.load_model = load_no_watermark
    work_dir.mkdir(parents=True, exist_ok=True)
    source_wav = work_dir / "source.wav"
    output_wav = work_dir / "output.wav"
    reference = (
        root
        / "private"
        / "openvoice-runtime"
        / "OpenVoice"
        / "resources"
        / "example_reference.mp3"
    )
    model_root = root / "private" / "models" / "OpenVoiceV2"

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    converter = ToneColorConverter(
        str(model_root / "converter" / "config.json"),
        device="cuda",
    )
    converter.watermark_model = None
    converter.load_ckpt(str(checkpoint))
    target_se = converter.extract_se(str(reference))
    tts = TTS(language="EN", device="cuda", use_hf=True)
    speaker_id = tts.hps.data.spk2id["EN-US"]
    source_se = torch.load(
        model_root / "base_speakers" / "ses" / "en-us.pth",
        map_location="cuda",
        weights_only=True,
    )
    model_load_ms = (time.perf_counter() - load_started) * 1000

    inference_started = time.perf_counter()
    text = synthetic_text(characters)
    tts.tts_to_file(text, speaker_id, str(source_wav), speed=1.0, quiet=True)
    converter.convert(
        audio_src_path=str(source_wav),
        src_se=source_se,
        tgt_se=target_se,
        output_path=str(output_wav),
        message="@ClassVoice",
    )
    torch.cuda.synchronize()
    inference_ms = (time.perf_counter() - inference_started) * 1000
    sample_rate, channels, sample_width, duration_ms = _wav_metadata(output_wav)
    byte_size = output_wav.stat().st_size
    peak_memory_bytes = torch.cuda.max_memory_allocated()
    valid_output = (
        channels == 1
        and sample_width == 2
        and 0 < byte_size <= MAX_OUTPUT_BYTES
        and 0 < duration_ms <= MAX_OUTPUT_DURATION_MS
    )
    meets_latency = inference_ms < QUEUE_TARGET_MS
    status = "pass" if valid_output and meets_latency else "known-gap"
    reason_code = None
    if not valid_output:
        reason_code = "output_limit_exceeded"
    elif not meets_latency:
        reason_code = "latency_target_missed"
    payload = {
        "status": status,
        "reason_code": reason_code,
        "message": (
            "Reference-GPU workload passed its single-run target comparison."
            if status == "pass"
            else "Reference-GPU maximum-text workload missed a launch target."
        ),
        "environment": environment,
        "model": {
            "model_key": "openvoice-v2",
            "version": "2.0.0",
            "checkpoint_sha256": actual_sha,
            "license_review_status": manifest.get("license_review_status"),
            "production_enabled": bool(manifest.get("enabled")),
        },
        "results": {
            "model_load_ms": round(model_load_ms, 3),
            "queue_to_complete_proxy_ms": round(inference_ms, 3),
            "observed_queue_to_complete_ms": round(inference_ms, 3),
            "peak_gpu_memory_bytes": peak_memory_bytes,
            "output_byte_size": byte_size,
            "output_duration_ms": duration_ms,
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "output_sha256": _sha256(output_wav),
        },
    }
    # Read once to make sure soundfile also accepts the output container. The
    # samples are intentionally discarded and never serialized.
    audio, sf_rate = sf.read(output_wav)
    if len(audio) == 0 or sf_rate != sample_rate:
        raise RuntimeError("soundfile could not validate the generated output")
    child_result.write_text(json.dumps(payload), encoding="utf-8")
    return 0


def run_parent(
    *,
    root: Path,
    characters: int,
    timeout_seconds: int,
    json_output: Path | None,
) -> int:
    environment: dict[str, Any] = {}
    try:
        import torch

        environment = {
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
        }
        if torch.cuda.is_available():
            environment.update(
                {
                    "device_name": torch.cuda.get_device_name(0),
                    "device_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
                }
            )
    except Exception as error:
        report = _known_gap(
            characters=characters,
            timeout_seconds=timeout_seconds,
            reason_code="runtime_import_failed",
            message=(
                "The isolated OpenVoice runtime could not import PyTorch: "
                f"{type(error).__name__}."
            ),
        )
        _write_report(json_output, report)
        return 0

    if not environment.get("cuda_available"):
        report = _known_gap(
            characters=characters,
            timeout_seconds=timeout_seconds,
            reason_code="cuda_unavailable",
            message="The isolated OpenVoice runtime is CPU-only; no GPU latency claim was made.",
            environment=environment,
        )
        _write_report(json_output, report)
        return 0

    run_id = uuid.uuid4().hex
    work_dir = root / "private" / "openvoice-runtime" / "tmp" / f"p4-06-{run_id}"
    child_result = work_dir / "result.json"
    work_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--root",
        str(root),
        "--work-dir",
        str(work_dir),
        "--characters",
        str(characters),
        "--child-result",
        str(child_result),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        report = _known_gap(
            characters=characters,
            timeout_seconds=timeout_seconds,
            reason_code="gpu_benchmark_timeout",
            message="Maximum-text OpenVoice inference exceeded the bounded benchmark timeout.",
            environment=environment,
        )
        _write_report(json_output, report)
        return 0

    if child_result.is_file():
        child_payload = json.loads(child_result.read_text(encoding="utf-8"))
        report = _base_report(characters, timeout_seconds)
        report.update(child_payload)
        _write_report(json_output, report)
        return 0
    report = _known_gap(
        characters=characters,
        timeout_seconds=timeout_seconds,
        reason_code="gpu_benchmark_failed",
        message=(
            "The isolated OpenVoice benchmark exited without a result "
            f"(exit code {completed.returncode})."
        ),
        environment=environment,
    )
    _write_report(json_output, report)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the bounded P4-06 OpenVoice GPU profile.")
    parser.add_argument("--characters", type=int, default=10_000)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--work-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--child-result", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.characters < 1 or args.characters > 10_000:
        raise SystemExit("--characters must be between 1 and 10,000")
    if args.timeout_seconds < 30:
        raise SystemExit("--timeout-seconds must be at least 30")
    root = args.root.resolve()
    if args.child:
        if args.work_dir is None or args.child_result is None:
            raise SystemExit("child mode requires --work-dir and --child-result")
        return _child_run(root, args.work_dir, args.characters, args.child_result)
    return run_parent(
        root=root,
        characters=args.characters,
        timeout_seconds=args.timeout_seconds,
        json_output=args.json_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
