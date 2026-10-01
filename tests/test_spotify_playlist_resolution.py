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


def test_play_specific_tries_keystroke_automation_first(monkeypatch):
    """Typing into Spotify's own search box is tried before URI-scraping — the
    scrape can never resolve anything against the real site (its search page
    is a JS shell with no server-rendered track data), so it must not be the
    only, or first, thing standing between a request and real playback."""
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_search_type_and_play",
        lambda q: True,
    )

    result = ex.play_specific("soldiers logic by diabolic", target="spotify")

    assert result["ok"] is True
    assert result["played"] is True


def test_play_specific_resolves_and_plays_the_real_track_uri(monkeypatch):
    """When keystroke automation is unavailable (non-Linux, no xdotool), the real
    track URI must be resolved and opened directly, same as the album/playlist/
    artist paths already do — not a bare search with nothing selected."""
    opened_uris = []
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_search_type_and_play",
        lambda q: False,
    )
    monkeypatch.setattr(ex, "_spotify_resolve_track_uri", lambda q: "spotify:track:abc123")
    monkeypatch.setattr(ex, "_spotify_running", lambda: True)
    monkeypatch.setattr(ex, "_spotify_open_uri", lambda u: opened_uris.append(u) or True)
    monkeypatch.setattr(ex, "_spotify_clear_track_repeat", lambda: True)
    monkeypatch.setattr(ex, "_spotify_play", lambda: True)
    monkeypatch.setattr(ex, "_spotify_live_meta", lambda *a, **k: ("", "Diabolic", "Soldiers Logic"))
    monkeypatch.setattr(ex.time, "sleep", lambda _s: None)

    result = ex.play_specific("soldiers logic by diabolic", target="spotify")

    assert result["ok"] is True
    assert result["played"] is True
    assert opened_uris == ["spotify:track:abc123"]


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
