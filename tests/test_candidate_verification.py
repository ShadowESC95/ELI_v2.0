"""A candidate repair is tried on a copy of the tree and compared with the untouched tree; only a verified fix can be adopted."""
import sqlite3
import textwrap

import pytest

import eli.runtime.self_improvement as si


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "eli").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "eli" / "__init__.py").write_text("")
    (root / "eli" / "calc.py").write_text("def add(a, b):\n    return a - b\n\n\ndef neg(a):\n    return -a\n")
    (root / "tests" / "test_calc.py").write_text(textwrap.dedent("""
        from eli.calc import add, neg
        def test_add():
            assert add(2, 3) == 5
        def test_neg():
            assert neg(2) == -2
    """))
    (root / "pytest.ini").write_text("[pytest]\n")
    monkeypatch.setattr(si, "_patch_root", lambda: root)
    monkeypatch.setattr(si, "_smoke_import_module", lambda dotted, timeout=30.0: (True, "ok"))
    monkeypatch.setattr(si, "_dotted_module_for_path", lambda p: "eli.calc")
    return root


def _engine(tmp_path):
    e = si.SelfImprovementEngine.__new__(si.SelfImprovementEngine)
    db = tmp_path / "agent.sqlite3"
    e.memory = type("M", (), {"_get_connection": lambda s: sqlite3.connect(db)})()
    e.log_improvement = lambda *a, **k: None
    return e


def test_a_fix_is_verified_without_touching_the_real_tree(project, tmp_path):
    before = (project / "eli" / "calc.py").read_text()
    res = _engine(tmp_path).verify_in_workspace({"file": "eli/calc.py", "old": "a - b", "new": "a + b"})
    assert res["verdict"] == "fixed" and "tests/test_calc.py::test_add" in res["baseline"]["failed"] and res["candidate"]["failed"] == []
    assert (project / "eli" / "calc.py").read_text() == before
    assert not list((project / "artifacts" / "self_improve").iterdir())


def test_a_change_that_breaks_something_that_passed_is_a_regression(project, tmp_path):
    res = _engine(tmp_path).verify_in_workspace({"file": "eli/calc.py", "old": "return -a", "new": "return a"})
    assert res["verdict"] == "regression" and "tests/test_calc.py::test_neg" in res["candidate"]["failed"]


def test_no_matching_tests_is_inconclusive_not_a_pass(project, tmp_path):
    (project / "tests" / "test_calc.py").write_text("def test_other():\n    assert True\n")
    res = _engine(tmp_path).verify_in_workspace({"file": "eli/calc.py", "old": "a - b", "new": "a + b"}, tests=["tests/", "-k", "nothing_matches"])
    assert res["verdict"] == "inconclusive"


def test_a_candidate_cannot_change_the_tests_or_the_evaluator(project, tmp_path):
    for target in ("tests/test_calc.py", "tools/eval/memory_bench.py", "eli/runtime/lessons.py"):
        (project / target).parent.mkdir(parents=True, exist_ok=True)
        (project / target).write_text("x = 1\n")
        res = _engine(tmp_path).verify_in_workspace({"file": target, "old": "x = 1", "new": "x = 2"})
        assert res["verdict"] == "rejected" and "protected" in res["reason"]


def test_a_text_that_is_not_in_the_file_or_does_not_parse_is_rejected(project, tmp_path):
    e = _engine(tmp_path)
    assert e.verify_in_workspace({"file": "eli/calc.py", "old": "no such text", "new": "x"})["verdict"] == "rejected"
    assert e.verify_in_workspace({"file": "eli/calc.py", "old": "a - b", "new": "a +"})["verdict"] == "rejected"


def test_the_archive_keeps_every_candidate_and_only_a_verified_fix_is_adopted(project, tmp_path):
    e = _engine(tmp_path)
    bad = e.propose_candidate({"file": "eli/calc.py", "old": "return -a", "new": "return a", "description": "bad idea"}, hypothesis="neg is wrong")
    good = e.propose_candidate({"file": "eli/calc.py", "old": "a - b", "new": "a + b", "description": "fix add"}, hypothesis="add subtracts")
    assert (bad["status"], good["status"]) == ("rejected", "verified")
    assert e.adopt_candidate(bad["candidate_id"])["applied"] is False
    assert "a - b" in (project / "eli" / "calc.py").read_text()
    res = e.adopt_candidate(good["candidate_id"])
    assert res["applied"] and "a + b" in (project / "eli" / "calc.py").read_text()
    archive = {c["id"]: c for c in e.candidate_archive()}
    assert archive[good["candidate_id"]]["status"] == "adopted" and archive[bad["candidate_id"]]["verdict"] == "regression"
    assert archive[good["candidate_id"]]["hypothesis"] == "add subtracts"


def test_a_failure_capsule_carries_what_is_needed_to_look_again():
    cap = si.failure_capsule("GPU_STATUS", {"question": "temp"}, {"ok": False, "error": "nvidia-smi not found"}, request_id="req-1")
    assert cap["action"] == "GPU_STATUS" and cap["args"] == {"question": "temp"} and "nvidia-smi" in cap["error"]
    assert cap["classification"] and cap["python"] and cap["request_id"] == "req-1"
    cmd = si.capsule_reproducer(cap)
    assert cmd and cmd[0] and "GPU_STATUS" in cmd[-1]
    assert si.capsule_reproducer({"action": "SHELL_EXEC", "args": {"cmd": "rm -rf /"}}) is None


def test_the_autonomous_path_applies_only_a_demonstrated_fix(project, tmp_path, monkeypatch):
    e = _engine(tmp_path)
    unproven = e.apply_autonomously({"file": "eli/calc.py", "old": "def neg(a):\n    return -a", "new": "def neg(a):\n    return -a  # tidy", "description": "cosmetic"})
    assert unproven["applied"] is False and unproven["verdict"] == "unchanged" and "tidy" not in (project / "eli" / "calc.py").read_text()
    proven = e.apply_autonomously({"file": "eli/calc.py", "old": "a - b", "new": "a + b", "description": "fix add"})
    assert proven["applied"] and "a + b" in (project / "eli" / "calc.py").read_text()


def test_the_unproven_switch_restores_the_old_behaviour(project, tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_SELFPATCH_UNPROVEN", "1")
    monkeypatch.setattr(si, "_run_targeted_tests", lambda path, timeout=120.0: (False, True, "no matching tests"))
    e = _engine(tmp_path)
    assert e.apply_autonomously({"file": "eli/calc.py", "old": "return -a", "new": "return -a  # x", "description": "d"})["applied"]
