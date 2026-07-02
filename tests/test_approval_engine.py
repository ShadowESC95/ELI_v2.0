"""Approval engine — the emitter/action-class gate that decides what an autonomous
emitter may even propose. Pure policy logic; the guardrail behind ELI's autonomy.
"""
from __future__ import annotations

from eli.runtime import approval_engine as ae


def test_normalize_action_class():
    assert ae.normalize_action_class("shell-exec") == "shell-exec"
    assert ae.normalize_action_class("SHELL-EXEC") == "shell-exec"
    assert ae.normalize_action_class("nonsense") == "observe-only"   # safe default
    assert ae.normalize_action_class("") == "observe-only"


def test_normalize_emitter():
    assert ae.normalize_emitter("proactive") == "proactive"
    assert ae.normalize_emitter("who-dis") == "unknown"


def test_safe_class_allowed():
    assert ae.can_emitter_propose("autonomy_controller", "memory-write")[0] is True


def test_autonomy_cannot_run_shell():
    # The guardrail: the autonomy controller may only observe / write memory.
    ok, reason = ae.can_emitter_propose("autonomy_controller", "shell-exec")
    assert ok is False and "may not" in reason


def test_unknown_emitter_locked_to_observe():
    assert ae.can_emitter_propose("mystery", "shell-exec")[0] is False
    assert ae.can_emitter_propose("mystery", "observe-only")[0] is True


def test_remediation_may_run_shell():
    assert ae.can_emitter_propose("grounded_remediation", "shell-exec")[0] is True
