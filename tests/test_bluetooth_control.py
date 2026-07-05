"""Bluetooth control — pair / connect / disconnect + audio routing (regression, 2026-07-04).

Discovery could *list* Bluetooth devices but not act on them. This adds a driver that pairs,
connects, disconnects, and routes system audio to a Bluetooth device via the OS stack
(bluetoothctl + pactl on Linux). It must build the right commands, find the BlueZ audio sink
by MAC address, and degrade cleanly when the tools/radio are absent — never raise.
"""
import shutil
import sys

import pytest

import eli.runtime.device_drivers as dd


@pytest.fixture
def linux_tools(monkeypatch):
    """Force the Linux branch with all tools 'present', and capture shell calls."""
    calls = []

    def _responder(args):
        if args[:3] == ["pactl", "list", "short"]:
            if "sinks" in args:
                return 0, "42\tbluez_output.AA_BB_CC_DD_EE_FF.1\tmod\ts16le\tRUNNING"
            return 0, "7\tsomestream"
        return 0, "Connection successful"

    def fake_sh(args, timeout=25.0):
        calls.append(list(args))
        return _responder(args)

    def fake_batch(addr, steps, timeout=45.0, agent="NoInputNoOutput"):
        calls.append(["bluetoothctl-batch", addr, *steps])
        return True, "Connection successful"

    monkeypatch.setattr(dd.BluetoothDriver, "_sh", staticmethod(fake_sh))
    monkeypatch.setattr(dd.BluetoothDriver, "_btctl_batch", staticmethod(fake_batch))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda t: "/usr/bin/" + t)
    return calls


DEV = {"host": "AA:BB:CC:DD:EE:FF", "driver": "bluetooth"}


def test_driver_registered():
    d = dd.get_driver("bluetooth")
    assert d is not None and d.name == "bluetooth"
    caps = d.capabilities({})
    assert "connect" in caps and "disconnect" in caps and "use_for_audio" in caps


def test_connect_and_disconnect(linux_tools):
    d = dd.get_driver("bluetooth")
    assert d.control(DEV, "connect")["ok"] is True
    assert ["bluetoothctl-batch", "AA:BB:CC:DD:EE:FF", "connect"] in linux_tools
    linux_tools.clear()
    assert d.control(DEV, "disconnect")["ok"] is True
    assert ["bluetoothctl", "disconnect", "AA:BB:CC:DD:EE:FF"] in linux_tools


def test_pair_runs_pair_trust_connect(linux_tools, monkeypatch):
    d = dd.get_driver("bluetooth")
    monkeypatch.setattr(dd.BluetoothDriver, "_bt_device_info",
                        classmethod(lambda cls, a: {"paired": "no", "name": "My Buds"}))
    monkeypatch.setattr(
        "eli.runtime.bt_platform.resolve_device",
        lambda addr, name="", timeout=20.0: {"address": addr, "found": True, "phase": "cached"},
    )
    monkeypatch.setattr(
        "eli.runtime.bt_platform.ensure_radio",
        lambda: (True, "hci0"),
    )
    monkeypatch.setattr("eli.runtime.bt_platform.try_recover_radio", lambda: None)

    def fake_session(addr, steps, **kw):
        linux_tools.append(["linux_pair_session", addr, *steps])
        return True, "Connection successful", "paired"

    monkeypatch.setattr("eli.runtime.bt_platform.linux_pair_session", fake_session)
    monkeypatch.setattr(dd.BluetoothDriver, "_bt_ensure_controller", classmethod(lambda cls: (True, "AA:BB:CC:DD:EE:00")))
    monkeypatch.setattr(dd.BluetoothDriver, "_is_paired", classmethod(lambda cls, a: False))
    monkeypatch.setattr(dd.BluetoothDriver, "_pair_steps_for", classmethod(lambda cls, a: ["pair", "trust", "connect"]))
    monkeypatch.setattr(dd.BluetoothDriver, "classify_bt_device",
                        classmethod(lambda cls, i, n="": {"bt_type": "headphones", "audio_capable": True}))
    d.control(DEV, "pair")
    assert ["linux_pair_session", "AA:BB:CC:DD:EE:FF", "pair", "trust", "connect"] in linux_tools


def test_classify_printer_and_adapter():
    d = dd.get_driver("bluetooth")
    pr = d.classify_bt_device({"name": "DeskJet 2800 series", "uuids": ["0000fdb4-..."]})
    assert pr["bt_type"] == "printer" and pr["audio_capable"] is False
    ad = d.classify_bt_device({"name": "BT Headphones Kit", "icon": "audio-headset", "uuids": ["Audio Sink"]})
    assert ad["bt_type"] == "headphones" and ad["audio_capable"] is True
    dongle = d.classify_bt_device({"name": "CSR Bluetooth Dongle", "icon": "computer", "uuids": []})
    assert dongle["bt_type"] == "adapter" and dongle["audio_capable"] is False


