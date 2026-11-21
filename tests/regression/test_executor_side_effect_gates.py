import importlib
import os

import pytest


def _executor():
    return importlib.import_module("eli.execution.executor_enhanced")


def test_web_search_uses_mocked_fetch_not_real_network(monkeypatch):
    # WEB_SEARCH no longer opens a browser; it does a headless text fetch and
    # returns grounded snippets. Verify it (a) honours the offline gate by being
    # given network, and (b) uses the mocked fetch — never a real network call.
    ex = _executor()

    # Pass the offline-by-default gate.
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: True)

    captured = {}

    def fake_results(query, max_results=5):
        captured["query"] = query
        return [{"title": "Entropy field simulation",
                 "href": "https://example.org/entropy",
                 "body": "A grounded snippet."}]

    import eli.plugins.web.plugin as webplugin
    monkeypatch.setattr(webplugin, "_web_search_results", fake_results, raising=False)

    result = ex.execute("WEB_SEARCH", {"query": "entropy field simulation"})

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert result.get("web_grounded") is True
    assert captured["query"] == "entropy field simulation"


def test_speak_uses_mocked_tts_not_real_audio(monkeypatch):
    calls = []

    import eli.perception.tts_router as tts_router

    def fake_maybe_speak(text, enabled=True):
        calls.append({"text": text, "enabled": enabled})
        return None

    monkeypatch.setattr(tts_router, "maybe_speak", fake_maybe_speak)

    ex = _executor()
    result = ex.execute("SPEAK", {"text": "side effect gate test"})

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert calls == [{"text": "side effect gate test", "enabled": True}]


def test_smart_home_with_no_devices_is_honest(monkeypatch):
    # SMART_HOME now routes through ELI's OWN MQTT device server (no Home Assistant).
    # With no devices registered it must refuse honestly — and never touch the network.
    import urllib.request as urllib_request

    def blocked_urlopen(*args, **kwargs):
        raise AssertionError("urlopen must not be called — SMART_HOME uses MQTT, not HTTP/HA")

    monkeypatch.setattr(urllib_request, "urlopen", blocked_urlopen)

    import eli.runtime.device_server as ds

    class _EmptySrv:
        def list_devices(self): return []
        def rooms(self): return []
        def control(self, *a, **k): return {"ok": False}
        def control_room(self, *a, **k): return {"ok": False}

    monkeypatch.setattr(ds, "get_server", lambda: _EmptySrv())

    ex = _executor()
    result = ex.execute("SMART_HOME", {"command": "turn on", "device": "desk lamp"})

    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert result.get("error") == "no_devices"


def test_smart_home_controls_device_via_mqtt_server(monkeypatch):
    # A registered device is resolved by name and controlled via the device server.
    import eli.runtime.device_server as ds

    calls = []

    class _Srv:
        def list_devices(self):
            return [{"id": "lamp1", "name": "Desk Lamp", "type": "light",
                     "command_topic": "home/lamp/set"}]
        def rooms(self): return []
        def control(self, device_id, command, value=None):
            calls.append((device_id, command))
            return {"ok": True, "device": device_id, "command": command}
        def control_room(self, *a, **k): return {"ok": False}

    monkeypatch.setattr(ds, "get_server", lambda: _Srv())

    ex = _executor()
    result = ex.execute("SMART_HOME", {"command": "turn on", "device": "desk lamp"})

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert calls == [("lamp1", "on")]


def test_smart_home_controls_room(monkeypatch):
    # A spoken room name controls every device in that room.
    import eli.runtime.device_server as ds

    calls = []

    class _Srv:
        def list_devices(self):
            return [{"id": "lamp1", "name": "Lamp", "type": "light", "command_topic": "h/l/set"}]
        def rooms(self):
            return [{"room": "Kitchen", "devices": []}]
        def control(self, *a, **k): return {"ok": False}
        def control_room(self, room, command):
            calls.append((room, command))
            return {"ok": True, "room": room, "count": 2}

    monkeypatch.setattr(ds, "get_server", lambda: _Srv())

    ex = _executor()
    result = ex.execute("SMART_HOME", {"command": "turn off", "device": "kitchen"})

    assert result.get("ok") is True
    assert calls == [("Kitchen", "off")]


