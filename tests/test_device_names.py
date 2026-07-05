"""Tests for persistent custom device names."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eli.runtime import device_names as dn


def test_sink_key_uses_mac():
    sid = "bluez_output.XX_B9_08_A1_EF_CD_23.1"
    assert dn.sink_key(sid) == "sink:B9:08:A1:EF:CD:23"
    assert dn.mac_from_sink_id(sid) == "B9:08:A1:EF:CD:23"


def test_bt_and_registry_keys():
    assert dn.bt_key("b9:08:a1:ef:cd:23") == "bt:B9:08:A1:EF:CD:23"
    assert dn.registry_key("living_room_light") == "dev:living_room_light"


def test_save_and_load_custom_name(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"device_custom_names": {}}), encoding="utf-8")

    def _load():
        return json.loads(settings_file.read_text(encoding="utf-8"))

    def _save(data):
        settings_file.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("eli.core.runtime_settings.load_settings", _load)
    monkeypatch.setattr("eli.core.runtime_settings.save_settings", _save)

    res = dn.save_custom_name("bt:B9:08:A1:EF:CD:23", "Reflex")
    assert res["ok"] is True
    names = dn.load_custom_names()
    assert names["bt:B9:08:A1:EF:CD:23"] == "Reflex"

    row = {"name": "Reflex-Pro", "host": "B9:08:A1:EF:CD:23"}
    dn.apply_name(row, "bt:B9:08:A1:EF:CD:23", "Reflex-Pro")
    assert row["display_name"] == "Reflex"
    assert "reflex" in row["voice_names"]

    match = dn.match_bluetooth_name("reflex", [{"name": "Reflex-Pro", "host": "B9:08:A1:EF:CD:23"}])
    assert match is not None

    dn.save_custom_name("bt:B9:08:A1:EF:CD:23", "")
    assert "bt:B9:08:A1:EF:CD:23" not in dn.load_custom_names()
