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


def test_the_machines_own_programs_are_stand_ins_that_reach_nothing():
    """`flatpak search` and `flatpak run` made a Flatpak repository in the home folder and
    `bluetoothctl list` asked the real radio; here each is a stand-in that fails, as where it is not
    installed."""
    import shutil
    stand_ins = os.path.join(os.environ["ELI_TEST_SANDBOX"], "no-launchers")
    for program in ("flatpak", "bluetoothctl", "nmcli", "snap", "xdotool", "wmctrl"):
        assert os.path.dirname(shutil.which(program)) == stand_ins, program
    out = subprocess.run(["sh", "-c", "bluetoothctl list; flatpak search firefox"], capture_output=True, text=True)
    assert out.returncode != 0 and out.stdout == ""


def test_a_real_run_of_one_is_named_by_the_test_that_started_it():
    import tests.conftest as suite
    before = len(suite.MACHINE_RUNS)
    suite._note_machine_program(("/usr/bin/flatpak", ["/usr/bin/flatpak", "run", "an.App"], None, None))
    suite._note_machine_program((None, ["/bin/sh", "-c", "flatpak list"], None, None))   # the stand-in
    try:
        assert suite.MACHINE_RUNS[before:] == [
            "/usr/bin/flatpak (run by tests/test_tests_stay_off_the_desktop.py::"
            "test_a_real_run_of_one_is_named_by_the_test_that_started_it)"]
    finally:
        del suite.MACHINE_RUNS[before:]
