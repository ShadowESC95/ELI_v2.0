"""Bluetooth MAC resolution — prefer classic/audio over BLE duplicate names."""
import pytest

from eli.runtime import bt_platform as bp


def test_best_address_prefers_audio_headset_icon(monkeypatch):
    monkeypatch.setattr(bp, "_linux_list_devices", lambda: [
        {"address": "B9:08:A1:09:8C:D9", "name": "Reflex-Pro"},
        {"address": "B9:08:A1:EF:CD:23", "name": "Reflex-Pro"},
    ])

    def fake_info(addr):
        if addr == "B9:08:A1:EF:CD:23":
            return {"name": "Reflex-Pro", "icon": "audio-headset", "uuids": [], "class": "0x00240404"}
        return {
            "name": "Reflex-Pro",
            "uuids": ["00001800-0000-1000-8000-00805f9b34fb"],
            "manufacturerdata.key": "0xb822",
        }

    monkeypatch.setattr(bp, "device_info", fake_info)
    assert bp._best_address_for_name("Reflex-Pro") == "B9:08:A1:EF:CD:23"
    assert bp._prefer_address("B9:08:A1:09:8C:D9", "Reflex-Pro") == "B9:08:A1:EF:CD:23"


def test_enrich_uses_audio_mac_for_duplicate_name(monkeypatch):
    from eli.runtime.device_server import _enrich_bt_discover_results

    monkeypatch.setattr(bp, "_linux_list_devices", lambda: [
        {"address": "B9:08:A1:09:8C:D9", "name": "Reflex-Pro"},
        {"address": "B9:08:A1:EF:CD:23", "name": "Reflex-Pro"},
    ])
    monkeypatch.setattr(bp, "ensure_radio", lambda: (True, ""))

    def fake_info(addr):
        if addr == "B9:08:A1:EF:CD:23":
            return {"name": "Reflex-Pro", "icon": "audio-headset", "uuids": [], "paired": "no"}
        return {"name": "Reflex-Pro", "uuids": [], "paired": "no"}

    monkeypatch.setattr(
        "eli.runtime.device_drivers.BluetoothDriver._bt_device_info",
        classmethod(lambda cls, a: fake_info(a)),
    )
    monkeypatch.setattr(bp, "device_info", fake_info)
    monkeypatch.setattr(bp, "_address_quality_score", lambda a: 100 if a.endswith("CD:23") else 0)
    monkeypatch.setattr(bp, "_best_address_for_name", lambda n: "B9:08:A1:EF:CD:23")

    rows = [
        {"kind": "bluetooth", "host": "B9:08:A1:09:8C:D9", "name": "Reflex-Pro"},
        {"kind": "bluetooth", "host": "B9:08:A1:EF:CD:23", "name": "Reflex-Pro"},
    ]
    _enrich_bt_discover_results(rows)
    bt = [r for r in rows if r.get("kind") == "bluetooth"]
    assert len(bt) == 1
    assert bt[0]["host"] == "B9:08:A1:EF:CD:23"
    assert bt[0].get("audio_capable") is True
