import hashlib
import json
import wave
from pathlib import Path

import soundfile as sf
import torch
import wavmark

from melo.api import TTS
from openvoice.api import ToneColorConverter


class _NoWatermark:
    def to(self, _device):
        return self


wavmark.load_model = lambda: _NoWatermark()


ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "private" / "models" / "OpenVoiceV2"
SOURCE_ROOT = ROOT / "private" / "openvoice-runtime" / "OpenVoice"
OUTPUT_ROOT = ROOT / "private" / "openvoice-runtime" / "outputs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

converter = ToneColorConverter(
    str(MODEL_ROOT / "converter" / "config.json"),
    device="cpu",
)
converter.watermark_model = None
converter.load_ckpt(str(MODEL_ROOT / "converter" / "checkpoint.pth"))

reference = SOURCE_ROOT / "resources" / "example_reference.mp3"
target_se = converter.extract_se(str(reference))

tts = TTS(language="EN", device="cpu", use_hf=True)
speaker_id = tts.hps.data.spk2id["EN-US"]
source_wav = OUTPUT_ROOT / "openvoice-smoke-source.wav"
tts.tts_to_file(
    "This is a ClassVoice OpenVoice V2 runtime smoke test.",
    speaker_id,
    str(source_wav),
    speed=1.0,
    quiet=True,
)

source_se = torch.load(
    MODEL_ROOT / "base_speakers" / "ses" / "en-us.pth",
    map_location="cpu",
)
output_wav = OUTPUT_ROOT / "openvoice-smoke-output.wav"
converter.convert(
    audio_src_path=str(source_wav),
    src_se=source_se,
    tgt_se=target_se,
    output_path=str(output_wav),
    message="@ClassVoice",
)

audio, sample_rate = sf.read(output_wav)
duration_ms = round(len(audio) * 1000 / sample_rate)
sha256 = hashlib.sha256(output_wav.read_bytes()).hexdigest()
with wave.open(str(output_wav), "rb") as wav_file:
    channels = wav_file.getnchannels()
    sample_width = wav_file.getsampwidth()

print(
    json.dumps(
        {
            "output": str(output_wav),
            "sample_rate_hz": sample_rate,
            "channels": channels,
            "sample_width_bytes": sample_width,
            "duration_ms": duration_ms,
            "sha256": sha256,
            "checkpoint_sha256": hashlib.sha256(
                (MODEL_ROOT / "converter" / "checkpoint.pth").read_bytes()
            ).hexdigest(),
            "settings": {"speed": 1.0, "stability": None, "style": None, "seed": None},
        },
        sort_keys=True,
    )
)
