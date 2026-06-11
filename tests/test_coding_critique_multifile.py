"""Coding advancements D (self-critique) + E (atomic multi-file patch set)."""
import shutil
import tempfile
from pathlib import Path

import pytest


# ── D — self-critique ───────────────────────────────────────────────────────
def test_critique_returns_concrete_issues():
    from eli.coding.verification import critique_candidate
    issues = critique_candidate("sum a list", "def s(x): return x[0]",
                                lambda p, **k: "line 1: crashes on empty list; no None handling")
    assert "empty list" in issues


def test_critique_empty_when_ok_or_no_model():
    from eli.coding.verification import critique_candidate
    assert critique_candidate("x", "def s(x): return sum(x)", lambda p, **k: "OK") == ""
    assert critique_candidate("x", "code", generate=None) == ""


def test_agent_wires_critique():
    import inspect
    from eli.coding import agent
    assert "critique_candidate" in inspect.getsource(agent)


# ── E — atomic multi-file patch set ─────────────────────────────────────────
@pytest.fixture
def workspace():
    from eli.runtime.self_improvement import PROJECT_ROOT
    d = Path(tempfile.mkdtemp(prefix="patchset_", dir=str(PROJECT_ROOT / "artifacts")))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _eng():
    from eli.runtime.self_improvement import get_self_improvement
    return get_self_improvement()


def test_patch_set_applies_atomically(workspace):
    f1 = workspace / "a.py"; f1.write_text("X = 1\n")
    f2 = workspace / "b.py"; f2.write_text("Y = 2\n")
    r = _eng().apply_patch_set([
        {"file": str(f1), "old": "X = 1", "new": "X = 10"},
        {"file": str(f2), "old": "Y = 2", "new": "Y = 20"},
    ], verify=False)
    assert r["ok"] and len(r["files"]) == 2
    assert f1.read_text().strip() == "X = 10" and f2.read_text().strip() == "Y = 20"


def test_patch_set_all_or_nothing_on_bad_patch(workspace):
    # One patch is bad (old not found) → the WHOLE set aborts, the valid sibling is untouched.
    f1 = workspace / "a.py"; f1.write_text("X = 1\n")
    f2 = workspace / "b.py"; f2.write_text("Y = 2\n")
    r = _eng().apply_patch_set([
        {"file": str(f1), "old": "X = 1", "new": "X = 99"},   # valid
        {"file": str(f2), "old": "NOPE", "new": "Z"},          # stale → reject set
    ], verify=False)
    assert not r["ok"]
    assert f1.read_text().strip() == "X = 1"   # NOT written — atomic
    assert f2.read_text().strip() == "Y = 2"


def test_patch_set_rejects_syntax_break(workspace):
    f1 = workspace / "a.py"; f1.write_text("X = 1\n")
    r = _eng().apply_patch_set([{"file": str(f1), "old": "X = 1", "new": "X = (1"}], verify=False)
    assert not r["ok"] and f1.read_text().strip() == "X = 1"


def test_patch_set_rejects_outside_project():
    r = _eng().apply_patch_set([{"file": "/tmp/evil.py", "old": "a", "new": "b"}], verify=False)
    assert not r["ok"] and "outside project" in r["message"]
