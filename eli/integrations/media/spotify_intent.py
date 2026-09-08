"""Parse user phrasing into Spotify playback intents (no Web API)."""
from __future__ import annotations

import re

_PLAYLIST_RE = re.compile(
    r"^\s*(?:my|the|a)?\s*(?P<name>.+?)\s*(?:play\s*list|playlist)\s*$", re.I
)
_LIKED_SONGS_RE = re.compile(
    r"^(?:my\s+)?(?:liked\s+songs?|likes|favourites?|favorites?)$",
    re.I,
)
_ALBUM_RE = re.compile(
    r"^\s*(?:the\s+)?(?P<name>.+?)\s+album\s*$", re.I
)
_LP_RE = re.compile(
    r"^\s*(?:the\s+)?(?P<name>.+?)\s+lp\s*$", re.I
)
_ALBUM_CMD_RE = re.compile(
    r"^(?:the\s+)?album\s+(.+)$", re.I
)
_ARTIST_SONGS_RE = re.compile(
    r"^(?:songs?|tracks?|music)\s+by\s+(?P<artist>.+)$", re.I
)
_CHAT_LOG_RE = re.compile(
    r"^(?:🧑\s*)?(?:You|ELI)\s*\[\d{1,2}:\d{2}(?::\d{2})?\]\s*:\s*",
    re.I,
)
_ON_SPOTIFY_TAIL_RE = re.compile(r"\s+on\s+spotify\s*$", re.I)


def sanitize_media_query(query: str) -> str:
    """Strip chat-log prefixes and trailing platform noise from a play query."""
    q = str(query or "").strip()
    for _ in range(3):
        q2 = _CHAT_LOG_RE.sub("", q).strip()
        if q2 == q:
            break
        q = q2
    q = _ON_SPOTIFY_TAIL_RE.sub("", q).strip()
    q = re.sub(r"^(?:please\s+)?(?:can you\s+)?(?:ply|play)\s+", "", q, flags=re.I).strip()
    return q


def playlist_name(query: str) -> str:
    m = _PLAYLIST_RE.match(str(query or ""))
    if not m:
        return ""
    name = (m.group("name") or "").strip(" .,:;-")
    return name if len(name) >= 2 else ""


def is_liked_songs(name: str) -> bool:
    return bool(_LIKED_SONGS_RE.match(str(name or "").strip()))


def album_request(query: str) -> tuple[str, str | None]:
    """Return (album_name, artist_or_none) when the user asked for an album."""
    q = normalize_play_query(query)
    by_m = re.match(r"^(.+?)\s+by\s+(.+)$", q, re.I)
    if by_m:
        left = (by_m.group(1) or "").strip()
        artist = (by_m.group(2) or "").strip()
        for _pat in (_ALBUM_RE, _LP_RE):
            am = _pat.match(left)
            if am:
                name = (am.group("name") or "").strip(" .,:;-")
                if len(name) >= 2:
                    return name, artist if len(artist) >= 2 else None
    for _pat in (_ALBUM_RE, _LP_RE):
        am = _pat.match(q)
        if am:
            name = (am.group("name") or "").strip(" .,:;-")
            if len(name) >= 2:
                return name, None
    cmd_m = _ALBUM_CMD_RE.match(q)
    if cmd_m:
        name = (cmd_m.group(1) or "").strip(" .,:;-")
        if len(name) >= 2:
            return name, None
    return "", None


def artist_songs_request(query: str) -> str:
    m = _ARTIST_SONGS_RE.match(str(query or "").strip())
    if not m:
        return ""
    artist = (m.group("artist") or "").strip(" .,:;-")
    return artist if len(artist) >= 2 else ""


def normalize_play_query(query: str) -> str:
    """Strip chat noise and leading 'the album' filler from a play request."""
    q = sanitize_media_query(query)
    q = re.sub(r"^(?:the\s+)?album\s+", "", q, flags=re.I).strip()
    return q


def youtube_search_query(query: str) -> str:
    """Turn natural album phrasing into a YouTube-friendly search string."""
    q = normalize_play_query(query)
    raw = str(query or "").lower()
    if not re.search(r"\balbum\b", raw) and not re.match(r"^\s*the\s+album\b", raw):
        return q
    by_m = re.match(r"^(.+?)\s+by\s+(.+)$", q, re.I)
    if by_m:
        title, artist = by_m.group(1).strip(), by_m.group(2).strip()
        title = re.sub(r"\s+album\s*$", "", title, flags=re.I).strip()
        if "album" not in title.lower():
            title = f"{title} album"
        return f"{artist} {title}"
    if "album" not in q.lower():
        q = f"{q} album"
    return q


def youtube_mpv_query(query: str, *, by_artist: tuple[str, str] | None = None) -> str:
    """Search string for headless mpv/yt-dlp — album-aware, otherwise plain."""
    if album_request(query)[0] or re.search(r"\balbum\b", str(query or ""), re.I):
        base = youtube_search_query(query)
        return base if "official audio" in base.lower() else f"{base} official audio"
    q = normalize_play_query(query)
    if by_artist:
        return f"{by_artist[0]} {by_artist[1]} official audio"
    return q


def prefers_spotify_music_context(query: str) -> bool:
    """True when phrasing is album/playlist/artist — not a bare song title."""
    q = str(query or "").strip().lower()
    if not q:
        return False
    if playlist_name(query) or is_liked_songs(playlist_name(query)):
        return True
    if album_request(query)[0]:
        return True
    if artist_songs_request(query):
        return True
    return bool(re.search(r"\b(?:album|playlist|play\s*list|liked\s+songs?)\b", q))