class _HomeSrv:
    """Two rooms, invented names: a study with a lamp and a fan, a porch light outside."""

    def __init__(self):
        self.calls = []

    def list_devices(self):
        return [{"id": "lamp-7", "name": "Reading Lamp", "type": "light", "room": "Study", "command_topic": "h/l"},
                {"id": "fan-2", "name": "Desk Fan", "type": "fan", "room": "Study", "command_topic": "h/f"},
                {"id": "porch-1", "name": "Front Porch Light", "type": "light", "room": "Outside",
                 "command_topic": "h/p"}]

    def rooms(self):
        return [{"room": "Outside", "devices": []}, {"room": "Study", "devices": []}]

    def list_scenes(self):
        return [{"name": "Movie Night", "actions": []}]

    def control(self, device_id, command, value=None):
        self.calls.append((device_id, command, value))
        return {"ok": True}

    def control_room(self, room, command):
        self.calls.append((room, command, None))
        return {"ok": True, "count": 2}

    def activate_scene(self, name):
        self.calls.append(("scene", name, None))
        return {"ok": True, "scene": name, "ran": 1}


@pytest.mark.parametrize("said,expected", [
    ("turn off the reading lamp", [("lamp-7", "off", None)]),
    # "front" holds "on": the old substring test switched the porch light ON when asked to turn it off
    ("switch off the front porch light", [("porch-1", "off", None)]),
    # the study's lights, not its fan
    ("turn the lights off in the study", [("lamp-7", "off", None)]),
    ("dim the reading lamp to 30%", [("lamp-7", "brightness", 30)]),
    ("smart home movie night", [("scene", "Movie Night", None)]),
])
def test_smart_home_reads_the_device_from_what_was_said(monkeypatch, said, expected):
    """The router sends the whole request as `command` and no `device`, and every request got
    "Which device or room?"."""
    import eli.runtime.device_server as ds
    from eli.execution.router_enhanced import route
    srv = _HomeSrv()
    monkeypatch.setattr(ds, "get_server", lambda: srv)
    routed = route(said)
    assert routed["action"] == "SMART_HOME"
    result = _executor().execute("SMART_HOME", routed["args"])
    assert result.get("ok") is True, result
    assert srv.calls == expected


def test_pomodoro_start_stop_uses_temp_config_dir(monkeypatch, tmp_path):
    import eli.core.paths as paths

    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)

    ex = _executor()

    start = ex.execute("POMODORO_START", {"minutes": 1})
    assert isinstance(start, dict)
    assert start.get("ok") is True

    pom_file = tmp_path / "pomodoro.json"
    assert pom_file.exists()

    stop = ex.execute("POMODORO_STOP", {})
    assert isinstance(stop, dict)
    assert stop.get("ok") is True


def test_the_end_of_a_pomodoro_is_announced_and_a_stopped_one_is_not(monkeypatch, tmp_path):
    """POMODORO_* kept a start time and nothing else. The pomodoro plugin's timer, which announced
    the end, never ran: the executor answers its actions first."""
    import json
    import eli.core.paths as paths
    from eli.runtime import agenda
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)
    delivered = []
    agenda.set_delivery(lambda item, missed: delivered.append(item["id"]))
    try:
        ex = _executor()
        assert ex.execute("POMODORO_START", {"minutes": 1})["ok"] is True
        first = json.loads((tmp_path / "pomodoro.json").read_text(encoding="utf-8"))
        agenda.fire_due(now_ts=first["start"] + 61)
        assert first.get("reminder_id") in delivered, "the end of the session was not announced"

        ex.execute("POMODORO_START", {"minutes": 1})
        second = json.loads((tmp_path / "pomodoro.json").read_text(encoding="utf-8"))
        ex.execute("POMODORO_STOP", {})
        agenda.fire_due(now_ts=second["start"] + 61)
        assert second["reminder_id"] not in delivered, "a stopped session was announced"
    finally:
        agenda.set_delivery(None)


