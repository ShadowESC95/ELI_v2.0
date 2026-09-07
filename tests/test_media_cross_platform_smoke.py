"""Cross-platform media smoke tests — run on Linux, macOS, and Windows CI."""
from __future__ import annotations

import sys

import pytest


def test_platform_capability_report_runs():
    from eli.integrations.media.capabilities import platform_capability_report
    report = platform_capability_report(verbose=True)
    assert "Platform:" in report


def test_open_url_does_not_crash(monkeypatch):
    from eli.utils import platform_compat as pc
    monkeypatch.setattr(pc, "open_url", lambda u: True)
    from eli.execution.effectors.system_helpers import open_browser
    r = open_browser("https://example.com")
    assert r["ok"] is True


def test_yt_player_clients_order():
    from eli.integrations.media.youtube_playback import yt_player_clients
    clients = yt_player_clients()
    assert clients[0] == "android"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only mpv pipe path")
def test_mpv_socket_path_windows():
    from eli.integrations.media.cross_platform import mpv_socket_path
    p = mpv_socket_path()
    assert "pipe" in p.lower() or "\\\\" in p


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS browser open smoke")
def test_macos_open_url_smoke(monkeypatch):
    import subprocess
    from eli.utils import platform_compat as pc
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a) or type("P", (), {"poll": lambda s: 0})())
    monkeypatch.setattr(pc, "MACOS", True)
    monkeypatch.setattr(pc, "LINUX", False)
    monkeypatch.setattr(pc, "WINDOWS", False)
    assert pc._macos_open_url("https://example.com") is True
    assert calls


@pytest.mark.skipif(sys.platform != "win32", reason="Windows browser open smoke")
def test_windows_open_url_smoke(monkeypatch):
    import subprocess
    from eli.utils import platform_compat as pc
    monkeypatch.setattr(pc.shutil, "which", lambda name: "chrome.exe" if name == "chrome" else None)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: type("P", (), {"poll": lambda s: 0})())
    monkeypatch.setattr(pc, "WINDOWS", True)
    monkeypatch.setattr(pc, "LINUX", False)
    monkeypatch.setattr(pc, "MACOS", False)
    assert pc._windows_open_url("https://example.com") is True


def test_volume_helpers_exist():
    from eli.utils.platform_compat import get_volume, set_volume, adjust_volume, set_muted
    assert callable(get_volume)
    assert callable(set_volume)
    assert callable(adjust_volume)
    assert callable(set_muted)
