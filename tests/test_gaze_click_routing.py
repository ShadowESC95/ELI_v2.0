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


def test_enable_gaze_clicking_turns_on_dwell():
    """'enable gaze clicking' / 'turn on dwell click' → GAZE_ENABLE with dwell=True
    (accessibility: hands-free AND voice-free look-and-hold clicking). 2026-07-04."""
    for q in ("enable gaze clicking", "turn on dwell click", "enable dwell clicking"):
        r = route(q) or {}
        assert r.get("action") == "GAZE_ENABLE", q
        assert (r.get("args") or {}).get("dwell") is True, q


def test_plain_enable_gaze_does_not_turn_on_dwell():
    """Plain 'enable gaze' starts tracking WITHOUT auto-click dwell mode."""
    for q in ("enable gaze", "enable the gaze tracker"):
        r = route(q) or {}
        assert r.get("action") == "GAZE_ENABLE", q
        assert not (r.get("args") or {}).get("dwell"), q


def test_dwell_click_can_be_switched_off_by_name():
    """It had no phrase: "disable dwell click" went to PLUGIN_DISABLE and "turn off
    dwell click" to chat. Switching dwell off alone leaves tracking running."""
    for q in ("turn off dwell click", "disable dwell clicking", "disable gaze clicking",
              "stop dwell clicking", "dwell click off"):
        r = route(q) or {}
        assert r.get("action") == "GAZE_DISABLE", q
        assert (r.get("args") or {}).get("dwell") is True, q
    r = route("disable gaze") or {}
    assert r.get("action") == "GAZE_DISABLE" and not (r.get("args") or {}).get("dwell")


def _dwell_setting():
    from eli.core.runtime_settings import load_settings
    return bool((load_settings() or {}).get("gaze_dwell_click", False))


def test_disable_gaze_also_switches_dwell_click_off(monkeypatch):
    """Dwell-click is a saved setting: stopping the engine without clearing it meant the
    next plain "enable gaze" clicked on its own again."""
    from eli.execution.executor_enhanced import execute
    stopped = []
    monkeypatch.setattr(ge, "stop_gaze_engine",
                        lambda: stopped.append(1) or {"ok": True, "message": "stopped"})
    ge.set_dwell_click(True)
    res = execute("GAZE_DISABLE", {})
    assert res["ok"] is True and stopped == [1]
    assert _dwell_setting() is False

    ge.set_dwell_click(True)
    res = execute("GAZE_DISABLE", {"dwell": True})
    assert res["ok"] is True and _dwell_setting() is False
    assert stopped == [1], "switching dwell-click off must leave tracking running"


def test_the_calibrator_is_told_to_write_where_the_engine_reads():
    """Its own default is ~/.config, which ELI never reads; the instruction promised
    ELI's config folder."""
    cmd = ge.calibration_command()
    assert cmd[cmd.index("--out") + 1] == str(ge.get_calibration_path())
    assert cmd[1].endswith("eli_gaze_calibrate_plus.py") and __import__("os").path.isfile(cmd[1])
    from eli.execution.executor_enhanced import execute
    msg = execute("GAZE_CALIBRATE", {})["response"]
    assert ge.calibration_command_line() in msg


def test_the_gaze_core_is_looked_for_only_in_the_kit():
    assert ge._GAZE_CORE_CANDIDATES == [ge._KIT_DIR / "eli_gaze_core"]
