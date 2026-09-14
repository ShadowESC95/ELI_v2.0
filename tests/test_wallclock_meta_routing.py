"""DATE/TIME must not hijack meta-critique that merely embeds 'what day'."""
from __future__ import annotations

from eli.execution.router_enhanced import (
    _is_wallclock_meta_question,
    _is_wallclock_question,
    route,
)
from eli.kernel.engine import _is_brief_phatic_prompt
from eli.cognition.personal_context_gate import continuity_guard_block

LIVE_META = (
    "care to explain how you can tell me the date by calling that function, "
    "but you were not smart enough to think about making a plan, executuing "
    "that function, and incorporating it into your answer? so you know what "
    "day it is now?"
)

CHECK_IN = "hey buddy, you oaynow? feeling normal again?"


def _action(text: str) -> str:
    return str((route(text) or {}).get("action") or "").upper()


def test_live_meta_date_critique_routes_to_chat():
    assert _is_wallclock_meta_question(LIVE_META.lower())
    assert not _is_wallclock_question(LIVE_META.lower())
    assert _action(LIVE_META) == "CHAT"


def test_plain_date_asks_still_date():
    assert _action("what is the date/day") == "DATE"
    assert _action("what day is it") == "DATE"
    assert _action("what's the date") == "DATE"


def test_check_in_is_phatic_and_continuity_blocks_gpu_volunteer():
    assert _is_brief_phatic_prompt(CHECK_IN)
    guard = continuity_guard_block(CHECK_IN) or ""
    assert "GPU layer" in guard
