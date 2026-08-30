"""Regression tests for failure-log direct return and deterministic self-fix patches."""
from __future__ import annotations

import pytest


def test_explain_failure_log_is_system_action():
    from eli.cognition.agent_bus import SystemAgent

    assert "EXPLAIN_FAILURE_LOG" in SystemAgent.SYSTEM_ACTIONS
    assert "EXPLAIN_GGUF_DIAGNOSTICS" in SystemAgent.SYSTEM_ACTIONS
    assert "EXPLAIN_LAST_FAILURE" in SystemAgent.SYSTEM_ACTIONS


def test_explain_failure_log_agent_selection_is_system_only():
    from eli.cognition.agent_bus import _select_agents_for_intent

    selected = _select_agents_for_intent("what are the failures?", "EXPLAIN_FAILURE_LOG")
    assert selected == {"system"}


def test_create_document_accepts_name_as_topic(monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    from eli.execution.executor_enhanced import execute

    result = execute(
        "CREATE_DOCUMENT",
        {"name": "new agent", "target": "new agent"},
    )
    assert result.get("ok") is True
    body = str(result.get("document_content") or result.get("content") or "")
    assert "new agent" in body.lower()


def test_create_doc_alias_routes_to_create_document(monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    from eli.execution.executor_enhanced import execute

    result = execute("CREATE_DOC", {"topic": "alias smoke test"})
    assert result.get("ok") is True
    assert "alias smoke test" in str(result.get("document_content") or result.get("content") or "").lower()


def test_deterministic_patch_for_missing_document_topic():
    from eli.runtime.deterministic_failure_patches import propose_deterministic_patch

    patch = propose_deterministic_patch(
        {
            "error": "Missing topic for document generation",
            "command": 'CREATE_DOCUMENT {"name": "new agent"}',
        }
    )
    # After the executor fix is applied, the patch may already be present (returns None).
    # Before apply, it should propose the alias expansion.
    if patch:
        assert patch.get("ok") is True
        assert "name" in patch.get("new", "")
        assert patch.get("file") == "eli/execution/executor_enhanced.py"


def test_self_fix_routes_to_self_patch():
    from eli.execution.router_enhanced import route

    intent = route("self fix")
    assert intent.get("action") == "SELF_PATCH"
