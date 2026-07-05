"""Local connectivity module — structure and graceful degradation (no cloud)."""
from __future__ import annotations

from eli.runtime import local_connectivity as lc


def test_connectivity_status_shape():
    st = lc.connectivity_status()
    assert st["ok"] is True
    assert st["local_only"] is True
    assert "wifi" in st
    assert "audio" in st
    assert "bluetooth" in st


def test_wifi_scan_returns_dict():
    r = lc.wifi_scan()
    assert "ok" in r
    assert "networks" in r
    assert isinstance(r["networks"], list)


def test_list_audio_outputs_returns_dict():
    r = lc.list_audio_outputs()
    assert "ok" in r
    assert "sinks" in r
    assert isinstance(r["sinks"], list)


def test_wifi_connect_rejects_empty_ssid():
    r = lc.wifi_connect("")
    assert r["ok"] is False
    assert "ssid" in r["error"].lower()


def test_set_default_audio_rejects_empty():
    r = lc.set_default_audio("")
    assert r["ok"] is False


def test_aux_status_embedder_path():
    from eli.core.model_download import aux_asset_path, aux_status
    p = aux_asset_path("embedder")
    assert p.name == "nomic-embed-text-v1.5.Q4_K_M.gguf"
    assert "embeddings" in str(p)
    st = aux_status("embedder")
    assert st["key"] == "embedder"
    assert "size_gib_estimate" in st


def test_audio_alias_resolve_by_name(monkeypatch):
    monkeypatch.setattr(
        lc,
        "list_audio_outputs",
        lambda: {
            "ok": True,
            "sinks": [
                {"id": "sink-a", "name": "Built-in Audio", "alias": "Kitchen speaker",
                 "display_name": "Kitchen speaker", "device_number": 1,
                 "voice_names": ["kitchen speaker", "device 1"]},
                {"id": "sink-b", "name": "HDMI", "alias": "", "display_name": "HDMI",
                 "device_number": 2, "voice_names": ["hdmi", "device 2"]},
            ],
        },
    )
    hit = lc.resolve_audio_sink("kitchen speaker")
    assert hit and hit["id"] == "sink-a"
    hit2 = lc.resolve_audio_sink("device 2")
    assert hit2 and hit2["id"] == "sink-b"


def test_route_audio_by_name(monkeypatch):
    monkeypatch.setattr(
        lc,
        "resolve_audio_sink",
        lambda q: {"id": "sink-a", "alias": "Sitting room", "display_name": "Sitting room"},
    )
    monkeypatch.setattr(lc, "set_default_audio", lambda s: {"ok": True, "sink": s})
    r = lc.route_audio_by_name("sitting room")
    assert r["ok"] is True and r["display_name"] == "Sitting room"
