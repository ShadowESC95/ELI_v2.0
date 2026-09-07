"""Tests for Spotify intent parsing (no network)."""
from eli.integrations.media import spotify_intent as si


def test_sanitize_strips_chat_log_prefix():
    q = "🧑 You [11:51:07]: play the liar and a thief album diabolic"
    cleaned = si.sanitize_media_query(q)
    assert "the liar and a thief album diabolic" == cleaned
    assert "🧑" not in cleaned


def test_liked_songs_playlist_name():
    assert si.playlist_name("my liked songs playlist") == "liked songs"
    assert si.is_liked_songs("liked songs")


def test_album_by_artist():
    name, artist = si.album_request("a liar and a thief album by diabolic")
    assert name == "a liar and a thief"
    assert artist == "diabolic"


def test_album_without_artist():
    name, artist = si.album_request("the marshall mathers lp album")
    assert name == "marshall mathers lp"
    assert artist is None


def test_artist_songs_request():
    assert si.artist_songs_request("songs by diabolic") == "diabolic"


def test_mpv_load_confirmed_rejects_bool_duration(monkeypatch):
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.mpv_ipc_send",
        lambda cmd, **kw: True if cmd[-1] == "duration" else False,
    )
    from eli.execution.executor_enhanced import _mpv_load_confirmed
    assert _mpv_load_confirmed("/tmp/fake.sock") is False


def test_youtube_mpv_query_skips_album_suffix_for_plain_songs():
    from eli.integrations.media.spotify_intent import youtube_mpv_query
    assert "album" not in youtube_mpv_query("never gonna give you up").lower()


def test_youtube_mpv_query_album_by_artist():
    from eli.integrations.media.spotify_intent import youtube_mpv_query
    q = youtube_mpv_query("the album liar and a thief by diabolic")
    assert "diabolic" in q.lower()
    assert "official audio" in q.lower()
    q = si.youtube_search_query("the album liar and a thief by diabolic")
    assert "diabolic" in q.lower()
    assert "liar" in q.lower()
    assert "album" in q.lower()


def test_prefers_spotify_for_album_phrasing():
    assert si.prefers_spotify_music_context("the marshall mathers lp album")
