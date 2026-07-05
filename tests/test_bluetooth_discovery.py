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
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)

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
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)
    found, errors = [], []
    ds._ble_discover(2.0, found, errors)
    assert found == []
    assert errors and any("classic scan only" in e.lower() for e in errors)


def test_ble_discover_survives_scan_error(monkeypatch):
    async def _boom(timeout=0):
        raise RuntimeError("adapter powered off")

    fake_bleak = types.SimpleNamespace(BleakScanner=types.SimpleNamespace(discover=_boom))
    monkeypatch.setitem(sys.modules, "bleak", fake_bleak)
    monkeypatch.setattr(ds, "_classic_bt_discover", lambda *a, **k: None)
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


def test_classic_bt_discover_includes_known_headphones(monkeypatch):
    monkeypatch.setattr(ds.shutil, "which", lambda t: "/usr/bin/bluetoothctl" if t == "bluetoothctl" else None)

    def fake_run(args, **kw):
        cmd = args
        class R:
            stdout = ""
            stderr = ""
        if cmd[:2] == ["bluetoothctl", "devices"]:
            R.stdout = "Device 41:42:51:08:4E:49 HOCO W46\n"
            return R
        if len(cmd) >= 3 and cmd[:3] == ["bluetoothctl", "--timeout", "6"]:
            R.stdout = "[NEW] Device 41:42:51:08:4E:49 HOCO W46\n"
            return R
        return R

    monkeypatch.setattr(ds.subprocess, "run", fake_run)
    found, seen, errors = [], set(), []
    ds._classic_bt_discover(4.0, found, seen, errors)
    assert any(f["name"] == "HOCO W46" for f in found)
