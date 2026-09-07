"""Tests for cross-platform media capability probe and YouTube helpers."""
from __future__ import annotations

import os

import pytest


def test_detect_media_capabilities_structure():
    from eli.integrations.media.capabilities import detect_media_capabilities
    c = detect_media_capabilities()
    assert "platform" in c
    assert "youtube_mpv_ready" in c
    assert "browsers_found" in c
    assert isinstance(c["browsers_found"], list)


def test_media_capability_summary_non_empty():
    from eli.integrations.media.capabilities import media_capability_summary
    s = media_capability_summary()
    assert "platform=" in s


def test_detect_hardware_capabilities_uses_hardware_profile():
    from eli.integrations.media.capabilities import detect_hardware_capabilities
    hw = detect_hardware_capabilities()
    assert hw.get("ok") is True
    assert isinstance(hw.get("cpu_cores"), int)
    assert hw.get("cpu_cores", 0) >= 1
    assert isinstance(hw.get("ram_gb"), (int, float))
    if hw.get("has_gpu"):
        assert hw.get("primary_gpu")
        assert isinstance(hw.get("vram_mb"), int)


def test_yt_player_clients_default_order():
    from eli.integrations.media.youtube_playback import yt_player_clients
    os.environ.pop("ELI_YT_PLAYER_CLIENTS", None)
    clients = yt_player_clients()
    assert clients[0] == "android"
    assert "" in clients


def test_mpv_numeric_rejects_bool():
    from eli.integrations.media.youtube_playback import mpv_numeric
    assert mpv_numeric(True) is False
    assert mpv_numeric(3.14) is True
    assert mpv_numeric(0) is True


def test_yt_browser_play_url_fallback_search():
    from eli.integrations.media.youtube_playback import yt_search_open_url
    url = yt_search_open_url("test song")
    assert "youtube.com/results" in url
    assert "test+song" in url or "test%20song" in url


def test_executable_paths_includes_snap(monkeypatch):
    import shutil
    from eli.utils import platform_compat as pc
    snap = "/snap/bin/chromium"
    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc, "ANDROID", False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(os.path, "isfile", lambda p: p == snap)
    monkeypatch.setattr(os, "access", lambda p, mode: p == snap)
    paths = pc._executable_paths("chromium")
    assert snap in paths
