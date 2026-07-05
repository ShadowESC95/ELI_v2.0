"""Bluetooth discovery deduplication by device name."""
from eli.runtime.device_server import _dedupe_bluetooth_entries


def test_dedupe_merges_same_name_different_mac():
    found = [
        {"kind": "bluetooth", "host": "B8:8B:A1:EF:CD:23", "name": "Reflex-Pro",
         "audio_capable": True, "paired": True, "connected": False},
        {"kind": "bluetooth", "host": "B8:8B:A1:09:8C:D9", "name": "Reflex-Pro",
         "audio_capable": False, "paired": False, "connected": False},
        {"kind": "airplay", "host": "192.168.1.10", "name": "Kitchen TV"},
    ]
    out = _dedupe_bluetooth_entries(found)
    bt = [r for r in out if r.get("kind") == "bluetooth"]
    assert len(bt) == 1
    assert bt[0]["host"] == "B8:8B:A1:EF:CD:23"
    assert any(r.get("kind") == "airplay" for r in out)
