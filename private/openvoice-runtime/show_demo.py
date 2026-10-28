import json
from pathlib import Path

notebook = json.loads(Path("private/openvoice-runtime/OpenVoice/demo_part3.ipynb").read_text(encoding="utf-8"))
for cell in notebook["cells"]:
    source = "".join(cell.get("source", []))
    if any(term in source for term in ("ToneColorConverter", "BaseSpeakerTTS", "MeloTTS", "tts_to_file", "target_se", "source_se")):
        print("--- CELL ---")
        print(source.encode("ascii", "backslashreplace").decode("ascii"))
