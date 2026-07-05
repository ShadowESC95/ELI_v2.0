"""Claims suite bootstrap — fresh clones self-verify without manual steps."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_claims_artifacts():
    script = _REPO / "tools" / "bootstrap_claims_artifacts.py"
    if not script.is_file():
        pytest.skip("bootstrap_claims_artifacts.py missing")
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "bootstrap failed").strip()
        pytest.fail(f"claims bootstrap failed: {msg}")
