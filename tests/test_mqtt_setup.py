"""Tests for cross-platform MQTT onboarding helpers."""
from __future__ import annotations

import pytest

from eli.runtime.mqtt_setup import (
    DISCOVERY_PRESETS,
    broker_install_guide,
    detect_platform,
    probe_broker_connection,
    suggest_local_hosts,
)


def test_detect_platform_returns_known_label():
    assert detect_platform() in {"linux", "windows", "macos", "android", "other"}


def test_broker_install_guide_has_steps_for_each_platform():
    for plat in ("linux", "windows", "macos", "android", "other"):
        g = broker_install_guide(plat)
        assert g["platform"] == plat
        assert g["title"]
        assert len(g["steps"]) >= 3
        assert g["discovery_presets"] == DISCOVERY_PRESETS


def test_suggest_local_hosts_includes_loopback():
    hosts = suggest_local_hosts()
    assert "127.0.0.1" in hosts


def test_probe_broker_connection_requires_host():
    out = probe_broker_connection(host="")
    assert out["ok"] is False
    assert "host" in out["error"].lower()


def test_probe_broker_connection_unreachable_port():
    out = probe_broker_connection(host="127.0.0.1", port=31999, timeout=0.5)
    assert out["ok"] is False
    assert out.get("hint")
