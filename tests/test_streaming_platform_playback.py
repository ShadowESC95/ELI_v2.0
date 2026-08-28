"""Streaming-platform PLAY_MEDIA — every named service opens its own search, never YouTube."""
from __future__ import annotations

import pytest

from eli.execution.media_runtime import (
    _STREAMING_CANONICAL_URLS,
    _STREAMING_ALIASES,
    normalize_streaming_target,
)


# Every alias users/STT might produce for each canonical platform.
_STREAMING_CASES = [
    ("netflix", "netflix", "Stranger Things"),
    ("net flix", "netflix", "Stranger Things"),
    ("prime video", "primevideo", "the walking dead"),
    ("primevideo", "primevideo", "the walking dead"),
    ("amazon prime", "primevideo", "the walking dead"),
    ("disney+", "disneyplus", "mandalorian"),
    ("disney plus", "disneyplus", "mandalorian"),
    ("disney", "disneyplus", "mandalorian"),
    ("hulu", "hulu", "rick and morty"),
    ("hbo max", "max", "succession"),
    ("max", "max", "succession"),
    ("paramount", "paramountplus", "yellowstone"),
    ("paramount+", "paramountplus", "yellowstone"),
    ("peacock", "peacock", "the office"),
    ("apple tv", "appletv", "severance"),
    ("plex", "plex", "blade runner"),
    ("crunchyroll", "crunchyroll", "one piece"),
    ("discovery+", "discoveryplus", "gold rush"),
    ("tubi", "tubi", "night of the living dead"),
    ("pluto tv", "pluto", "star trek"),
    ("twitch", "twitch", "speedrun"),
]


@pytest.mark.parametrize("spoken,canonical,query", _STREAMING_CASES)
def test_normalize_streaming_target_aliases(spoken, canonical, query):
    assert normalize_streaming_target(spoken) == canonical


@pytest.mark.parametrize("spoken,canonical,query", _STREAMING_CASES)
def test_play_specific_streaming_never_youtube(spoken, canonical, query, monkeypatch):
    opened: list[str] = []

    def _fake_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr("eli.utils.platform_compat.open_url", _fake_open)

    from eli.execution.executor_enhanced import play_specific

    result = play_specific(query, spoken)
    assert result.get("target") == canonical
    assert "YouTube" not in (result.get("response") or "")
    assert opened
    assert "youtube.com" not in opened[0].lower()
    expected_host = _STREAMING_CANONICAL_URLS[canonical].split("/")[2]
    assert expected_host in opened[0]


@pytest.mark.parametrize("spoken,canonical,query", _STREAMING_CASES[:6])
def test_execute_play_media_honours_streaming_target(spoken, canonical, query, monkeypatch):
    opened: list[str] = []

    monkeypatch.setattr("eli.utils.platform_compat.open_url", lambda u: opened.append(u) or True)

    from eli.execution.executor_enhanced import execute_action

    result = execute_action(
        "PLAY_MEDIA",
        {"query": query, "target": spoken, "service": spoken},
    )
    assert isinstance(result, dict)
    assert result.get("target") == canonical
    assert "YouTube" not in (result.get("response") or "")
    assert opened


def test_all_canonical_streaming_platforms_have_aliases():
    """Every canonical id must be reachable by at least its own key."""
    for canon in _STREAMING_CANONICAL_URLS:
        assert normalize_streaming_target(canon) == canon
    assert len(_STREAMING_ALIASES) >= len(_STREAMING_CANONICAL_URLS)
