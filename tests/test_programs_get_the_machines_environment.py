"""Programs ELI starts from a frozen build get the machine's environment, not the bundle's.

In the 2.5.6 AppImage every child inherited LD_LIBRARY_PATH=<bundle>/_internal: dbus-send died
on the bundle's libdbus (so every MPRIS call to Spotify failed), /usr/bin/yt-dlp on its
libcrypto, and Spotify launched by ELI exited at once while ELI said "Opened app: Spotify".
"""
import os
import pathlib
import subprocess
import sys

import pytest

from eli.core import host_env as he

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    b = tmp_path / "bundle"
    (b / "bin").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(b), raising=False)
    monkeypatch.setattr(sys, "executable", str(b / "ELI"))
    monkeypatch.delenv("APPDIR", raising=False)
    return b


J = os.pathsep


def test_the_bundle_is_taken_out_of_a_childs_environment(bundle):
    env = he.host_env({
        "LD_LIBRARY_PATH": J.join([f"{bundle}/_internal", "/opt/user/lib"]), "LD_LIBRARY_PATH_ORIG": "/opt/user/lib",
        "QT_PLUGIN_PATH": f"{bundle}/qt/plugins", "SSL_CERT_FILE": f"{bundle}/certifi/cacert.pem",
        "PATH": J.join([f"{bundle}/bin", "/usr/bin", "/bin"]), "XDG_DATA_DIRS": J.join([f"{bundle}/share", "/usr/share"]),
        "_PYI_APPLICATION_HOME_DIR": str(bundle), "HOME": "/home/u", "LANG": "en_IE.UTF-8",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
    })
    assert env["LD_LIBRARY_PATH"] == "/opt/user/lib" and "LD_LIBRARY_PATH_ORIG" not in env
    assert "QT_PLUGIN_PATH" not in env and "SSL_CERT_FILE" not in env
    assert env["PATH"] == J.join(["/usr/bin", "/bin"]) and env["XDG_DATA_DIRS"] == "/usr/share"
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert env["HOME"] == "/home/u" and env["LANG"] == "en_IE.UTF-8"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_the_bundle_is_found_as_given_and_as_resolved(bundle, tmp_path, monkeypatch):
    # macOS: a bundle unpacked under /var/folders is /private/var/folders resolved.
    link = tmp_path / "var"
    link.symlink_to(bundle)
    monkeypatch.setattr(sys, "_MEIPASS", str(link))
    env = he.host_env({"SSL_CERT_FILE": f"{link}/certifi/cacert.pem", "QT_PLUGIN_PATH": f"{bundle}/qt",
                       "PATH": J.join([f"{link}/bin", "", "/usr/bin"])})
    assert "SSL_CERT_FILE" not in env and "QT_PLUGIN_PATH" not in env
    assert env["PATH"] == J.join(["", "/usr/bin"])


def test_from_source_nothing_changes(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)
    base = {"LD_LIBRARY_PATH": "/x", "PATH": "/usr/bin"}
    assert he.host_env(base) == base


@pytest.mark.skipif(os.name == "nt", reason="uses env(1)")
def test_installed_wrapper_cleans_system_programs_only(bundle, monkeypatch):
    monkeypatch.setattr(subprocess.Popen, "__init__", subprocess.Popen.__init__)   # restored after
    monkeypatch.setattr(he, "_installed", False)
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{bundle}/_internal")
    monkeypatch.setenv("QT_PLUGIN_PATH", f"{bundle}/qt")
    own = bundle / "bin" / "helper"
    own.write_text("#!/bin/sh\nenv\n")
    own.chmod(0o755)
    he.install()
    system = subprocess.run(["env"], capture_output=True, text=True).stdout
    assert str(bundle) not in system
    ours = subprocess.run([str(own)], capture_output=True, text=True).stdout
    assert f"LD_LIBRARY_PATH={bundle}/_internal" in ours


def test_the_frozen_entry_installs_it_before_anything_runs():
    src = (ROOT / "packaging/pyinstaller/eli_entry.py").read_text(encoding="utf-8")
    assert src.index("_install_host_env()") < src.index('sys.argv[1] == "-c"')
