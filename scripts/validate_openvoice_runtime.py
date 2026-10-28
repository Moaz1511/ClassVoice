"""Run the isolated OpenVoice V2 CPU validation fixture.

The production API environment intentionally does not import PyTorch/OpenVoice.
This command delegates to the ignored, locally provisioned runtime environment
under ``private/openvoice-runtime`` and fails closed when it is absent.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PYTHON = ROOT / "private" / "openvoice-runtime" / ".venv" / "Scripts" / "python.exe"
SMOKE_SCRIPT = ROOT / "private" / "openvoice-runtime" / "run_openvoice_smoke.py"


def main() -> int:
    if not RUNTIME_PYTHON.is_file() or not SMOKE_SCRIPT.is_file():
        raise SystemExit(
            "OpenVoice runtime is not provisioned. See docs/06_Plan.md P2-11."
        )
    completed = subprocess.run([str(RUNTIME_PYTHON), str(SMOKE_SCRIPT)], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
