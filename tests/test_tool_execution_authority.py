"""tool_execution_authority.canonicalize_execution_call — normalise any call form
(dict / bare string / packet) into (packet, action, args). The single entry the
executor funnels through.
"""
from __future__ import annotations


from eli.execution import tool_execution_authority as tea


def test_canonicalize_dict_call():
    _, action, args = tea.canonicalize_execution_call({"action": "OPEN_APP", "args": {"app": "firefox"}})
    assert action == "OPEN_APP" and args.get("app") == "firefox"


def test_canonicalize_bare_string():
    _, action, args = tea.canonicalize_execution_call("GET_TIME", {"tz": "utc"})
    assert action == "GET_TIME" and isinstance(args, dict)


def test_canonicalize_tool_key_alias():
    # FIXED: the 'if payload:' branch now honours the tool/name aliases too.
    _, action, _ = tea.canonicalize_execution_call({"tool": "VOLUME", "args": {}})
    assert action == "VOLUME"


def test_canonicalize_name_key_alias():
    _, action, _ = tea.canonicalize_execution_call({"name": "GET_TIME", "args": {}})
    assert action == "GET_TIME"


def test_canonicalize_kwargs_alias():
    _, _, args = tea.canonicalize_execution_call({"action": "OPEN_APP", "kwargs": {"app": "x"}})
    assert args.get("app") == "x"


def test_record_execution_result_no_crash():
    tea.record_execution_result("GET_TIME", {}, {"ok": True})   # side-effect only, must not raise
