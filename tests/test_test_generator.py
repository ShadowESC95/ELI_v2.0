"""Meta-tests for ELI-assisted test generation (eli/runtime/test_generator.py).

Deterministic — the model is a stub `ask`. Verifies the GATE (only passing
candidates accepted), target selection, and the gen→verify→write→manifest pipeline.
"""
from __future__ import annotations

import json

import eli.runtime.test_generator as TG


def test_verify_accepts_a_passing_test():
    code = "def test_ok():\n    assert 1 + 1 == 2\n"
    r = TG.verify_test(code)
    assert r["accepted"] is True and r.get("passed", 0) >= 1


def test_verify_rejects_a_failing_test():
    code = "def test_bad():\n    assert 1 == 2\n"
    r = TG.verify_test(code)
    assert r["accepted"] is False and r["reason"] in ("failed/errored", "no tests collected")


def test_verify_rejects_syntax_error():
    # long enough to pass the min-length guard so it reaches the syntax check
    r = TG.verify_test("def test_broken_syntax(:\n    assert True  # missing paren arg\n")
    assert r["accepted"] is False and "syntax" in r["reason"]


def test_verify_rejects_when_no_tests_collected():
    r = TG.verify_test("x = 1  # no test functions here at all, just a statement\n")
    assert r["accepted"] is False


def test_select_targets_returns_real_functions():
    targets = TG.select_targets(limit=3, modules=["eli.core.dag"])
    assert targets and all(t.module == "eli.core.dag" for t in targets)
    assert all(callable(t.func) and t.source for t in targets)


def test_generate_test_strips_fences():
    t = TG.select_targets(limit=1, modules=["eli.core.dag"])[0]
    ask = lambda *a, **k: "```python\ndef test_z():\n    assert True\n```"
    code = TG.generate_test(t, ask)
    assert code.startswith("def test_z") and "```" not in code


def test_run_testgen_pipeline_accepts_and_writes(tmp_path, monkeypatch):
    # redirect the generated area to a temp dir so the real suite isn't touched
    monkeypatch.setattr(TG, "GEN_DIR", tmp_path)
    monkeypatch.setattr(TG, "MANIFEST", tmp_path / "_manifest.json")
    # stub the model to return a valid, passing test
    ask = lambda *a, **k: "def test_generated_ok():\n    assert sum([1, 2, 3]) == 6\n"
    res = TG.run_testgen(limit=1, ask=ask, modules=["eli.core.dag"])
    assert res["ok"] and res["accepted"] >= 1
    assert (tmp_path / "_manifest.json").exists()
    data = json.loads((tmp_path / "_manifest.json").read_text())
    assert any(e.get("accepted") for e in data["entries"])
    # the accepted test file exists
    assert list(tmp_path.glob("test_gen_*.py"))


def test_run_testgen_rejects_bad_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(TG, "GEN_DIR", tmp_path)
    monkeypatch.setattr(TG, "MANIFEST", tmp_path / "_manifest.json")
    ask = lambda *a, **k: "def test_bad():\n    assert False\n"
    res = TG.run_testgen(limit=1, ask=ask, modules=["eli.core.dag"])
    assert res["ok"] and res["accepted"] == 0 and res["rejected"] >= 1
    assert not list(tmp_path.glob("test_gen_*.py"))  # nothing written


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ELI_TESTGEN", "0")
    assert TG.enabled() is False
