"""Play commands must use native apps — browser only when browser=True (.com / website)."""
from __future__ import annotations

import pytest


def test_spotify_play_launches_native_app_not_browser(monkeypatch):
    browser_calls: list[str] = []
    app_uri_calls: list[str] = []
    launch_calls: list[str] = []

    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_running",
        lambda: False,
    )
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_launch_if_needed",
        lambda: launch_calls.append("launch") or True,
    )
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_search",
        lambda q, prefer=None: True,
    )
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_play",
        lambda: True,
    )
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_clear_track_repeat",
        lambda: True,
    )
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_live_meta",
        lambda player="spotify": ("", "Artist", "Track"),
    )
    monkeypatch.setattr(
        "eli.utils.platform_compat.open_url",
        lambda u: browser_calls.append(u) or True,
    )
    monkeypatch.setattr(
        "eli.utils.platform_compat.open_app_uri",
        lambda u: app_uri_calls.append(u) or True,
    )

    from eli.execution.executor_enhanced import play_specific

    result = play_specific("tupac all eyez", "spotify")
    assert result.get("target") == "spotify" or result.get("played")
    assert not browser_calls, f"open_url must not be used for Spotify play: {browser_calls}"
    assert launch_calls == ["launch"]


@pytest.mark.parametrize("spoken,canonical", [
    ("netflix", "netflix"),
    ("prime video", "primevideo"),
    ("disney plus", "disneyplus"),
])
def test_streaming_play_uses_native_app_not_browser(spoken, canonical, monkeypatch):
    browser_calls: list[str] = []
    app_uri_calls: list[str] = []
    native_calls: list[str] = []

    monkeypatch.setattr(
        "eli.execution.media_runtime.open_streaming_app",
        lambda c: native_calls.append(c) or True,
    )
    monkeypatch.setattr(
        "eli.utils.platform_compat.open_app_uri",
        lambda u: app_uri_calls.append(u) or True,
    )
    monkeypatch.setattr(
        "eli.utils.platform_compat.open_url",
        lambda u: browser_calls.append(u) or True,
    )

    from eli.execution.executor_enhanced import play_specific

    result = play_specific("Stranger Things", spoken)
    assert result.get("target") == canonical
    assert native_calls == [canonical]
    assert not browser_calls
    assert app_uri_calls
    assert "netflix.com" in app_uri_calls[0] or "primevideo.com" in app_uri_calls[0] or "disneyplus.com" in app_uri_calls[0]


def test_streaming_dot_com_uses_browser(monkeypatch):
    browser_calls: list[str] = []

    monkeypatch.setattr(
        "eli.utils.platform_compat.open_url",
        lambda u: browser_calls.append(u) or True,
    )

    from eli.execution.executor_enhanced import play_specific

    result = play_specific("Oppenheimer", "netflix.com", browser=True)
    assert result.get("target") == "netflix"
    assert browser_calls
    assert "netflix.com" in browser_calls[0]
