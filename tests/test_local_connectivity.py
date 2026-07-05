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


def test_is_handsfree_sink_detects_hsp():
    assert lc.is_handsfree_sink("bluez_output.XX.headset-head-unit", "HOCO W46")
    assert not lc.is_handsfree_sink("bluez_output.XX_1", "HOCO W46")
    assert lc.is_handsfree_sink("bluez_sink.aa_bb", "Handsfree")


def test_find_bt_a2dp_sink_prefers_music_profile(monkeypatch):
    def fake_sh(args, timeout=25.0):
        if args[:3] == ["pactl", "list", "short"]:
            if "sinks" in args:
                return 0, (
                    "1\tbluez_output.AA_BB_CC_DD_EE_FF.headset-head-unit\tmod\ts16le\n"
                    "2\tbluez_output.AA_BB_CC_DD_EE_FF.1\tmod\ts16le\n"
                )
            return 0, "0\tbluez_card.AA_BB_CC_DD_EE_FF\tmodule-bluez5-device.c\n"
        if args[:3] == ["pactl", "list", "sinks"]:
            return 0, (
                "Name: bluez_output.AA_BB_CC_DD_EE_FF.headset-head-unit\n"
                "Description: HOCO Handsfree\n"
                "Name: bluez_output.AA_BB_CC_DD_EE_FF.1\n"
                "Description: HOCO W46\n"
            )
        return 0, ""
    monkeypatch.setattr(lc, "_sh", fake_sh)
    sid = lc.find_bt_a2dp_sink("AA:BB:CC:DD:EE:FF", "HOCO")
    assert sid == "bluez_output.AA_BB_CC_DD_EE_FF.1"
