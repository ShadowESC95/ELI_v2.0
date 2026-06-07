"""GENERATE_PROJECT routed through the coding planner DAG (decompose→solve→verify)."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from eli.execution.executor_enhanced import execute


def _fake_cr():
    return MagicMock(code="def app():\n    return 42\n", solved=True, score=0.96,
                     plan={"approach": "subtask DAG", "steps": ["core", "cli"]}, search={})


def test_generate_project_uses_planner_dag():
    with patch("eli.coding.agent.CodeAgent.solve", return_value=_fake_cr()):
        r = execute("GENERATE_PROJECT", {"description": "a tiny todo cli", "_evidence": ""})
    assert r["ok"] and r["evidence_source"] == "planner_dag"
    assert (r.get("result") or {}).get("steps") == ["core", "cli"]
    assert "planner DAG" in r["content"] and r.get("doc_path")


def test_generate_project_falls_back_when_agent_empty(monkeypatch):
    # agent yields nothing → single-pass chat fallback (still returns a result)
    monkeypatch.setenv("ELI_PROJECT_DAG", "1")
    with patch("eli.coding.agent.CodeAgent.solve",
               return_value=MagicMock(code="", solved=False, score=0.0, plan={}, search={})):
        r = execute("GENERATE_PROJECT", {"description": "x", "_evidence": ""})
    assert isinstance(r, dict) and "action" in r


def test_generate_project_missing_description():
    r = execute("GENERATE_PROJECT", {"_evidence": ""})
    assert r["ok"] is False
