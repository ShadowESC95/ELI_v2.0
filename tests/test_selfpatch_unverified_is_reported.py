"""A patch whose tests could not run stays reported as unverified, and can be made to revert."""
import pathlib
import shutil
import tempfile

import pytest

import eli.runtime.self_improvement as si


@pytest.fixture
def target(monkeypatch):
    from eli.execution import executor_enhanced as EX
    root = getattr(EX, "PROJECT_ROOT", pathlib.Path(".").resolve())
    d = pathlib.Path(tempfile.mkdtemp(prefix="selfpatch_unverified_", dir=str(root / "artifacts")))
    f = d / "target.py"
    f.write_text("def main():\n    return 1\n")
    monkeypatch.setattr(si, "_dotted_module_for_path", lambda p: "fake.module.for.test")
    monkeypatch.setattr(si, "_smoke_import_module", lambda dotted, timeout=30.0: (True, "ok"))
    yield f
    shutil.rmtree(d, ignore_errors=True)


def _patch(engine, f):
    return engine.apply_code_patch({"file": str(f), "old": "return 1", "new": "return 2", "description": "change"})


@pytest.mark.parametrize("detail", ["no matching tests", "targeted test run timed out — tolerated"])
def test_tests_that_did_not_run_are_reported_unverified(target, monkeypatch, detail):
    monkeypatch.setattr(si, "_run_targeted_tests", lambda path, timeout=120.0: (False, True, detail))
    engine = si.SelfImprovementEngine.__new__(si.SelfImprovementEngine)
    engine.memory = type("M", (), {"_get_connection": lambda s: __import__("sqlite3").connect(":memory:")})()
    engine.log_improvement = lambda *a, **k: None
    res = _patch(engine, target)
    assert res["ok"] and res["verification"].startswith("unverified") and "unverified" in res["message"]


def test_passing_tests_are_reported_as_such(target, monkeypatch):
    monkeypatch.setattr(si, "_run_targeted_tests", lambda path, timeout=120.0: (True, True, "targeted tests passed"))
    engine = si.SelfImprovementEngine.__new__(si.SelfImprovementEngine)
    engine.memory = type("M", (), {"_get_connection": lambda s: __import__("sqlite3").connect(":memory:")})()
    engine.log_improvement = lambda *a, **k: None
    assert _patch(engine, target)["verification"] == "targeted tests passed"


def test_requiring_tests_reverts_an_unverified_patch(target, monkeypatch):
    monkeypatch.setenv("ELI_SELFPATCH_REQUIRE_TESTS", "1")
    monkeypatch.setattr(si, "_run_targeted_tests", lambda path, timeout=120.0: (False, True, "no matching tests"))
    engine = si.SelfImprovementEngine.__new__(si.SelfImprovementEngine)
    engine.memory = None
    engine.log_improvement = lambda *a, **k: None
    res = _patch(engine, target)
    assert res["ok"] is False and "return 1" in target.read_text()
