"""Gaze-cursor click routing.

Regression: with gaze tracking DISABLED, "open it" mis-fired into a phantom GAZE_CLICK
(and a "gaze enabled" hallucination). Natural-language targeting ("open it", "click
that") must only mean a gaze click when gaze is ON; explicit click commands always do.
"""
import eli.perception.gaze_engine as ge
from eli.execution.router_enhanced import route


def _act(q):
    r = route(q) or {}
    return r.get("action")


def test_open_it_does_not_gaze_click_when_gaze_off(monkeypatch):
    monkeypatch.setattr(ge, "is_gaze_running", lambda: False)
    for q in ("open it", "open that", "open your summary.md", "click that"):
        assert _act(q) != "GAZE_CLICK", q


def test_natural_language_click_routes_gaze_when_gaze_on(monkeypatch):
    monkeypatch.setattr(ge, "is_gaze_running", lambda: True)
    assert _act("open it") == "GAZE_CLICK"
    assert _act("click that") == "GAZE_CLICK"


def test_explicit_click_commands_always_gaze_click(monkeypatch):
    # Unambiguous click commands route regardless of gaze state.
    for state in (True, False):
        monkeypatch.setattr(ge, "is_gaze_running", lambda: state)
        assert _act("double click") == "GAZE_CLICK"
        assert _act("right click") == "GAZE_CLICK"
        assert _act("left click") == "GAZE_CLICK"
