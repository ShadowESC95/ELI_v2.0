"""The test run cannot reach this machine's desktop session.

A test run once started the real Spotify and played a song: a new code path asked Spotify over
the session bus, and an older test had not stubbed it. conftest.py takes the session bus and the
display away for the whole run, as on a CI runner, so no test can do that again.
"""
import os
import subprocess


def test_no_display_and_no_session_bus():
    assert not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    assert "no-session-bus" in os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")


def test_a_media_player_call_cannot_reach_a_real_player():
    from eli.integrations.media import cross_platform as cp
    assert cp._session_bus_reachable() is False
    try:
        out = subprocess.run(["playerctl", "-l"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return
    assert "spotify" not in out.stdout
