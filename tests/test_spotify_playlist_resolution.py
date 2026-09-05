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
    assert ex._spotify_resolve_playlist_uri("workout") == "spotify:playlist:37i9dQZF1DX0XUsuxWHRQd"


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
