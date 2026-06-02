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


def test_smart_home_without_config_does_not_call_network(monkeypatch):
    monkeypatch.delenv("ELI_HA_URL", raising=False)
    monkeypatch.delenv("ELI_HA_TOKEN", raising=False)

    import urllib.request as urllib_request

    def blocked_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not be called when Home Assistant is not configured")

    monkeypatch.setattr(urllib_request, "urlopen", blocked_urlopen)

    ex = _executor()
    result = ex.execute("SMART_HOME", {"command": "turn on", "device": "desk lamp"})

    assert isinstance(result, dict)
    assert result.get("ok") is False
    assert result.get("error") == "not_configured"


def test_smart_home_configured_uses_mocked_network(monkeypatch):
    monkeypatch.setenv("ELI_HA_URL", "http://homeassistant.local:8123")
    monkeypatch.setenv("ELI_HA_TOKEN", "fake-token")

    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    import urllib.request as urllib_request

    def fake_urlopen(req, timeout=10):
        calls.append({"req": req, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)

    ex = _executor()
    result = ex.execute("SMART_HOME", {"command": "turn on", "device": "light.desk_lamp"})

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert calls
    assert calls[0]["timeout"] == 10


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
