"""The test run cannot reach this machine's desktop session.

A test run once started the real Spotify and played a song: a new code path asked Spotify over
the session bus, and an older test had not stubbed it. conftest.py takes the session bus and the
display away for the whole run, as on a CI runner, so no test can do that again.
"""
import os
import subprocess
import sys


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


def test_sound_cannot_reach_a_real_device():
    """The real audio libraries load in tests now; nothing a test plays or sets can reach the speakers.
    conftest.py takes the sound servers away through the environment, which only Linux honours (a CI
    runner of any OS has no speakers)."""
    if not sys.platform.startswith("linux"):
        __import__("pytest").skip("the sound servers are taken away by environment on Linux only")
    try:
        import sounddevice as sd
        outputs = [d["name"] for d in sd.query_devices() if d["max_output_channels"] > 0]
    except (ImportError, OSError):
        outputs = []        # no PortAudio library at all
    except Exception as e:  # PortAudioError: no sound system reachable, as on a CI runner
        assert type(e).__name__ == "PortAudioError", e
        outputs = []
    assert all(name in ("default", "null") for name in outputs), outputs
    try:
        mixer = subprocess.run(["amixer", "scontrols"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return
    assert "Master" not in mixer.stdout, "a test could change this machine's volume"
