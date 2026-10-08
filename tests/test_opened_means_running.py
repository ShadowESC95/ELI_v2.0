""""Opened app: X" only when X is running afterwards.

Spotify started from the 2.5.6 AppImage died on the bundle's libraries a moment after the launch,
and ELI had already said "Opened app: Spotify": the launch call returning was taken as the app
being open.
"""
import pytest

from eli.system import portable_app_control as pac


@pytest.fixture
def linux_spotify(monkeypatch):
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac, "resolve_app", lambda q: pac.AppCandidate(
        name="Spotify", command=["spotify"], desktop_id="spotify.desktop", source="desktop"))
    monkeypatch.setattr(pac.shutil, "which", lambda c, *a, **k: f"/usr/bin/{c}")
    monkeypatch.setattr(pac, "_popen", lambda args: True)
    import time
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    return monkeypatch


def test_an_app_that_dies_at_once_is_not_reported_open(linux_spotify):
    clock = iter(range(1000))
    linux_spotify.setattr("time.monotonic", lambda: next(clock))
    linux_spotify.setattr(pac, "_app_running", lambda needles, loose=True: False)
    r = pac.open_app("spotify")
    assert r["ok"] is False and "closed straight away" in r["content"]


def test_an_app_that_stays_up_is_open(linux_spotify):
    # not up before the launch, up after it
    linux_spotify.setattr(pac, "_app_running", lambda needles, loose=True: loose and "spotify" in needles)
    assert pac.open_app("spotify")["ok"] is True


def test_the_needles_name_the_app():
    target = pac.AppCandidate(name="LibreOffice Writer", command=["/usr/bin/libreoffice"],
                              desktop_id="libreoffice-writer.desktop")
    needles = pac._process_needles(target)
    assert "libreoffice" in needles and "writer" in needles


def test_only_the_program_counts_not_its_arguments(monkeypatch):
    import psutil

    class P:
        def __init__(self, pid, name, cmdline):
            self.info = {"pid": pid, "name": name, "cmdline": cmdline}

    procs = [P(10, "playerctl", ["playerctl", "-p", "spotify", "status"]),
             P(11, "grep", ["grep", "spotify"]),
             P(12, "gnome-shell", ["/usr/bin/gnome-shell"])]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))
    assert not pac._app_running(["spotify"])
    procs.append(P(13, "spotify", ["/usr/share/spotify/spotify", "--uri=x"]))
    assert pac._app_running(["spotify"])


def test_before_a_launch_only_the_program_itself_counts(monkeypatch):
    import psutil

    class P:
        def __init__(self, pid, name, cmdline):
            self.info = {"pid": pid, "name": name, "cmdline": cmdline}

    procs = [P(10, "gsd-xsettings", ["/usr/libexec/gsd-xsettings"]),
             P(11, "java", ["/usr/bin/java", "-jar", "/opt/jdownloader/JDownloader.jar"])]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(procs))
    assert not pac._app_running(["settings"], loose=False)
    assert pac._app_running(["jdownloader"])                 # stayed up, run by java
    procs.append(P(12, "soffice.bin", ["/usr/lib/libreoffice/program/soffice.bin", "--writer"]))
    assert pac._app_running(["libreoffice"], loose=False)


def test_a_vendor_name_is_not_the_app():
    target = pac.AppCandidate(name="Calculator", command=["gnome-calculator"],
                              desktop_id="org.gnome.Calculator.desktop")
    assert "gnome" not in pac._process_needles(target)
