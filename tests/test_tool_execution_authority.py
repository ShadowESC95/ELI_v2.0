"""tool_execution_authority.canonicalize_execution_call — normalise any call form
(dict / bare string / packet) into (packet, action, args). The single entry the
executor funnels through.
"""
from __future__ import annotations

import pytest

from eli.execution import tool_execution_authority as tea


def test_canonicalize_dict_call():
    _, action, args = tea.canonicalize_execution_call({"action": "OPEN_APP", "args": {"app": "firefox"}})
    assert action == "OPEN_APP" and args.get("app") == "firefox"


def test_canonicalize_bare_string():
    _, action, args = tea.canonicalize_execution_call("GET_TIME", {"tz": "utc"})
    assert action == "GET_TIME" and isinstance(args, dict)


@pytest.mark.xfail(
    strict=True,
    reason="LATENT BUG: canonicalize_execution_call lists 'tool'/'name' as aliases for "
           "'action' (line ~47), but _payload_from_packet_like returns the plain dict "
           "first, so the 'if payload:' branch honours only the 'action' key and the "
           "alias branch is dead code. A {'tool': X} call resolves to action=''.",
)
def test_canonicalize_tool_key_alias_SHOULD_work():
    _, action, _ = tea.canonicalize_execution_call({"tool": "VOLUME", "args": {}})
    assert action == "VOLUME"


def test_canonicalize_tool_key_current_behaviour():
    # Documents the *actual* (buggy) behaviour so a future fix is a visible change.
    _, action, _ = tea.canonicalize_execution_call({"tool": "VOLUME", "args": {}})
    assert action == ""


def test_record_execution_result_no_crash():
    tea.record_execution_result("GET_TIME", {}, {"ok": True})   # side-effect only, must not raise
