import importlib
import os


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
