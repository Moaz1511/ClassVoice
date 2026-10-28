"""Export the FastAPI OpenAPI document used by the generated TypeScript client."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packages" / "api-client" / "openapi.json"


def _venv_python() -> Path | None:
    candidates = (
        ROOT / "apps" / "api" / ".venv" / "Scripts" / "python.exe",
        ROOT / "apps" / "api" / ".venv" / "bin" / "python",
    )
    return next((candidate for candidate in candidates if candidate.exists()), None)


def main() -> None:
    # Let a repository-local API virtualenv supply FastAPI when this script is
    # launched by npm or a system Python. CI already runs the direct branch.
    venv_python = _venv_python()
    if "--direct" not in sys.argv and venv_python and Path(sys.executable).resolve() != venv_python.resolve():
        subprocess.run([str(venv_python), str(Path(__file__).resolve()), "--direct"], check=True)
        return

    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from app.main import app  # noqa: PLC0415

    document = app.openapi()
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    os.environ.setdefault("APP_ENV", "test")
    main()
