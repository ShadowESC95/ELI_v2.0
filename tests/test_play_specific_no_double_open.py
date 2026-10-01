"""Regression: 'play X by Y on spotify' must open ONLY Spotify — never YouTube.

User report: requesting a Spotify song opened the search in BOTH YouTube and
Spotify and never actually played. Root cause was play_specific()'s Spotify
branch only returning when the dbus search reported success; on any failure it
fell through into the YouTube sections and opened a second platform.

These tests assert that an explicit Spotify target stays on Spotify in both the
success and the unreachable-Spotify paths.
"""
from __future__ import annotations

import subprocess

from eli.execution import executor_enhanced as ex
from eli.integrations.media import cross_platform as cp


def _install_capture(monkeypatch, *, run_rc=0, run_stdout="Playing"):
    calls = {"popen": [], "run": []}

    class _P:
        pid = 1

    class _R:
        returncode = run_rc
        stdout = run_stdout
        stderr = ""

    def fake_popen(argv, *a, **k):
        calls["popen"].append(list(argv) if isinstance(argv, (list, tuple)) else [str(argv)])
        return _P()

    def fake_run(argv, *a, **k):
        calls["run"].append(list(argv) if isinstance(argv, (list, tuple)) else [str(argv)])
        return _R()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(ex.time, "sleep", lambda *_a, **_k: None)
    return calls


def _has_youtube(calls):
    blob = " ".join(" ".join(c) for c in calls["popen"] + calls["run"]).lower()
    return ("youtube" in blob) or ("ytsearch" in blob) or ("ytdl" in blob)


def test_spotify_target_plays_and_never_opens_youtube(monkeypatch):
    # Spotify reachable; status reports Playing AND live metadata matches the
    # requested track -> honest played=True. Status alone ("Playing") isn't
    # enough on its own — that's also true of a stale, already-playing track
    # that the request never touched; live metadata is what actually confirms
    # the right song loaded (see test_now_playing_matches_query regression).
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    calls = _install_capture(monkeypatch, run_rc=0, run_stdout="Playing")
    monkeypatch.setattr(cp, "spotify_live_meta",
                         lambda player="spotify": ("▶ Playing", "The Notorious B.I.G.", "Juicy"))

    res = ex.play_specific("juicy by notorious big", "spotify")

    assert res["action"] == "PLAY_MEDIA"
    assert res.get("played") is True
    assert not _has_youtube(calls), "Spotify request must not open YouTube"


def test_spotify_unreachable_reports_search_only_not_youtube(monkeypatch):
    # Every dbus/playerctl call fails and Spotify is not running -> must NOT
    # fall through to YouTube; must return an honest search_only/failure result.
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    calls = _install_capture(monkeypatch, run_rc=1, run_stdout="")

    res = ex.play_specific("juicy by notorious big", "spotify")

    assert res["action"] == "PLAY_MEDIA"
    assert res.get("played") is not True
    assert res.get("search_only") is True
    assert res.get("target") == "spotify"


def test_spotify_stale_track_resuming_is_not_reported_as_the_requested_song(monkeypatch):
    """Regression (live session, 2026-10-01): "play evil by eminem on spotify"
    opened a spotify:search: URI then hit MPRIS Play. Spotify had an unrelated
    track already queued from earlier and just resumed it — playerctl status
    correctly says "Playing", but it's the wrong track. The old code trusted
    status alone and told the user "Playing 'evil by eminem' on Spotify" when
    nothing of the sort had happened. Now it must report search_only instead."""
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    calls = _install_capture(monkeypatch, run_rc=0, run_stdout="Playing")
    monkeypatch.setattr(cp, "spotify_live_meta",
                         lambda player="spotify": ("▶ Playing", "Point Of No Return", "Immortal Technique"))

    res = ex.play_specific("evil by eminem", "spotify")

    assert res["action"] == "PLAY_MEDIA"
    assert res.get("played") is not True, "must not claim success for an unrelated stale track"
    assert res.get("search_only") is True
    assert not _has_youtube(calls), "must not fall through to YouTube either"


# ── YouTube continuous play: watch URL becomes a Mix/radio so it autoplays ────
def test_yt_mix_url_adds_radio_playlist():
    from eli.execution.executor_enhanced import _yt_mix_url
    assert _yt_mix_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == \
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"
    # extra params preserved-but-reseeded to the video id
    assert _yt_mix_url("https://www.youtube.com/watch?v=abc123XYZ_-&t=5").endswith("list=RDabc123XYZ_-")
    # non-watch URLs and None pass through unchanged
    assert _yt_mix_url(None) is None
    assert "list=RD" not in _yt_mix_url("https://www.youtube.com/results?search_query=x")


def test_yt_apply_browser_autoplay_adds_start_params():
    from eli.execution.executor_enhanced import _yt_apply_browser_autoplay, _yt_mix_url
    mix = _yt_mix_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    url = _yt_apply_browser_autoplay(mix)
    assert "autoplay=1" in url
    assert "start_radio=1" in url


