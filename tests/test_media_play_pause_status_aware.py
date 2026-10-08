"""play_pause is status-aware (regression, 2026-07-04).

The dashboard's now-playing pause button used playerctl's `play-pause` toggle, which
resumes reliably but frequently no-ops on *pausing* Spotify — so play worked, pause
didn't. Fix: play_pause queries the player's status and issues an EXPLICIT pause (when
playing) or play (when paused), the reliable path voice control uses. This locks in that
a playing player gets paused (not toggled), and a paused one gets resumed.
"""
import eli.integrations.mpris.playerctl_backend as mp
import pytest


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


# After "next", ELI names the track that is now playing, or none.
#
# Live: "next" -> "⏭ Next track — spotify (Eminem — Trouble)", the track it had just skipped:
# the player had not switched yet when ELI read what was playing.
class _Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def player(monkeypatch):
    state = {"track": "old", "switch_after": 3, "reads": 0}
    tracks = {"old": ("Eminem", "Trouble"), "new": ("Eminem", "Evil")}

    def metadata(p, key):
        state["reads"] += 1
        if state.get("sent") and state["reads"] >= state["switch_after"]:
            state["track"] = state.get("next_track", state["track"])
        artist, title = tracks[state["track"]]
        return {"mpris:trackid": f"/track/{state['track']}", "xesam:artist": artist, "artist": artist,
                "xesam:title": title, "title": title}.get(key, "")

    def run(argv, timeout=8, input_bytes=None):
        if argv[-1] in ("next", "previous"):
            state["sent"] = True
            state["reads"] = 0
        return True, "Playing" if argv[-1] == "status" else "", ""

    monkeypatch.setattr(mp, "_has", lambda tool: True)
    monkeypatch.setattr(mp, "get_active_player", lambda command=None: "spotify")
    monkeypatch.setattr(mp, "_metadata", metadata)
    monkeypatch.setattr(mp, "_run", run)
    monkeypatch.setattr(mp, "time", _Clock())
    return state


def test_next_names_the_track_it_moved_to(player):
    player["next_track"] = "new"
    r = mp.next_track()
    assert r["ok"] and "Evil" in r["content"] and "Trouble" not in r["content"]


def test_a_track_that_never_changed_is_not_named(player):
    r = mp.next_track()
    assert r["ok"] and "Trouble" not in r["content"]
