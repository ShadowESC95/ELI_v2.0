"""Repair playbook routing and content."""
from __future__ import annotations

from eli.execution.router_enhanced import route
from eli.runtime.repair_playbook import (
    build_repair_playbook_report,
    recommend_repair_path,
)


def test_repair_playbook_route():
    out = route("show me the repair playbook")
    assert out["action"] == "SELF_REPAIR_PLAYBOOK", out


def test_self_help_route():
    out = route("self help")
    assert out["action"] == "SELF_REPAIR_PLAYBOOK", out


def test_recommend_self_fix():
    rec = recommend_repair_path("can you fix those errors in your code")
    assert rec["action"] == "SELF_PATCH"


def test_recommend_user_input_not_patch():
    rec = recommend_repair_path("mouse action levitate failed")
    assert rec["action"] == "NONE"
    assert rec["reason"] == "user_input_validation"


def test_playbook_report_contains_mechanisms():
    text = build_repair_playbook_report("how do I fix ELI", live=False)
    assert "self fix" in text.lower()
    assert "examine eli/gui/eli_pro_audio_gui_v2_0.py" in text
    assert "Tier 3" in text
    assert "USER_INPUT" in text


def test_playbook_executor():
    from eli.execution.executor_enhanced import execute

    out = execute("SELF_REPAIR_PLAYBOOK", {"question": "self help"})
    assert out.get("ok") is True
    body = str(out.get("content") or "")
    assert "repair playbook" in body.lower()
