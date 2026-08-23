"""Behaviour locks for media playback: YouTube 403 recovery and Spotify context.

Observed live at 2.3.15:

  * "play bang along by the game on youtube" failed with mpv rc=3 and
    `[ffmpeg] https: HTTP error 403 Forbidden` on a googlevideo URL carrying
    `c=ANDROID_VR`. A 403 there does not mean the video is unavailable — it
    means yt-dlp returned a stream URL bound to the client that requested it.
    There was one attempt and no recovery.
  * Asking for a song on Spotify played it and then repeated rather than
    continuing, and there was no way to ask for a playlist at all — the query
    went to Spotify's *search results* context, which has no continuation.

The client order below is deliberate and was measured, not assumed: against
live YouTube on yt-dlp 2026.03.17 the default client resolved and fetched
(HTTP 206) while web_safari/tv/ios/mweb did not resolve at all. Pinning a
"preferred" client would have broken working playback for everyone.
"""
import pytest

from eli.execution import executor_enhanced as ex


# ── YouTube: recover from a client-bound refusal, change nothing else ──────
def test_default_client_is_tried_first():
    """The normal path must be byte-for-byte what it was: no pinned client."""
    assert ex._yt_player_clients()[0] == "", "a client is pinned ahead of the default"


def test_ladder_only_lists_clients_that_resolve():
    clients = ex._yt_player_clients()
    assert clients[0] == ""
    assert len(clients) >= 2, "no recovery clients at all"
    for dead in ("web_safari", "tv", "ios", "mweb", "web_embedded"):
        assert dead not in clients, f"{dead} does not resolve on current yt-dlp"


def test_client_order_is_overridable(monkeypatch):
    monkeypatch.setenv("ELI_YT_PLAYER_CLIENTS", "default,android,tv")
    assert ex._yt_player_clients() == ["", "android", "tv"]


@pytest.mark.parametrize("tail", [
    "[ffmpeg] https: HTTP error 403 Forbidden",
    "HTTP Error 403: Forbidden",
    "server returned 403",
])
def test_403_is_retried(tail):
    assert ex._yt_is_client_bound_failure(tail) is True


@pytest.mark.parametrize("tail", [
    "ERROR: Video unavailable",
    "Playlist ytsearch1: empty playlist",
    "ERROR: Private video. Sign in if you've been granted access",
])
def test_permanent_failures_are_not_retried(tail):
    """Retrying these just burns seconds before the fallback they were always
    going to get."""
    assert ex._yt_is_client_bound_failure(tail) is False


def test_403_failure_message_names_the_remedy():
    """A stale yt-dlp is the other common cause and no client can compensate
    for it, so a total refusal has to say so."""
    from pathlib import Path
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    assert "refused the stream for every player client" in src
    assert "upgrade yt-dlp" in src, "no actionable advice for a total refusal"


# ── Spotify: a playlist is a different context from a song ─────────────────
@pytest.mark.parametrize("query,expected", [
    ("my workout playlist", "workout"),
    ("the chill playlist", "chill"),
    ("discover weekly playlist", "discover weekly"),
    ("a rainy day play list", "rainy day"),
])
def test_playlist_requests_are_recognised(query, expected):
    assert ex._spotify_playlist_name(query) == expected


@pytest.mark.parametrize("query", [
    "the third world by immortal technique",
    "bang along by the game",
    "my playlist",          # names nothing
    "",
])
def test_song_requests_are_not_mistaken_for_playlists(query):
    assert ex._spotify_playlist_name(query) == ""


def test_repeat_one_is_only_cleared_when_actually_set(monkeypatch):
    """Repeat-one was NOT the cause on the reporting machine, so this must
    never overwrite a loop setting the user chose."""
    monkeypatch.setattr(ex, "_spotify_loop_status", lambda: "Playlist")
    assert ex._spotify_clear_track_repeat() is False
    monkeypatch.setattr(ex, "_spotify_loop_status", lambda: "None")
    assert ex._spotify_clear_track_repeat() is False


def test_playlist_path_uses_the_playlists_filter():
    from pathlib import Path
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    assert '_spotify_search(_pl_name, prefer="playlists")' in src


def test_playlist_without_a_platform_does_not_go_to_youtube():
    from pathlib import Path
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    assert "_spotify_playlist_name(query) and _spotify_running()" in src, \
        "a bare playlist request still falls through to YouTube search"
