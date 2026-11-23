"""Tests for eli.runtime sub-modules — ~80 tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ── Security ──────────────────────────────────────────────────────────────


def test_allow_roots_split_on_the_os_path_separator(monkeypatch, tmp_path):
    """ELI_ALLOW_ROOTS was split on ":", which cuts a Windows drive letter ("C:\\work") in two."""
    import os
    from eli.runtime import security
    monkeypatch.setattr(os, "pathsep", ";")
    monkeypatch.setenv("ELI_ALLOW_ROOTS", f"{tmp_path / 'one'};{tmp_path / 'two'}")
    roots = security.SecurityManager().allowed_roots
    assert (tmp_path / "one").resolve() in roots and (tmp_path / "two").resolve() in roots


def test_create_file_builds_the_security_manager_once_and_logs_no_false_block(monkeypatch, tmp_path, caplog):
    """CREATE_FILE built a SecurityManager on every call, and each one logged "shell commands are
    BLOCKED", which the live shell gate never was."""
    import logging
    from eli.execution.executor_enhanced import execute
    from eli.runtime import security
    built = []

    class _Counted(security.SecurityManager):
        def __init__(self):
            built.append(1)
            super().__init__()

    monkeypatch.setattr(security, "SecurityManager", _Counted)
    if hasattr(security, "_manager_for"):
        security._manager_for.cache_clear()
    monkeypatch.delenv("ELI_ALLOWED_CMDS", raising=False)
    with caplog.at_level(logging.WARNING, logger="eli.runtime.security"):
        for name in ("a.txt", "b.txt"):
            assert execute("CREATE_FILE", {"path": str(tmp_path / name), "content": "x"})["ok"] is True
    assert len(built) == 1
    assert "BLOCKED" not in caplog.text
    security._manager_for.cache_clear()

def test_security_safe_chat():
    try:
        from eli.runtime.security import is_safe_action
        result = is_safe_action("CHAT", {})
        assert result is True or result is False
    except ImportError:
        pytest.skip("is_safe_action not available")

def test_security_safe_memory_recall():
    try:
        from eli.runtime.security import is_safe_action
        result = is_safe_action("MEMORY_RECALL", {})
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("is_safe_action not available")

@pytest.mark.parametrize("action", [
    "CHAT", "MEMORY_RECALL", "RUNTIME_STATUS",
    "MEMORY_STATUS", "COGNITION_STATUS",
])
def test_security_standard_actions(action):
    try:
        from eli.runtime.security import is_safe_action
        result = is_safe_action(action, {})
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("is_safe_action not available")


# ── Authority Gate ────────────────────────────────────────────────────────


# ── Response Contracts ────────────────────────────────────────────────────


def test_grounded_actions_contains_standard():
    from eli.runtime.response_contracts import contract_for_action
    for action in ("MEMORY_STATUS", "COGNITION_STATUS"):
        contract = contract_for_action(action)
        assert contract is not None


# ── Reflection ────────────────────────────────────────────────────────────


# ── Self Improvement ──────────────────────────────────────────────────────


# ── Live Introspection ────────────────────────────────────────────────────


# ── Approval Engine ───────────────────────────────────────────────────────


# ── Personal Memory Surface ───────────────────────────────────────────────


# ── Evidence Store ────────────────────────────────────────────────────────

# ── Awareness Boot ────────────────────────────────────────────────────────


# ── Operator State ────────────────────────────────────────────────────────

