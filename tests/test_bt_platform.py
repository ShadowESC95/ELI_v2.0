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


def test_linux_default_hci_id_uses_busctl_not_hardcoded(monkeypatch):
    monkeypatch.setattr(bp, "_linux_bluez_default_controller_mac", lambda: "AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(bp, "_linux_hci_for_controller_mac", lambda m: "hci2" if m == "AA:BB:CC:DD:EE:FF" else "")
    assert bp._linux_default_hci_id() == "hci2"


def test_linux_device_dbus_path_prefers_active_hci(monkeypatch):
    tree = "└─ /org/bluez/hci2/dev_AA_BB_CC_DD_EE_FF\n"
    monkeypatch.setattr(bp, "_sh", lambda args, timeout=10: (0, tree))
    monkeypatch.setattr(bp, "_linux_default_hci_id", lambda: "hci2")
    path = bp._linux_device_dbus_path("AA:BB:CC:DD:EE:FF")
    assert path == "/org/bluez/hci2/dev_AA_BB_CC_DD_EE_FF"


def test_linux_hci_down_skips_zero_mac_ghosts(monkeypatch):
    monkeypatch.setattr(bp, "_linux_kernel_adapters", lambda: [
        bp.BtAdapter(id="hci1", address="00:00:00:00:00:00", state="down", source="kernel"),
        bp.BtAdapter(id="hci2", address="AA:BB:CC:DD:EE:FF", state="down", source="kernel"),
    ])
    assert bp._linux_hci_down() == ["hci2"]


def test_ensure_radio_delegates_by_platform(monkeypatch):
    monkeypatch.setattr(bp, "platform_kind", lambda: "darwin")
    monkeypatch.setattr(bp, "_darwin_ensure_radio", lambda: (True, "default"))
    ok, msg = bp.ensure_radio()
    assert ok and msg == "default"
