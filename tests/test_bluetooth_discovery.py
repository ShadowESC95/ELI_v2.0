"""Bluetooth (BLE) device discovery (regression, 2026-07-04).

ELI discovered WiFi/mDNS/UPnP devices but had NO Bluetooth discovery at all. This adds a
best-effort BLE scan to device discover(). It must: shape results like the network results
(BT address carried as `host` so the existing merge dedups them), degrade cleanly when
there's no bleak/radio, and be skippable via include_bluetooth=False.
"""
import builtins
import sys
import types

import eli.runtime.device_server as ds


class _FakeDev:
    def __init__(self, address, name, rssi=-60):
        self.address = address
        self.name = name
        self.rssi = rssi


def test_ble_discover_shapes_devices(monkeypatch):
    async def _fake_discover(timeout=0):
        return [_FakeDev("AA:BB:CC:DD:EE:FF", "My Buds"), _FakeDev("11:22:33:44:55:66", None)]

    fake_bleak = types.SimpleNamespace(BleakScanner=types.SimpleNamespace(discover=_fake_discover))
    monkeypatch.setitem(sys.modules, "bleak", fake_bleak)
    monkeypatch.setattr(
        "eli.runtime.bt_platform.ensure_radio",
        lambda: (True, "00:11:22:33:44:55"),
    )
    monkeypatch.setattr(
        "eli.runtime.device_drivers.BluetoothDriver.ensure_adapter_alias",
        classmethod(lambda cls, *a, **k: {"ok": True}),
    )
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_enrich_bt_discover_results", lambda *a, **k: None)

    found, errors = [], []
    ds._ble_discover(2.0, found, errors)

    assert len(found) == 2, found
    named = next(f for f in found if f["host"] == "AA:BB:CC:DD:EE:FF")
    assert named["kind"] == "bluetooth"
    assert named["transport"] == "bluetooth"
    assert named["name"] == "My Buds"
    assert named["control"] == "bluetooth"     # controllable: pair/connect/disconnect/audio
    # An unnamed device still gets a friendly fallback carrying its address.
    unnamed = next(f for f in found if f["host"] == "11:22:33:44:55:66")
    assert "11:22:33:44:55:66" in unnamed["name"]


def test_ble_discover_degrades_without_bleak(monkeypatch):
    real_import = builtins.__import__

    def _no_bleak(name, *a, **k):
        if name == "bleak":
            raise ImportError("no bleak")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_bleak)
    monkeypatch.setattr(
        "eli.runtime.bt_platform.ensure_radio",
        lambda: (True, "00:11:22:33:44:55"),
    )
    monkeypatch.setattr(
        "eli.runtime.device_drivers.BluetoothDriver.ensure_adapter_alias",
        classmethod(lambda cls, *a, **k: {"ok": True}),
    )
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_enrich_bt_discover_results", lambda *a, **k: None)
    found, errors = [], []
    ds._ble_discover(2.0, found, errors)
    assert found == []
    assert errors and any("classic scan only" in e.lower() for e in errors)


def test_ble_discover_survives_scan_error(monkeypatch):
    async def _boom(timeout=0):
        raise RuntimeError("adapter powered off")

    fake_bleak = types.SimpleNamespace(BleakScanner=types.SimpleNamespace(discover=_boom))
    monkeypatch.setitem(sys.modules, "bleak", fake_bleak)
    monkeypatch.setattr(
        "eli.runtime.bt_platform.ensure_radio",
        lambda: (True, "00:11:22:33:44:55"),
    )
    monkeypatch.setattr(
        "eli.runtime.device_drivers.BluetoothDriver.ensure_adapter_alias",
        classmethod(lambda cls, *a, **k: {"ok": True}),
    )
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_enrich_bt_discover_results", lambda *a, **k: None)
    found, errors = [], []
    ds._ble_discover(2.0, found, errors)          # must NOT raise
    assert found == []
    assert any("scan failed" in e.lower() for e in errors)


def test_discover_skips_bluetooth_when_disabled(monkeypatch):
    called = {"ble": False}
    monkeypatch.setattr(ds, "_ble_discover", lambda *a, **k: called.__setitem__("ble", True))
    monkeypatch.setattr(ds, "_mdns_discover", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_ssdp_discover", lambda *a, **k: [])
    ds.discover(timeout=1.0, fresh=True, include_bluetooth=False)
    assert called["ble"] is False


def test_ble_discover_skips_bleak_when_radio_down(monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.bt_platform.ensure_radio",
        lambda: (False, "replug your USB Bluetooth dongle"),
    )
    monkeypatch.setattr(
        "eli.runtime.device_drivers.BluetoothDriver.ensure_adapter_alias",
        classmethod(lambda cls, *a, **k: {"ok": True}),
    )

    async def _should_not_run(timeout=0):
        raise AssertionError("bleak should not run when radio is down")

    fake_bleak = types.SimpleNamespace(BleakScanner=types.SimpleNamespace(discover=_should_not_run))
    monkeypatch.setitem(sys.modules, "bleak", fake_bleak)
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)
    monkeypatch.setattr(ds, "_enrich_bt_discover_results", lambda *a, **k: None)

    found, errors = [], []
    ds._ble_discover(2.0, found, errors)
    assert found == []
    assert any("radio unavailable" in e.lower() for e in errors)
    assert not any("BLE scan failed" in e for e in errors)


def test_quick_bt_discover_uses_known_list(monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.bt_platform.list_known_devices",
        lambda: [{"host": "AA:BB:CC:DD:EE:FF", "name": "My Buds", "kind": "bluetooth"}],
    )
    monkeypatch.setattr(ds, "_enrich_bt_discover_results", lambda found: None)
    found, errors = [], []
    ds._ble_discover(1.0, found, errors, quick=True)
    assert len(found) == 1 and found[0]["name"] == "My Buds"


def test_classic_bt_discover_includes_known_headphones(monkeypatch):
    ingested = []

    def fake_classic(timeout, found, seen, errors, entry_fn):
        row = entry_fn("AA:BB:CC:DD:EE:01", "BT Headphones Kit")
        found.append(row)
        seen.add("AA:BB:CC:DD:EE:01")

    monkeypatch.setattr("eli.runtime.bt_platform.classic_discover", fake_classic)
    found, seen, errors = [], set(), []
    ds._classic_bt_discover(4.0, found, seen, errors)
    assert any(f["name"] == "BT Headphones Kit" for f in found)