def test_use_for_audio_rejects_printer(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda t: "/usr/bin/" + t)
    monkeypatch.setattr(
        dd.BluetoothDriver, "_bt_device_info",
        classmethod(lambda cls, a: {"name": "DeskJet 2800 series", "uuids": ["0000fdb4"]}),
    )
    r = dd.get_driver("bluetooth").control(DEV, "use_for_audio")
    assert r["ok"] is False and "printer" in r["error"].lower()


def test_ensure_adapter_alias_skips_when_already_eli(monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.bt_platform.set_adapter_alias",
        lambda name: {"ok": True, "alias": name, "already_set": True},
    )
    r = dd.BluetoothDriver.ensure_adapter_alias()
    assert r["ok"] is True and r.get("already_set") is True


def test_ensure_adapter_alias_sets_eli(monkeypatch):
    captured = {}

    def fake_set(name):
        captured["name"] = name
        return {"ok": True, "alias": name, "output": "Changing Eli · Home succeeded"}

    monkeypatch.setattr("eli.runtime.bt_platform.set_adapter_alias", fake_set)
    monkeypatch.setattr(dd.BluetoothDriver, "resolve_adapter_alias", classmethod(lambda cls: "Eli · Home"))
    r = dd.BluetoothDriver.ensure_adapter_alias()
    assert r["ok"] is True and r["alias"] == "Eli · Home"
    assert captured["name"] == "Eli · Home"


def test_resolve_adapter_alias_default_home(monkeypatch):
    monkeypatch.setattr("eli.core.runtime_settings.load_settings", lambda: {})
    assert dd.BluetoothDriver.resolve_adapter_alias() == "Eli · Home"


def test_resolve_adapter_alias_custom_zone(monkeypatch):
    monkeypatch.setattr(
        "eli.core.runtime_settings.load_settings",
        lambda: {"hub_zone": "Living room"},
    )
    assert dd.BluetoothDriver.resolve_adapter_alias() == "Eli · Living room"


def test_resolve_adapter_alias_override(monkeypatch):
    monkeypatch.setattr(
        "eli.core.runtime_settings.load_settings",
        lambda: {"bluetooth_display_name": "Eli Hub", "hub_zone": "Garage"},
    )
    assert dd.BluetoothDriver.resolve_adapter_alias() == "Eli Hub"


def test_use_for_audio_routes_to_bluez_sink(linux_tools, monkeypatch):
    monkeypatch.setattr(
        dd.BluetoothDriver, "_bt_device_info",
        classmethod(lambda cls, a: {"name": "My Buds", "icon": "audio-headset", "uuids": ["Audio Sink"], "paired": "yes"}),
    )
    monkeypatch.setattr(dd.BluetoothDriver, "_is_paired", classmethod(lambda cls, a: True))
    monkeypatch.setattr("eli.runtime.local_connectivity.find_bt_a2dp_sink",
                        lambda addr, name="": "bluez_output.AA_BB_CC_DD_EE_FF.1")
    monkeypatch.setattr("eli.runtime.local_connectivity.activate_bt_a2dp", lambda addr: True)
    d = dd.get_driver("bluetooth")
    r = d.control(DEV, "use_for_audio")
    assert r["ok"] is True and r["sink"] == "bluez_output.AA_BB_CC_DD_EE_FF.1"
    assert ["pactl", "set-default-sink", "bluez_output.AA_BB_CC_DD_EE_FF.1"] in linux_tools


def test_use_for_audio_no_sink_is_clean_error(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda t: "/usr/bin/" + t)
    monkeypatch.setattr(dd.BluetoothDriver, "_sh", staticmethod(lambda a, timeout=25.0: (0, "no bluez here")))
    monkeypatch.setattr(dd.BluetoothDriver, "_btctl_batch", staticmethod(lambda addr, steps, timeout=45.0: (False, "Failed to connect")))
    r = dd.get_driver("bluetooth").control(DEV, "use_for_audio")
    assert r["ok"] is False and "error" in r


def test_degrades_when_bluetoothctl_absent(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda t: None)   # nothing installed
    r = dd.get_driver("bluetooth").control(DEV, "connect")
    assert r["ok"] is False and "bluetoothctl" in r["error"].lower()


def test_unsupported_command_and_missing_address():
    d = dd.get_driver("bluetooth")
    assert d.control(DEV, "moonwalk")["ok"] is False
    assert d.control({}, "connect")["ok"] is False