@pytest.mark.parametrize("alias", ["LAUNCH_APP", "OPEN_APPLICATION"])
def test_an_open_app_alias_gets_the_install_offer_when_the_app_is_missing(monkeypatch, alias):
    """When the portable layer could not open the app, the alias went on as itself, which nothing
    handles: "Unsupported executor action", and no offer to install it."""
    import eli.system.portable_app_control as pac
    from eli.runtime import grounded_remediation as gr
    monkeypatch.setattr(pac, "open_app", lambda *a, **k: {"ok": False, "error": "not found"})
    monkeypatch.setattr(gr, "diagnose_app", lambda name: {"ok": False, "subject": name})
    monkeypatch.setattr(gr, "offer_for_result", lambda diag: f"{diag['subject']} is not installed. Install it?")
    result = _executor().execute(alias, {"name": "zz-sketchpad"})
    assert "Unsupported" not in result["response"]
    # (a repeat across these cases adds the post-dispatch "attempt N" line to the same answer)
    assert result["response"].startswith("zz-sketchpad is not installed. Install it?")


@pytest.mark.parametrize("alias", ["CLOSE_APPLICATION", "EXIT_APP", "QUIT_APP"])
def test_a_close_app_alias_is_handled_as_close_app(monkeypatch, alias):
    import eli.system.portable_app_control as pac
    import eli.system.process_guard as pg
    ex = _executor()
    monkeypatch.setattr(pac, "close_app", lambda *a, **k: {"ok": False, "error": "no window"})
    monkeypatch.setattr(ex, "_run_ok", lambda *a, **k: False)
    monkeypatch.setattr(pg, "safe_pkill", lambda name, full_cmdline=False: {"ok": False, "reason": "not running"})
    result = ex.execute(alias, {"name": "zz-sketchpad"})
    # (a repeat across these cases adds the post-dispatch "attempt N" line to the same answer)
    assert result["response"].startswith("Could not close zz-sketchpad (not running).")


def test_show_diff_reads_the_real_history_and_says_when_there_is_none(monkeypatch, tmp_path):
    """SHOW_DIFF asked the chat model about "the recent changes" with nothing read from disk."""
    import subprocess
    ex = _executor()
    monkeypatch.setattr(ex, "chat", lambda *a, **k: {"ok": True, "content": "made up", "response": "made up"})
    repo = tmp_path / "proj"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "plan.txt").write_text("water the plants\n", encoding="utf-8")
    subprocess.run(git + ["add", "plan.txt"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "Add the watering plan"], check=True)
    (repo / "plan.txt").write_text("water the plants on Tuesday\n", encoding="utf-8")
    monkeypatch.setattr(ex, "_eli_self_project_root", lambda: repo)
    text = ex.execute("SHOW_DIFF", {})["response"]
    assert "+water the plants on Tuesday" in text and "Add the watering plan" in text

    plain = tmp_path / "installed"
    plain.mkdir()
    monkeypatch.setattr(ex, "_eli_self_project_root", lambda: plain)
    assert "no change history" in ex.execute("SHOW_DIFF", {})["response"]

    other = tmp_path / "other.txt"
    other.write_text("water the plants on Friday\n", encoding="utf-8")
    two = ex.execute("SHOW_DIFF", {"paths": f"{repo / 'plan.txt'} {other}"})["response"]
    assert "-water the plants on Tuesday" in two and "+water the plants on Friday" in two


def test_open_url_uses_mocked_helper(monkeypatch):
    ex = _executor()

    calls = []

    def fake_open_url(raw_url=None, *, query=None):
        calls.append({"raw_url": raw_url, "query": query})
        return {
            "ok": True,
            "action": "OPEN_URL",
            "url": raw_url,
            "content": f"mock opened {raw_url}",
            "response": f"mock opened {raw_url}",
        }

    monkeypatch.setattr(ex, "_eli_open_url_action", fake_open_url)

    result = ex.execute("OPEN_URL", {"url": "https://example.com"})

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert calls == [{"raw_url": "https://example.com", "query": None}]
