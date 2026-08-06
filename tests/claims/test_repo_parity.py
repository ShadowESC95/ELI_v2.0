"""CLAIM: constructs that should exist in both trees actually do.

v2 and v3 have different root commits, so git cannot compare them and a missed
port raises no error — the construct is simply absent. This runs the parity
report and fails on unexplained divergence in the hard families.

Skips cleanly when no v3 checkout is present, so CI (which only ever sees one
repo) stays green while a local run is meaningful.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from . import _helpers as H

TOOL = H.REPO / "tools" / "repo_parity.py"

sys.path.insert(0, str(H.REPO / "tools"))


def _v3():
    import repo_parity  # type: ignore
    return repo_parity.find_v3()


def test_parity_tool_exists():
    assert TOOL.is_file(), "tools/repo_parity.py missing"


@pytest.mark.skipif(_v3() is None, reason="no v3 checkout on this machine")
def test_no_unexplained_divergence():
    r = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True)
    assert r.returncode == 0, (
        "unexplained v2/v3 divergence — port it, or record the intentional ones "
        f"in tools/repo_parity_allow.txt\n\n{r.stdout}\n{r.stderr}"
    )


@pytest.mark.skipif(_v3() is None, reason="no v3 checkout on this machine")
def test_prompt_guards_are_in_parity():
    """The specific failure this tool was built for: v3 shipped 8 days citing
    'the mirror of the rule above' for a guard that had never been ported."""
    import repo_parity  # type: ignore
    v3 = repo_parity.find_v3()
    v2_guards = repo_parity.guards(H.REPO)
    v3_guards = repo_parity.guards(v3)
    missing = sorted(v2_guards - v3_guards)
    assert not missing, f"prompt guards present in v2 but not v3: {missing}"
