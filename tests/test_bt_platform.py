"""Cross-platform Bluetooth platform helpers."""
import sys

import pytest

import eli.runtime.bt_platform as bp


def test_platform_kind_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert bp.platform_kind() == "linux"


def test_valid_mac_rejects_zero():
    assert not bp._valid_mac("00:00:00:00:00:00")
    assert bp._valid_mac("AA:BB:CC:DD:EE:FF")


def test_recovery_hint_linux_dynamic(monkeypatch):
    monkeypatch.setattr(bp, "platform_kind", lambda: "linux")
    monkeypatch.setattr(bp, "list_adapters", lambda: [
        bp.BtAdapter(id="hci0", state="down", source="kernel"),
        bp.BtAdapter(id="hci2", state="down", source="kernel"),
    ])
    hint = bp.recovery_hint()
    assert "hci0" in hint and "hci2" in hint
    assert "hciconfig" in hint


def test_recovery_hint_macos(monkeypatch):
    monkeypatch.setattr(bp, "platform_kind", lambda: "darwin")
    monkeypatch.setattr(bp.shutil, "which", lambda t: None)
    assert "System Settings" in bp.recovery_hint([])


def test_recovery_hint_windows(monkeypatch):
    monkeypatch.setattr(bp, "platform_kind", lambda: "windows")
    assert "Settings" in bp.recovery_hint([])


def test_linux_pick_controller_prefers_valid_mac():
    adapters = [bp.BtAdapter(id="hci0", address="AA:BB:CC:DD:EE:FF", bus="usb", bluez=True)]
    pick = bp._linux_pick_controller(["00:00:00:00:00:00", "AA:BB:CC:DD:EE:FF"], adapters)
    assert pick == "AA:BB:CC:DD:EE:FF"


def test_ensure_radio_delegates_by_platform(monkeypatch):
    monkeypatch.setattr(bp, "platform_kind", lambda: "darwin")
    monkeypatch.setattr(bp, "_darwin_ensure_radio", lambda: (True, "default"))
    ok, msg = bp.ensure_radio()
    assert ok and msg == "default"
