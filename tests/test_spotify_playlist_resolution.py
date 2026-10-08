"""Spotify playlist URI resolution and playback polling helpers."""
from eli.execution import executor_enhanced as ex


def test_resolve_playlist_uri_from_search_html(monkeypatch):
    html = (
        '<script>{"uri":"spotify:playlist:37i9dQZF1DX0XUsuxWHRQd",'
        '"name":"Workout"}</script>'
    )

    class _Resp:
        def read(self):
            return html.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    from eli.integrations.media.cross_platform import spotify_resolve_playlist_uri
    assert spotify_resolve_playlist_uri("workout") == "spotify:playlist:37i9dQZF1DX0XUsuxWHRQd"


def test_resolve_album_uri_from_search_html(monkeypatch):
    html = '{"uri":"spotify:album:4cQZRveqW4purQgPiE8xNK"}'

    class _Resp:
        def read(self):
            return html.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    from eli.integrations.media.cross_platform import spotify_resolve_album_uri
    assert spotify_resolve_album_uri("marshall mathers lp", "eminem") == "spotify:album:4cQZRveqW4purQgPiE8xNK"


def test_resolve_track_uri_from_search_html(monkeypatch):
    html = '{"uri":"spotify:track:7xpjmdv9k5zgdH3EbLn4N1"}'

    class _Resp:
        def read(self):
            return html.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    from eli.integrations.media.cross_platform import spotify_resolve_track_uri
    assert spotify_resolve_track_uri("soldiers logic diabolic") == "spotify:track:7xpjmdv9k5zgdH3EbLn4N1"


def test_play_specific_asks_spotify_for_its_top_result_first(monkeypatch):
    """Spotify plays its top search result over MPRIS before anything types into its window: that
    path needs no window focus, so it is the one that works on Wayland."""
    typed = []
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_play_top_search_result",
                        lambda q, timeout=10.0, launch=True: True)
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_search_type_and_play",
                        lambda q, launch=True: typed.append(q) or True)
    monkeypatch.setattr(ex, "_spotify_live_meta", lambda *a, **k: ("▶ Playing", "Diabolic", "Soldiers Logic"))

    result = ex.play_specific("soldiers logic by diabolic", target="spotify")

    assert result["ok"] is True and result["played"] is True and not typed


def test_play_specific_types_into_spotify_when_the_top_result_is_not_it(monkeypatch):
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_play_top_search_result",
                        lambda q, timeout=10.0, launch=True: False)
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_search_type_and_play",
                        lambda q, launch=True: True)

    result = ex.play_specific("soldiers logic by diabolic", target="spotify")

    assert result["ok"] is True and result["played"] is True


def test_the_track_path_does_not_scrape_open_spotify(monkeypatch):
    """open.spotify.com's search page is a JS shell; scraping it for a track never resolved
    anything and only sent the query out and waited on it."""
    def no_scrape(q):
        raise AssertionError("scraped")
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_play_top_search_result",
                        lambda q, timeout=10.0, launch=True: False)
    monkeypatch.setattr("eli.integrations.media.cross_platform.spotify_search_type_and_play",
                        lambda q, launch=True: False)
    monkeypatch.setattr(ex, "_spotify_resolve_track_uri", no_scrape)
    monkeypatch.setattr(ex, "_spotify_running", lambda: True)
    monkeypatch.setattr(ex, "_spotify_search", lambda q, prefer=None: False)
    monkeypatch.setattr(ex, "_spotify_open_uri", lambda u: False)
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    ex.play_specific("soldiers logic by diabolic", target="spotify")


def test_play_specific_falls_back_to_search_when_no_track_uri_resolves(monkeypatch):
    """When both keystroke automation and URI resolution fail, the oldest
    search-then-play fallback must still run unchanged."""
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_search_type_and_play",
        lambda q: False,
    )
    monkeypatch.setattr(ex, "_spotify_resolve_track_uri", lambda q: None)
    monkeypatch.setattr(ex, "_spotify_running", lambda: True)
    monkeypatch.setattr(ex, "_spotify_search", lambda q, prefer=None: True)
    monkeypatch.setattr(ex, "_spotify_clear_track_repeat", lambda: True)
    monkeypatch.setattr(ex, "_spotify_play", lambda: False)
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    result = ex.play_specific("soldiers logic by diabolic", target="spotify")

    assert result["played"] is False
    assert result["search_only"] is True


def test_try_open_and_play_rejects_a_stale_track_that_never_changed(monkeypatch):
    """Regression: opening a resolved URI then calling _spotify_play() can
    report "Playing" purely because a track from before is still playing —
    _spotify_open_uri() itself can silently fail to actually queue the new
    target. Metadata identical before and after must not be reported as
    success."""
    monkeypatch.setattr(ex, "_spotify_running", lambda: True)
    monkeypatch.setattr(ex, "_spotify_open_uri", lambda u: True)
    monkeypatch.setattr(ex, "_spotify_clear_track_repeat", lambda: True)
    monkeypatch.setattr(ex, "_spotify_play", lambda: True)
    monkeypatch.setattr(ex, "_spotify_live_meta",
                         lambda *a, **k: ("▶ Playing", "Immortal Technique", "Harlem Streets"))
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    result = ex._spotify_try_open_and_play(
        "spotify:track:abc123", label="“evil”", kind="track")

    assert result is None, "must fall through to another path, not claim a stale track as success"


def test_wait_playing_returns_true_when_status_flips(monkeypatch):
    states = iter([False, False, True])

    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_is_playing",
        lambda: next(states),
    )
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)
    assert ex._spotify_wait_playing(timeout=2.0) is True


def test_next_media_uses_mpv_when_youtube_is_active(monkeypatch):
    monkeypatch.setattr(ex, "_targets_mpv", lambda target: True)
    monkeypatch.setattr(ex, "_mpv_ipc", lambda cmd, **kw: True)
    out = ex.next_media()
    assert out["action"] == "NEXT_MEDIA"
    assert "YouTube" in out["content"]
