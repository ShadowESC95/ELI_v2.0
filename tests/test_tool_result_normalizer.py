"""Tool-result normalizer — coerces any executor return (exception / dict / value)
into a uniform ToolResultRecord. Pure; the shape every downstream consumer relies on.
"""
from __future__ import annotations

from eli.runtime.tool_result_normalizer import normalize_tool_result


def test_exception_becomes_error_record():
    r = normalize_tool_result("OPEN_APP", {"app": "x"}, ValueError("boom"))
    assert r.ok is False and r.status == "error"
    assert "ValueError" in r.summary and r.result_type == "exception"


def test_dict_ok_true():
    r = normalize_tool_result("GET_TIME", {}, {"ok": True, "summary": "12:00"})
    assert r.ok is True and r.summary == "12:00"


def test_dict_with_error_is_not_ok():
    r = normalize_tool_result("X", {}, {"error": "nope"})
    assert r.ok is False


def test_dict_defaults_ok_true_when_unspecified():
    r = normalize_tool_result("X", {}, {"data": 1})
    assert r.ok is True


def test_none_args_tolerated():
    r = normalize_tool_result("X", None, {"ok": True})
    assert r.ok is True and isinstance(r.args, dict)
