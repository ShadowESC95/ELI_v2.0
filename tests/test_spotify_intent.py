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


def test_album_mid_string_artist_album_name():
    """Regression (live session): "play diabolics album liar and a thief" and
    "play the arctic monkeys album AM on spotify" both fell through to a bare
    track search typed verbatim, resolving to an unrelated song/album —
    album_request() only recognised "X album" (trailing) or "album X"
    (leading), never "ARTIST album ALBUMNAME" with "album" as a mid-string
    separator, which is how both real requests were phrased."""
    name, artist = si.album_request("diabolics album liar and a thief")
    assert name == "liar and a thief"
    assert artist == "diabolics"

    name, artist = si.album_request("the arctic monkeys album am")
    assert name == "am"
    assert artist == "arctic monkeys"


def test_album_mid_string_does_not_override_by_phrasing():
    """"NAME album by ARTIST" must still resolve via the existing, more
    specific "by" branch, not the new mid-string fallback — adding the
    fallback must not regress the already-working case this exercises."""
    name, artist = si.album_request("a liar and a thief album by diabolic")
    assert name == "a liar and a thief"
    assert artist == "diabolic"


def test_liked_songs_recognises_bare_liked_and_liked_playlist():
    """Regression: "play my liked playlist on spotify" extracted playlist
    name "liked" (via playlist_name()'s generic "X playlist" pattern), but
    is_liked_songs("liked") required "liked song(s)" and rejected bare
    "liked" — so it searched Spotify for a playlist literally named "liked"
    instead of opening the real Liked Songs collection."""
    assert si.is_liked_songs("liked") is True
    assert si.is_liked_songs("my liked playlist") is True
    assert si.is_liked_songs("liked playlist") is True
    assert si.playlist_name("my liked playlist") == "liked"


def test_liked_songs_recognises_the_phrase_without_the_word_playlist():
    """Regression: "play my liked songs in spotify" has no "playlist" in it
    at all, so playlist_name() never extracted anything and the liked-songs
    branch (gated behind a truthy extracted name) never ran — the query fell
    through and got typed verbatim into Spotify's track search, which then
    silently resumed whatever was already playing and reported false success."""
    assert si.is_liked_songs("my liked songs") is True
    assert si.is_liked_songs("liked songs") is True
    assert si.playlist_name("my liked songs") == "", (
        "no 'playlist' word in this phrasing — confirms the raw-query check "
        "is what must catch it, not playlist_name() extraction"
    )
