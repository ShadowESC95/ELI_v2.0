"""Media CLI resolution — venv yt-dlp and PATH helpers."""
from __future__ import annotations

import sys

import pytest


def test_yt_dlp_module_fallback(monkeypatch):
    import eli.integrations.media.media_deps as md

    monkeypatch.setattr(md, "resolve_binary", lambda name: "")
    monkeypatch.setattr(md, "yt_dlp_module_available", lambda: True)
    assert md.yt_dlp_available()
    assert md.yt_dlp_argv() == [md.sys.executable, "-m", "yt_dlp"]


def test_resolve_binary_from_venv_dir(monkeypatch, tmp_path):
    import eli.integrations.media.media_deps as md

    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "mpv"
    fake.write_text("#!/bin/sh\necho mpv\n")
    fake.chmod(0o755)

    monkeypatch.setattr(md.shutil, "which", lambda name: None)
    monkeypatch.setattr(md.sys, "executable", str(bindir / "python"))
    assert md.resolve_binary("mpv") == str(fake)


def test_build_mpv_argv_uses_resolved_mpv_binary(monkeypatch):
    from eli.integrations.media.youtube_playback import build_mpv_youtube_argv

    monkeypatch.setattr(
        "eli.integrations.media.media_deps.resolve_binary",
        lambda name: "/opt/bin/mpv" if name == "mpv" else "",
    )
    argv, _ = build_mpv_youtube_argv("test track", ipc_path="/tmp/s.sock", headless=True)
    assert argv[0] == "/opt/bin/mpv"


def test_missing_youtube_tools_lists_both(monkeypatch):
    monkeypatch.setattr("eli.integrations.media.media_deps.mpv_available", lambda: False)
    monkeypatch.setattr("eli.integrations.media.media_deps.yt_dlp_available", lambda: False)
    from eli.integrations.media.media_deps import missing_youtube_tools

    assert set(missing_youtube_tools()) == {"mpv", "yt-dlp"}
