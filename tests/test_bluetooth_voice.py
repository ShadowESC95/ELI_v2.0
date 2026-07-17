"""Bluetooth voice control (regression, 2026-07-04).

Wires spoken phrases to the Bluetooth driver: "connect my headphones", "pair the speaker",
"disconnect my earbuds", "play through the kitchen speaker", "use my headphones for audio".
Must route those (and NOT "connect to wifi" / media), resolve a spoken name to a device, and
— critically — not let the SMART_HOME on/off mapping turn "disc-ON-nect" into "on".
"""
import eli.runtime.device_server as ds
from eli.execution.router_enhanced import route


def _r(q):
    d = route(q) or {}
    return d.get("action"), (d.get("args") or {})


# ── routing ──────────────────────────────────────────────────────────────────
def test_connect_pair_disconnect_route():
    for q, cmd, dev in [
        ("connect my headphones", "connect", "headphones"),
        ("pair the bluetooth speaker", "pair", None),
        ("disconnect my earbuds", "disconnect", "earbuds"),
    ]:
        a, args = _r(q)
        assert a == "SMART_HOME" and args.get("bt") is True, q
        assert args.get("command") == cmd, q
        if dev:
            assert args.get("device") == dev, q


def test_audio_routing_phrases_route():
    for q, dev in [
        ("play through the kitchen speaker", "kitchen speaker"),
        ("use my headphones for audio", "headphones"),
        ("switch audio to my soundbar", "soundbar"),
    ]:
        a, args = _r(q)
        assert a == "SMART_HOME" and args.get("bt") is True, q
        assert args.get("command") == "use_for_audio" and args.get("device") == dev, q


def test_non_bluetooth_phrases_do_not_route_to_bt():
    for q in ("connect to wifi", "connect to the internet", "disconnect the call"):
        a, args = _r(q)
        assert not (a == "SMART_HOME" and args.get("bt")), q


def test_media_playback_still_wins():
    a, _ = _r("play despacito on spotify")
    assert a == "PLAY_MEDIA"


# ── name resolution ──────────────────────────────────────────────────────────
def _fake_devices(monkeypatch, devices, driver_calls):
    monkeypatch.setattr(ds, "discover",
                        lambda timeout=3.0, include_bluetooth=True, **k: {"found": devices})

    class _Drv:
        def control(self, dev, cmd, value=None):
            driver_calls.append((dev.get("name"), cmd))
            return {"ok": True, "command": cmd}

    import eli.runtime.device_drivers as dd
    monkeypatch.setitem(dd._DRIVERS, "bluetooth", _Drv())


def test_resolver_generic_picks_strongest_signal(monkeypatch):
    calls = []
    _fake_devices(monkeypatch, [
        {"host": "A", "name": "Sony WH-1000XM4", "kind": "bluetooth", "rssi": -50},
        {"host": "B", "name": "Kitchen JBL", "kind": "bluetooth", "rssi": -75},
    ], calls)
    r = ds.bluetooth_control_by_name("headphones", "connect")
    assert r["ok"] and r["device_name"] == "Sony WH-1000XM4"
    assert calls[-1] == ("Sony WH-1000XM4", "connect")


def test_resolver_named_and_word_match(monkeypatch):
    calls = []
    _fake_devices(monkeypatch, [
        {"host": "A", "name": "Sony WH-1000XM4", "kind": "bluetooth", "rssi": -50},
        {"host": "B", "name": "Kitchen JBL", "kind": "bluetooth", "rssi": -75},
    ], calls)
    assert ds.bluetooth_control_by_name("sony", "connect")["device_name"] == "Sony WH-1000XM4"
    assert ds.bluetooth_control_by_name("kitchen speaker", "use_for_audio")["device_name"] == "Kitchen JBL"


def test_resolver_no_devices_is_clean(monkeypatch):
    monkeypatch.setattr(ds, "discover", lambda **k: {"found": []})
    r = ds.bluetooth_control_by_name("headphones", "connect")
    assert r["ok"] is False and "bluetooth" in r["error"].lower()


# ── executor: the "disconnect" must NOT become "on" ──────────────────────────
def test_executor_disconnect_is_not_on(monkeypatch):
    from eli.execution.executor_enhanced import execute
    seen = {}

    def fake(name, command, scan_timeout=3.0):
        seen["command"] = command
        return {"ok": True, "command": command, "device_name": "Earbuds"}

    monkeypatch.setattr(ds, "bluetooth_control_by_name", fake)
    r = execute("SMART_HOME", {"device": "earbuds", "command": "disconnect", "bt": True})
    assert seen["command"] == "disconnect"          # not "on" (the substring trap)
    assert r["ok"] and "Disconnected" in r["content"]


def test_executor_use_for_audio_message(monkeypatch):
    from eli.execution.executor_enhanced import execute

    # use_for_audio tries the PulseAudio sink route first and only falls back to
    # the Bluetooth driver. Without stubbing that first hop the test reaches the
    # host's real sinks and reports whatever speaker the developer has plugged in.
    import eli.runtime.local_connectivity as lc
    monkeypatch.setattr(lc, "route_audio_by_name",
                        lambda n: {"ok": False, "error": "no sink"})
    monkeypatch.setattr(ds, "bluetooth_control_by_name",
                        lambda n, c, scan_timeout=3.0: {"ok": True, "command": c, "device_name": "Kitchen JBL"})
    r = execute("SMART_HOME", {"device": "kitchen speaker", "command": "use_for_audio", "bt": True})
    assert r["ok"] and "playing through Kitchen JBL" in r["content"]


def test_use_for_audio_claims_playing_only_when_a_stream_moved(monkeypatch):
    """A live stream was moved -> honest to say audio is now playing through it."""
    from eli.execution.executor_enhanced import execute
    import eli.runtime.local_connectivity as lc
    monkeypatch.setattr(lc, "route_audio_by_name",
                        lambda n: {"ok": True, "display_name": "Kitchen JBL",
                                   "alias": "Kitchen JBL", "streams_moved": 1})
    r = execute("SMART_HOME", {"device": "kitchen speaker", "command": "use_for_audio", "bt": True})
    assert r["ok"] and "playing through Kitchen JBL" in r["content"]


def test_use_for_audio_says_set_as_output_when_nothing_was_playing(monkeypatch):
    """Nothing was playing -> must NOT claim audio is 'now playing' (the server bug)."""
    from eli.execution.executor_enhanced import execute
    import eli.runtime.local_connectivity as lc
    monkeypatch.setattr(lc, "route_audio_by_name",
                        lambda n: {"ok": True, "display_name": "Kitchen JBL",
                                   "alias": "Kitchen JBL", "streams_moved": 0})
    # Also stub the BT fallback so a failed early hop can't reach real hardware.
    monkeypatch.setattr(ds, "bluetooth_control_by_name",
                        lambda n, c, scan_timeout=3.0: {"ok": False, "error": "x"})
    r = execute("SMART_HOME", {"device": "kitchen speaker", "command": "use_for_audio", "bt": True})
    assert r["ok"]
    assert "now playing" not in r["content"].lower()
    assert "set as the output" in r["content"]
