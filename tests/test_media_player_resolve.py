"""MPRIS player-target resolution (regression, 2026-07-05).

The dashboard's now-playing widget passes the live MPRIS id (e.g. "firefox.instance_1_125")
to control a browser tab. `_target_terms` rewrote underscores to spaces, so the exact id
failed to match its OWN name → `resolve_player_target` returned None → every pause/play
silently no-op'd (the "Netflix/YouTube pause does nothing" bug). This locks in that an
exact id (any case) and an underscore-bearing partial both resolve.
"""
import eli.integrations.mpris.playerctl_backend as mp

_PLAYERS = [
    {"player": "firefox.instance_1_125", "status": "playing", "title": "Netflix",
     "artist": "", "album": "", "url": "https://netflix.com", "identity": "Firefox",
     "desktop_entry": "firefox"},
    {"player": "spotify", "status": "paused", "title": "A Song",
     "artist": "Band", "album": "LP", "url": "", "identity": "Spotify", "desktop_entry": "spotify"},
]


def _patch(monkeypatch):
    monkeypatch.setattr(mp, "list_player_infos", lambda: [dict(p) for p in _PLAYERS])
    monkeypatch.setattr(mp, "list_players", lambda: [p["player"] for p in _PLAYERS])


def test_exact_browser_id_resolves(monkeypatch):
    _patch(monkeypatch)
    assert mp.resolve_player_target("firefox.instance_1_125", command="pause") == "firefox.instance_1_125"


def test_exact_id_is_case_insensitive(monkeypatch):
    _patch(monkeypatch)
    assert mp.resolve_player_target("FIREFOX.INSTANCE_1_125") == "firefox.instance_1_125"


def test_partial_id_with_underscores_resolves(monkeypatch):
    _patch(monkeypatch)
    assert mp.resolve_player_target("instance_1_125") == "firefox.instance_1_125"


def test_friendly_name_still_resolves(monkeypatch):
    _patch(monkeypatch)
    assert mp.resolve_player_target("spotify") == "spotify"
    # a generic "browser" target still finds the firefox tab
    assert mp.resolve_player_target("netflix", command="pause") == "firefox.instance_1_125"
