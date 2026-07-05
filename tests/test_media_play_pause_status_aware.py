"""play_pause is status-aware (regression, 2026-07-04).

The dashboard's now-playing pause button used playerctl's `play-pause` toggle, which
resumes reliably but frequently no-ops on *pausing* Spotify — so play worked, pause
didn't. Fix: play_pause queries the player's status and issues an EXPLICIT pause (when
playing) or play (when paused), the reliable path voice control uses. This locks in that
a playing player gets paused (not toggled), and a paused one gets resumed.
"""
import eli.integrations.mpris.playerctl_backend as mp


def _track(monkeypatch, status):
    calls = []
    monkeypatch.setattr(mp, "get_player_status",
                        lambda p=None: {"ok": True, "player": "spotify", "status": status})
    monkeypatch.setattr(mp, "pause", lambda p=None: (calls.append(("pause", p)), {"ok": True})[1])
    monkeypatch.setattr(mp, "play", lambda p=None: (calls.append(("play", p)), {"ok": True})[1])
    return calls


def test_play_pause_pauses_when_playing(monkeypatch):
    calls = _track(monkeypatch, "playing")
    mp.play_pause("spotify")
    assert calls == [("pause", "spotify")], calls


def test_play_pause_plays_when_paused(monkeypatch):
    calls = _track(monkeypatch, "paused")
    mp.play_pause("spotify")
    assert calls == [("play", "spotify")], calls


def test_play_pause_falls_back_to_toggle_when_status_unknown(monkeypatch):
    calls = []
    monkeypatch.setattr(mp, "get_player_status", lambda p=None: {"ok": False, "error": "no player"})
    monkeypatch.setattr(mp, "_playerctl",
                        lambda cmd, player=None, extra=None: (calls.append((cmd, player)), {"ok": True})[1])
    mp.play_pause("spotify")
    assert calls and calls[0][0] == "play-pause", calls
