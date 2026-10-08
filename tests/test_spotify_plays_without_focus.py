"""Playing a named song on Spotify without window focus or keystrokes.

Under GNOME 50 (Wayland only) Spotify is a native Wayland window: xdotool and wmctrl cannot see
it, so the type-into-search path waited 12 s for a window that never appeared, refused to type
(it cannot confirm focus) twice, then opened an https search page that only shows results. Every
"play X" took 16 s and played nothing. Over MPRIS, OpenUri("spotify:search:<query>") makes the
desktop client play its top result (checked live on Spotify 1.2.82), and success is only claimed
when the song that starts is the one asked for.
"""
from __future__ import annotations

import pytest

from eli.integrations.media import cross_platform as cp


@pytest.mark.parametrize("query,artist,title,ok", [
    ("trouble eminem", "Eminem", "Trouble", True),
    ("trouble by eminem", "Eminem", "Trouble", True),
    ("trouble eminem", "Eminem", "Mockingbird", False),         # one shared word is not the song
    ("point of no return immortal technique", "Immortal Technique", "Point Of No Return", True),
    ("lose yourself eminem", "Eminem", "Lose Yourself - Original Demo Version", True),
    ("evil by eminem", "Immortal Technique", "Point Of No Return", False),
    ("anything", "", "", False),
    ("juicy notorious big", "The Notorious B.I.G.", "Juicy", True),    # dotted initials
    ("dont stop me now queen", "Queen", "Don't Stop Me Now", True),
])
def test_the_playing_song_must_be_the_one_asked_for(query, artist, title, ok):
    assert cp.query_matches_track(query, artist, title) is ok


def _linux_spotify(monkeypatch, metas, *, bus=True):
    opened = []
    monkeypatch.setattr(cp.pc, "LINUX", True)
    monkeypatch.setattr(cp.shutil, "which", lambda c: f"/usr/bin/{c}")
    monkeypatch.setattr(cp, "_session_bus_reachable", lambda: bus)
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp, "spotify_open_uri", lambda uri: opened.append(uri) or True)
    it = iter(metas)
    monkeypatch.setattr(cp, "spotify_live_meta", lambda player="spotify": next(it, metas[-1]))
    monkeypatch.setattr(cp.time, "sleep", lambda *_: None)
    return opened


def test_the_top_result_is_asked_for_over_mpris_and_confirmed(monkeypatch):
    opened = _linux_spotify(monkeypatch, [("⏸ Paused", "Eminem", "Mockingbird"),
                                          ("▶ Playing", "Eminem", "Trouble")])
    assert cp.spotify_play_top_search_result("trouble eminem") is True
    # the spotify: form, which plays; the https search page only shows results
    assert opened == ["spotify:search:trouble eminem"]


def test_a_different_song_starting_is_not_success(monkeypatch):
    clock = iter(range(0, 1000))
    monkeypatch.setattr(cp.time, "monotonic", lambda: next(clock))
    _linux_spotify(monkeypatch, [("▶ Playing", "Coldplay", "Trouble")])
    assert cp.spotify_play_top_search_result("trouble eminem", timeout=6) is False


def test_without_a_session_bus_nothing_is_launched(monkeypatch):
    launched = []
    _linux_spotify(monkeypatch, [("", "", "")], bus=False)
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: launched.append(1) or True)
    assert cp.spotify_play_top_search_result("trouble eminem") is False
    assert not launched


def test_typing_is_not_tried_on_a_window_the_x_tools_cannot_see(monkeypatch):
    from eli.system import portable_app_control as pac
    from eli.utils import platform_compat as platc
    typed = []
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(pac, "display_server", lambda: "wayland")
    monkeypatch.setattr(pac, "window_exists", lambda name: False)
    monkeypatch.setattr(pac, "focus_app", lambda name: {"ok": True})
    monkeypatch.setattr(platc, "type_text", lambda text: typed.append(text) or True)
    monkeypatch.setattr(cp.time, "sleep", lambda *_: None)
    assert cp.spotify_search_type_and_play("trouble eminem") is False
    assert not typed


def test_the_reply_names_what_is_playing_and_never_asks_the_user_to_press_play(monkeypatch):
    from eli.execution import executor_enhanced as ex
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_play_top_search_result", lambda q, timeout=10.0, launch=True: False)
    monkeypatch.setattr(cp, "spotify_search_type_and_play", lambda q, launch=True: False)
    monkeypatch.setattr(ex, "_spotify_running", lambda: True)
    monkeypatch.setattr(ex, "_spotify_search", lambda q, prefer=None: True)
    monkeypatch.setattr(ex, "_spotify_play", lambda: True)
    monkeypatch.setattr(ex, "_spotify_clear_track_repeat", lambda: False)
    monkeypatch.setattr(ex, "_now_playing_matches_query", lambda q: False)
    monkeypatch.setattr(ex, "_spotify_live_meta", lambda: ("▶ Playing", "Coldplay", "Trouble"))
    monkeypatch.setattr(ex.time, "sleep", lambda *_: None)
    r = ex.play_specific("trouble by eminem", "spotify")
    text = r["response"].lower()
    assert "coldplay" in text and "press play" not in text
