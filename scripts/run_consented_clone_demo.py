"""Generate private, consent-confirmed OpenVoice demo outputs on the local GPU.

The script never downloads model weights. It requires the repository's pinned
OpenVoice V2 checkpoint and writes only beneath ``private/``. Bengali input is
provided as already-synthesized base speech because MeloTTS has no Bengali
base speaker; tone-color conversion remains local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CHECKPOINT_SHA256 = "9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e"
MAX_TEXT_CHARACTERS = 500
MAX_OUTPUT_BYTES = 25_000_000
MAX_OUTPUT_DURATION_MS = 120_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value or len(value) > MAX_TEXT_CHARACTERS:
        raise ValueError(f"text must contain 1-{MAX_TEXT_CHARACTERS} characters")
    return value


def _manifest_entry(root: Path) -> dict[str, Any]:
    payload = json.loads(
        (root / "infra" / "model-registry" / "manifest.json").read_text(encoding="utf-8")
    )
    for entry in payload.get("models", []):
        if entry.get("model_key") == "openvoice-v2" and entry.get("version") == "2.0.0":
            return dict(entry)
    raise RuntimeError("OpenVoice V2 is missing from the model registry")


def _wav_metadata(path: Path) -> dict[str, int]:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        duration_ms = round(handle.getnframes() * 1000 / sample_rate)
    byte_size = path.stat().st_size
    if (
        channels != 1
        or sample_width != 2
        or duration_ms <= 0
        or duration_ms > MAX_OUTPUT_DURATION_MS
        or byte_size <= 0
        or byte_size > MAX_OUTPUT_BYTES
    ):
        raise RuntimeError(f"generated WAV failed output limits: {path.name}")
    return {
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "duration_ms": duration_ms,
        "byte_size": byte_size,
    }


def _encode_mp3(source: Path, destination: Path) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg is required to create MP3 output")
    subprocess.run(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "3",
            str(destination),
        ],
        check=True,
        timeout=60,
    )
    if destination.stat().st_size <= 0 or destination.stat().st_size > MAX_OUTPUT_BYTES:
        raise RuntimeError(f"generated MP3 failed output limits: {destination.name}")


def _private_output(root: Path, requested: Path) -> Path:
    output = requested.resolve()
    private_root = (root / "private").resolve()
    try:
        output.relative_to(private_root)
    except ValueError as error:
        raise ValueError("output directory must be beneath the repository private directory") from error
    output.mkdir(parents=True, exist_ok=True)
    return output


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    if not arguments.confirm_consent:
        raise ValueError("--confirm-consent is required")

    root = arguments.root.resolve()
    reference = arguments.reference_audio.resolve()
    english_text_path = arguments.english_text_file.resolve()
    bengali_text_path = arguments.bengali_text_file.resolve()
    bengali_source = arguments.bengali_source_audio.resolve()
    for required in (reference, english_text_path, bengali_text_path, bengali_source):
        if not required.is_file():
            raise FileNotFoundError(required)

    output_dir = _private_output(root, arguments.output_dir)
    model_root = root / "private" / "models" / "OpenVoiceV2"
    checkpoint = model_root / "converter" / "checkpoint.pth"
    manifest = _manifest_entry(root)
    checkpoint_sha = _sha256(checkpoint)
    if (
        manifest.get("license_review_status") != "approved"
        or manifest.get("checkpoint_sha256") != CHECKPOINT_SHA256
        or checkpoint_sha != CHECKPOINT_SHA256
    ):
        raise RuntimeError("checkpoint failed the repository license/SHA gate")

    # Cached assets are mandatory; model downloads during inference are prohibited.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    import soundfile as sf
    import torch
    import wavmark
    from melo.api import TTS
    from openvoice.api import ToneColorConverter

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in the isolated OpenVoice runtime")

    class _NoWatermark:
        def to(self, _device: str) -> _NoWatermark:
            return self

    def load_no_watermark() -> _NoWatermark:
        return _NoWatermark()

    wavmark.load_model = load_no_watermark
    english_text = _text(english_text_path)
    bengali_text = _text(bengali_text_path)
    english_source = output_dir / "english-base.wav"
    english_wav = output_dir / "english-cloned.wav"
    bengali_wav = output_dir / "bangla-cloned.wav"

    started = time.perf_counter()
    converter = ToneColorConverter(
        str(model_root / "converter" / "config.json"),
        device="cuda",
    )
    converter.watermark_model = None
    converter.load_ckpt(str(checkpoint))
    target_se = converter.extract_se(str(reference))

    tts = TTS(language="EN", device="cuda", use_hf=True)
    speaker_id = tts.hps.data.spk2id["EN-US"]
    english_source_se = torch.load(
        model_root / "base_speakers" / "ses" / "en-us.pth",
        map_location="cuda",
        weights_only=True,
    )
    tts.tts_to_file(english_text, speaker_id, str(english_source), speed=1.0, quiet=True)
    converter.convert(
        audio_src_path=str(english_source),
        src_se=english_source_se,
        tgt_se=target_se,
        output_path=str(english_wav),
        message="@ClassVoice-consented-demo",
    )

    bengali_source_se = converter.extract_se(str(bengali_source))
    converter.convert(
        audio_src_path=str(bengali_source),
        src_se=bengali_source_se,
        tgt_se=target_se,
        output_path=str(bengali_wav),
        message="@ClassVoice-consented-demo",
    )
    torch.cuda.synchronize()

    results: dict[str, Any] = {}
    for language, wav_path in (("english", english_wav), ("bangla", bengali_wav)):
        audio, sample_rate = sf.read(wav_path)
        if len(audio) == 0 or sample_rate <= 0:
            raise RuntimeError(f"soundfile rejected generated output: {wav_path.name}")
        mp3_path = wav_path.with_suffix(".mp3")
        _encode_mp3(wav_path, mp3_path)
        metadata = _wav_metadata(wav_path)
        metadata.update(
            {
                "wav_sha256": _sha256(wav_path),
                "mp3_sha256": _sha256(mp3_path),
                "wav_path": str(wav_path),
                "mp3_path": str(mp3_path),
            }
        )
        results[language] = metadata

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pass",
        "consent_confirmed": True,
        "device": torch.cuda.get_device_name(0),
        "checkpoint_sha256": checkpoint_sha,
        "reference_sha256": _sha256(reference),
        "english_text_sha256": hashlib.sha256(english_text.encode("utf-8")).hexdigest(),
        "bengali_text_sha256": hashlib.sha256(bengali_text.encode("utf-8")).hexdigest(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "results": results,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-audio", type=Path, required=True)
    parser.add_argument("--english-text-file", type=Path, required=True)
    parser.add_argument("--bengali-text-file", type=Path, required=True)
    parser.add_argument("--bengali-source-audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--confirm-consent", action="store_true")
    return parser


def main() -> int:
    try:
        report = run(_parser().parse_args())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"clone demo failed: {error}") from error
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
