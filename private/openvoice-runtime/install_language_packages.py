import os
import subprocess
from pathlib import Path

temp_root = Path(__file__).resolve().parent / "tmp"
temp_root.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(temp_root)
os.environ["TMP"] = str(temp_root)

subprocess.run(
    [
        str(Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--no-deps",
        "g2p_en==2.1.0",
        "g2pkk==0.1.2",
        "pykakasi==2.2.1",
        "unidic==1.1.0",
        "unidic_lite==1.0.8",
    ],
    check=True,
)
