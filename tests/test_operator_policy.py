"""Operator policy — the autonomy-level governance gate.

Controls how much autonomy ELI has (proposal_only / operator_supervised /
goal_driven / observe_only). set_policy_mode must reject unknown modes (fail-safe)
and persist valid ones; load_policy always returns a well-formed record. This is an
audit-relevant control surface. Pure/file-backed; isolated + restored here.
"""
from __future__ import annotations

import pytest

from eli.execution import operator_policy as op


@pytest.fixture(autouse=True)
def _restore_policy():
    p = op.policy_path()
    original = p.read_text(encoding="utf-8") if p.exists() else None
    yield
    if original is None:
        if p.exists():
            p.unlink()
    else:
        p.write_text(original, encoding="utf-8")


def test_valid_modes_are_defined():
    assert {"proposal_only", "operator_supervised", "goal_driven", "observe_only"} <= op.VALID_POLICY_MODES


def test_load_policy_is_well_formed():
    pol = op.load_policy()
    assert isinstance(pol, dict)
    assert pol.get("mode") in op.VALID_POLICY_MODES
    assert "path" in pol


def test_set_valid_mode_persists():
    rec = op.set_policy_mode("observe_only", actor="tester", reason="unit test")
    assert rec["ok"] is True and rec["mode"] == "observe_only"
    assert rec["actor"] == "tester" and rec["reason"] == "unit test"
    # Round-trips through the store.
    assert op.load_policy()["mode"] == "observe_only"


def test_set_invalid_mode_rejected_and_no_write():
    op.set_policy_mode("goal_driven")           # a known-good baseline
    bad = op.set_policy_mode("full_send_yolo")   # not a valid mode
    assert bad["ok"] is False and "invalid mode" in bad["error"]
    assert "valid" in bad
    # The rejected mode must NOT have overwritten the baseline.
    assert op.load_policy()["mode"] == "goal_driven"


def test_mode_switch_round_trip():
    for mode in ("proposal_only", "operator_supervised", "goal_driven", "observe_only"):
        op.set_policy_mode(mode)
        assert op.load_policy()["mode"] == mode
