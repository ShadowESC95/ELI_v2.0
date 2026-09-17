"""FIX_FILE must have the same safety net self_improvement.py's autonomous
patcher already has: a protected-path guardrail, post-write smoke-import
verification, and rollback on failure.

Autonomous self-patching is opt-in and off by default, so FIX_FILE (the
directly user-triggered "fix this file" action) is almost certainly the MORE
exercised of the two paths — it must not be the LESS protected one. This used
to have only the generic project-root-or-home path boundary: no guardrail
carve-out, no import verification after writing, no automatic rollback.
"""
from __future__ import annotations

import pathlib
import shutil
import tempfile

import pytest


@pytest.fixture
def workspace():
    from eli.execution import executor_enhanced as EX
    root = getattr(EX, "PROJECT_ROOT", pathlib.Path(".").resolve())
    d = pathlib.Path(tempfile.mkdtemp(prefix="fixfile_safety_", dir=str(root / "artifacts")))
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ── is_protected_patch_path() ────────────────────────────────────────────────
def test_security_py_is_protected():
    from eli.runtime.self_improvement import is_protected_patch_path
    assert is_protected_patch_path(pathlib.Path("eli/runtime/security.py")) is True


def test_grounding_gate_is_protected():
    from eli.runtime.self_improvement import is_protected_patch_path
    assert is_protected_patch_path(pathlib.Path("eli/runtime/deterministic_grounding_gate.py")) is True


def test_an_ordinary_module_is_not_protected():
    from eli.runtime.self_improvement import is_protected_patch_path
    assert is_protected_patch_path(pathlib.Path("eli/memory/memory.py")) is False


def test_a_file_outside_the_source_root_is_not_protected():
    """A user's own unrelated file is never blocked by this list -- it just
    doesn't match, since it can't resolve relative to the source root."""
    from eli.runtime.self_improvement import is_protected_patch_path
    assert is_protected_patch_path(pathlib.Path("/tmp/some_users_script.py")) is False


# ── FIX_FILE refuses to touch a protected guardrail file ────────────────────
def test_fix_file_refuses_a_protected_guardrail():
    from eli.execution import executor_enhanced as EX

    r = EX.execute("FIX_FILE", {"path": "eli/runtime/security.py", "_no_background": True})

    assert r.get("ok") is False
    assert "protected" in (r.get("error") or "").lower()
    # Nothing should have been read/patched -- refused before any model work.
    real = pathlib.Path("eli/runtime/security.py").read_text(encoding="utf-8")
    assert "def " in real  # sanity: the real file is untouched and still real python


# ── post-write verification + rollback ───────────────────────────────────────
def test_fix_file_rolls_back_a_fix_that_breaks_import(workspace, monkeypatch):
    import eli.coding.agent as ca
    from eli.execution import executor_enhanced as EX
    import eli.runtime.self_improvement as si

    original = "def main():\n    print('original, importable')\n"
    # Syntactically VALID (passes the earlier ast.parse gate) but semantically
    # broken, so it reaches the new import-verify step.
    broken_fix = "import this_module_does_not_exist_anywhere\n\ndef main():\n    pass\n"

    monkeypatch.setattr(ca, "solve", lambda task, **kw: {"code": broken_fix, "score": 0.9, "solved": True})
    # Force the dotted-module / pre-import-baseline path to engage even though
    # this file lives under artifacts/, not the real eli/ package tree.
    monkeypatch.setattr(si, "_dotted_module_for_path", lambda p: "fake.module.for.test")

    # First call = pre-write baseline (must report True so the differential
    # check engages); second call = post-write verification (must report the
    # real failure).
    calls = {"n": 0}

    def _fake_smoke_import(dotted, timeout=30.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, "ok"          # pre-write baseline: importable before our fix
        return False, "ModuleNotFoundError: this_module_does_not_exist_anywhere"

    monkeypatch.setattr(si, "_smoke_import_module", _fake_smoke_import)

    f = workspace / "target.py"
    f.write_text(original)
    r = EX.execute("FIX_FILE", {"path": str(f), "_no_background": True})

    assert r.get("ok") is False, "a fix that breaks import must not be reported as success"
    assert "revert" in (r.get("error") or "").lower() or "broke module import" in (r.get("error") or "").lower()
    assert f.read_text() == original, "the file must be rolled back to its original content"


def test_fix_file_keeps_a_fix_that_imports_cleanly(workspace, monkeypatch):
    import eli.coding.agent as ca
    from eli.execution import executor_enhanced as EX
    import eli.runtime.self_improvement as si

    original = "def main():\n    print('original')\n"
    good_fix = "def main():\n    print('fixed and importable')\n"

    monkeypatch.setattr(ca, "solve", lambda task, **kw: {"code": good_fix, "score": 0.9, "solved": True})
    monkeypatch.setattr(si, "_dotted_module_for_path", lambda p: "fake.module.for.test")
    monkeypatch.setattr(si, "_smoke_import_module", lambda dotted, timeout=30.0: (True, "ok"))
    monkeypatch.setattr(si, "_run_targeted_tests", lambda path, timeout=120.0: (False, True, "no matching tests"))

    f = workspace / "target.py"
    f.write_text(original)
    r = EX.execute("FIX_FILE", {"path": str(f), "_no_background": True})

    assert r.get("ok") is True
    assert f.read_text().strip() == good_fix.strip()