def test_youtube_dot_com_uses_autoplay_mix_in_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(
        ex,
        "_yt_resolve_watch_url",
        lambda q: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    monkeypatch.setattr(ex, "_open_in_browser", lambda url: opened.append(url))
    monkeypatch.setattr(ex, "_yt_autoplay_enabled", lambda: True)

    res = ex.play_specific("real slim shady", "youtube website")

    assert res["action"] == "PLAY_MEDIA"
    assert opened, "browser was not opened"
    url = opened[0]
    assert "list=RD" in url
    assert "autoplay=1" in url
    assert "start_radio=1" in url


def test_spotify_playback_confirmed_rejects_unchanged_stale_track(monkeypatch):
    """Regression: the album/playlist search-tab fallbacks had the same bare
    `if _spotify_play():` false-positive the track fallback had — a stale,
    already-playing track reports identical "Playing" status whether or not
    anything new actually got selected. Used by both fallbacks now."""
    monkeypatch.setattr(ex, "_spotify_play", lambda: True)
    monkeypatch.setattr(ex, "_spotify_live_meta",
                         lambda *a, **k: ("▶ Playing", "Immortal Technique", "Harlem Streets"))
    before = ("Immortal Technique", "Harlem Streets")
    assert ex._spotify_playback_confirmed(before) is False


def test_spotify_playback_confirmed_accepts_a_real_change(monkeypatch):
    monkeypatch.setattr(ex, "_spotify_play", lambda: True)
    monkeypatch.setattr(ex, "_spotify_live_meta",
                         lambda *a, **k: ("▶ Playing", "Pink Floyd", "Breathe"))
    before = ("", "")
    assert ex._spotify_playback_confirmed(before) is True


def test_spotify_playback_confirmed_checks_hint_when_given(monkeypatch):
    """An album play must verify the live artist matches the requested album's
    artist, not just that *some* different track started."""
    monkeypatch.setattr(ex, "_spotify_play", lambda: True)
    monkeypatch.setattr(ex, "_spotify_live_meta",
                         lambda *a, **k: ("▶ Playing", "Some Other Artist", "Unrelated Track"))
    before = ("", "")
    assert ex._spotify_playback_confirmed(before, hint="pink floyd") is False


def test_spotify_playback_confirmed_false_when_play_itself_fails(monkeypatch):
    monkeypatch.setattr(ex, "_spotify_play", lambda: False)
    assert ex._spotify_playback_confirmed(("", "")) is False


def test_my_liked_songs_without_the_word_playlist_opens_liked_collection(monkeypatch):
    """Regression (live session): "play my liked songs in spotify" has no
    literal "playlist" in it, so playlist_name() extracted nothing and the
    liked-songs branch (gated behind a truthy extracted name) never ran —
    the phrase got typed verbatim into Spotify's track search, which then
    reported a false "Playing" success by resuming whatever track was
    already queued from before. Must open the real Liked Songs collection."""
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    _install_capture(monkeypatch, run_rc=0, run_stdout="Playing")

    opened = []
    monkeypatch.setattr(ex, "_spotify_open_liked_songs", lambda: opened.append(1) or True)
    live_meta = iter([("", ""), ("Some Artist", "Some Track")])
    monkeypatch.setattr(ex, "_spotify_live_meta", lambda player="spotify": ("", *next(live_meta)))

    res = ex.play_specific("my liked songs", "spotify")

    assert opened == [1], "must open the real Liked Songs collection, not search for it"
    assert res.get("kind") == "liked_songs"
    assert res.get("played") is True


def test_my_liked_playlist_opens_liked_collection_not_a_named_playlist_search(monkeypatch):
    """Regression: "play my liked playlist on spotify" extracted playlist
    name "liked" (the generic "X playlist" pattern), but is_liked_songs()
    required "liked song(s)" and rejected bare "liked" — so it searched
    Spotify for a playlist literally named "liked" instead."""
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    _install_capture(monkeypatch, run_rc=0, run_stdout="Playing")

    opened = []
    searched = []
    monkeypatch.setattr(ex, "_spotify_open_liked_songs", lambda: opened.append(1) or True)
    monkeypatch.setattr(ex, "_spotify_search", lambda q, prefer=None: searched.append(q) or True)
    live_meta = iter([("", ""), ("Some Artist", "Some Track")])
    monkeypatch.setattr(ex, "_spotify_live_meta", lambda player="spotify": ("", *next(live_meta)))

    res = ex.play_specific("my liked playlist", "spotify")

    assert opened == [1]
    assert searched == [], "must not fall through to a named-playlist search for 'liked'"
    assert res.get("kind") == "liked_songs"


def test_artist_album_name_phrasing_reaches_the_album_block_not_track_search(monkeypatch):
    """Regression (live session): "play diabolics album liar and a thief" and
    "play the arctic monkeys album AM" both fell through to the generic
    track-search fallback, typing the whole phrase verbatim and playing an
    unrelated top result — album_request() didn't recognise "ARTIST album
    ALBUMNAME" phrasing at all (fixed separately in spotify_intent). This
    confirms play_specific() actually routes through the album path now
    that the parser recognises it, rather than falling to track search."""
    monkeypatch.setattr(ex.shutil, "which",
                        lambda c: f"/usr/bin/{c}" if c in
                        {"xdg-open", "dbus-send", "playerctl"} else None)
    _install_capture(monkeypatch, run_rc=0, run_stdout="Playing")

    track_search_calls = []
    album_uri_calls = []
    monkeypatch.setattr(ex, "_spotify_resolve_track_uri", lambda q: None)
    monkeypatch.setattr(ex, "_spotify_resolve_album_uri",
                         lambda name, artist=None: album_uri_calls.append((name, artist)) or None)
    monkeypatch.setattr(ex, "_spotify_search",
                         lambda q, prefer=None: track_search_calls.append((q, prefer)) or False)
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_search_type_and_play",
        lambda q: False,
    )

    ex.play_specific("the arctic monkeys album am", "spotify")

    assert album_uri_calls == [("am", "arctic monkeys")], (
        "must resolve as an album request (name='am', artist='arctic monkeys')"
    )
    assert ("am arctic monkeys", "albums") in track_search_calls, (
        "the album search-tab fallback must search for the album name + "
        "artist, not get skipped"
    )
