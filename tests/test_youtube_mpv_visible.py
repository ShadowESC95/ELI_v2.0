"""YouTube via mpv — visible video window by default."""
from __future__ import annotations

from eli.integrations.media.youtube_playback import build_mpv_youtube_argv


def test_mpv_youtube_visible_by_default():
    argv, _ = build_mpv_youtube_argv("never gonna give you up", ipc_path="/tmp/test.sock")
    joined = " ".join(argv)
    assert "--no-video" not in argv
    assert "--force-window=immediate" in argv
    assert "bestvideo+bestaudio/best" in joined


def test_mpv_youtube_headless_when_requested():
    argv, _ = build_mpv_youtube_argv(
        "never gonna give you up",
        ipc_path="/tmp/test.sock",
        headless=True,
    )
    joined = " ".join(argv)
    assert "--no-video" in argv
    assert "--force-window=immediate" not in argv
    assert "bestaudio/best" in joined
