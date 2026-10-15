"""Desktop launchers must never bake versioned extract paths into .desktop files."""
from __future__ import annotations

from pathlib import Path

import eli.runtime.desktop_launchers as dl


def test_linux_desktop_has_no_path_or_extract_folder(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(dl, "product_line", lambda: "v2")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    root = tmp_path / "ELI_v2-2.4.29-linux-portable"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "eli-v2.0"\nversion = "2.4.34"\n', encoding="utf-8"
    )
    for name in ("eli_launch.sh", "eli_serve.sh", "eli_setup.sh", "eli_term.sh", "eli_uninstall.sh"):
        p = root / "scripts" / name
        p.write_text("#!/bin/bash\n", encoding="utf-8")
        p.chmod(0o755)

    monkeypatch.setattr(dl, "sys", type("S", (), {"platform": "linux", "frozen": False})())
    # Force linux branch even if host is linux (it is)
    written = dl.install_desktop_launchers(root, force=True)
    assert written

    apps = home / ".local" / "share" / "applications"
    desk = (apps / "eli-v2.desktop").read_text(encoding="utf-8")
    assert "Path=" not in desk
    assert "linux-portable" not in desk
    assert "2.4.29" not in desk
    assert "eli-v2-run" in desk
    assert 'Exec="' in desk and " gui" in desk

    pointer = (home / ".local" / "share" / "ELI_v2" / "runtime" / "install_root").read_text(
        encoding="utf-8"
    ).strip()
    assert pointer == str(root.resolve())

    guard = home / ".local" / "bin" / "eli-v2-run"
    assert guard.is_file()
    gtxt = guard.read_text(encoding="utf-8")
    assert "install_root" in gtxt
    assert "linux-portable" not in gtxt

    # Desktop mirror must exist and also be Path=-free
    desk_copy = home / "Desktop" / "eli-v2.desktop"
    # Desktop may not exist in this fixture — create and reinstall
    (home / "Desktop").mkdir(exist_ok=True)
    dl.install_desktop_launchers(root, force=True)
    assert desk_copy.is_file()
    assert "Path=" not in desk_copy.read_text(encoding="utf-8")


def test_stale_path_line_detected():
    stale = (
        "[Desktop Entry]\nName=ELI v2.0\n"
        'Exec=/home/jess/.local/bin/eli-run "/home/jess/Downloads/ELI_v2-2.4.29-linux-portable" gui\n'
        "Path=/home/jess/Downloads/ELI_v2-2.4.29-linux-portable\n"
    )
    assert dl._desktop_is_stale(stale, Path("/home/jess/.local/bin/eli-run"), "2.4.34")


def test_scrub_removes_gnome_dead_path_stub(tmp_path, monkeypatch):
    """GNOME never runs Exec when Path= points at a missing folder — scrub must delete it."""
    home = tmp_path / "home"
    apps = home / ".local" / "share" / "applications"
    desk = home / "Desktop"
    apps.mkdir(parents=True)
    desk.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(dl, "product_line", lambda: "v2")

    dead = desk / "ELI v2.0.desktop"
    dead.write_text(
        "[Desktop Entry]\nName=ELI v2.0\n"
        "Path=/home/jess/Downloads/ELI_v2-2.4.29-linux-portable\n"
        'Exec=/home/jess/.local/bin/eli-run "/home/jess/Downloads/ELI_v2-2.4.29-linux-portable" gui\n',
        encoding="utf-8",
    )
    removed = dl.scrub_stale_eli_desktops()
    assert dead in removed or not dead.exists()
    assert not dead.exists()


def test_install_replaces_dead_desktop_stub(tmp_path, monkeypatch):
    home = tmp_path / "home"
    desk = home / "Desktop"
    desk.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(dl, "product_line", lambda: "v2")

    root = tmp_path / "ELI_v2-2.4.37-linux-portable"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "eli-v2.0"\nversion = "2.4.37"\n', encoding="utf-8"
    )
    (desk / "eli-v2.desktop").write_text(
        "[Desktop Entry]\nName=ELI v2.0\n"
        "Path=/home/jess/Downloads/ELI_v2-2.4.29-linux-portable\n"
        'Exec=/old/eli-run "/home/jess/Downloads/ELI_v2-2.4.29-linux-portable" gui\n',
        encoding="utf-8",
    )
    dl.install_desktop_launchers(root, force=True)
    refreshed = (desk / "eli-v2.desktop").read_text(encoding="utf-8")
    assert "Path=" not in refreshed
    assert "2.4.29" not in refreshed
    assert "eli-v2-run" in refreshed


def test_v2_never_touches_another_eli_versions_launchers(tmp_path, monkeypatch):
    """v3, the first version (eli-ai), ELI Legal, ELI VR and AI_Eli are separate products: v2's setup
    and clean-up must leave their launchers exactly as they are, stale-looking or not."""
    home = tmp_path / "home"
    apps = home / ".local" / "share" / "applications"
    desk = home / "Desktop"
    apps.mkdir(parents=True)
    desk.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(dl, "product_line", lambda: "v2")
    others = {
        "eli-v3.desktop": "Name=ELI v3.0\nExec=/home/x/.local/bin/eli-v3-run gui\nX-ELI-Version=3.0.137\n",
        "eli-setup.desktop": "Name=ELI Setup 3.0.137\nExec=/home/x/.local/bin/eli-run setup\nX-ELI-Version=3.0.137\n",
        "eli-ai.desktop": "Name=ELI\nExec=/home/x/ELI-0.1.1-x86_64.AppImage\n",
        "eli-legal.desktop": "Name=ELI Legal\nExec=/opt/eli-legal/eli-legal\nPath=/missing/folder\n",
        "eli-vr.desktop": "Name=ELI VR\nExec=/home/x/ELI_VR-0.9.2-x86_64.AppImage\n",
    }
    for d in (apps, desk):
        for name, body in others.items():
            (d / name).write_text("[Desktop Entry]\n" + body, encoding="utf-8")

    root = tmp_path / "ELI_v2-2.5.15-linux-portable"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "eli-v2.0"\nversion = "2.5.15"\n', encoding="utf-8")
    dl.scrub_stale_eli_desktops()
    dl.install_desktop_launchers(root, force=True)

    for d in (apps, desk):
        for name, body in others.items():
            assert (d / name).read_text(encoding="utf-8") == "[Desktop Entry]\n" + body, (d, name)
    assert (apps / "eli-v2-setup.desktop").is_file()
    assert not (home / ".local" / "bin" / "eli-run").exists()
    assert (home / ".local" / "bin" / "eli-v2-run").is_file()


def _run_appimage_integration(entry: Path, home: Path, appimage: Path, root: Path) -> None:
    import os
    import subprocess
    import sys
    code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('eli_entry', sys.argv[1]); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); sys.exit(m._integrate(quiet=True))")
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(home / ".local" / "share"),
           "APPIMAGE": str(appimage), "ELI_PROJECT_ROOT": str(root)}
    env.pop("ARGV0", None)
    subprocess.run([sys.executable, "-c", code, str(entry)], env=env, check=True, timeout=120,
                   cwd=entry.parents[2])


def test_appimage_integration_touches_only_its_own_entries_and_command(tmp_path):
    """The AppImage's menu set-up (eli_entry._integrate, run on first launch) deleted every
    eli*.desktop in the menu (v3's, ELI Legal's, ELI VR's) and pointed the generic ~/.local/bin/eli
    at itself; v3's wrote its entries under v2's names. Each line now writes eli-v2… / eli-v3… and
    its own eli-v2 / eli-v3 command, and removes only what is its own."""
    import re
    import sys
    import pytest
    if not sys.platform.startswith("linux"):
        pytest.skip("menu entries are a Linux AppImage thing")
    entry = Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller" / "eli_entry.py"
    line = re.search(r'^_LINE = "(v\d)"', entry.read_text(encoding="utf-8"), re.M).group(1)
    other = "v3" if line == "v2" else "v2"
    home = tmp_path / "home"
    apps, bindir, desk = home / ".local" / "share" / "applications", home / ".local" / "bin", home / "Desktop"
    for d in (apps, bindir, desk):
        d.mkdir(parents=True)
    others = {
        f"eli-{other}.desktop": f"Name=ELI {other}.0\nExec=/x/ELI_{other}-9.9.9-x86_64.AppImage\nX-ELI-Version={other[1]}.9.9\n",
        "eli-legal.desktop": "Name=ELI Legal\nExec=/opt/eli-legal/eli-legal\n",
        "eli-vr-v3.desktop": "Name=ELI VR\nExec=/x/ELI_VR-0.9.2-x86_64.AppImage\n",
        "eli-ai.desktop": "Name=ELI\nExec=/x/ELI-0.1.1-x86_64.AppImage\n",
    }
    for name, body in others.items():
        (apps / name).write_text("[Desktop Entry]\n" + body, encoding="utf-8")
    generic = bindir / "eli"
    other_shim = f'#!/usr/bin/env bash\nexec "/x/ELI_{other}-9.9.9-x86_64.AppImage" "$@"\n'
    generic.write_text(other_shim, encoding="utf-8")
    appimage = tmp_path / f"ELI_{line}-1.2.3-x86_64.AppImage"
    appimage.write_text("", encoding="utf-8")

    _run_appimage_integration(entry, home, appimage, tmp_path / "root")
    for name, body in others.items():
        assert (apps / name).read_text(encoding="utf-8") == "[Desktop Entry]\n" + body, name
    assert generic.read_text(encoding="utf-8") == other_shim  # another product's command
    assert str(appimage) in (bindir / f"eli-{line}").read_text(encoding="utf-8")
    assert str(appimage) in (apps / f"eli-{line}.desktop").read_text(encoding="utf-8")
    assert not list(desk.iterdir())  # nothing is put on the desktop that was not there

    # the generic command is removed when it is a shim this line wrote for itself
    generic.write_text(f'#!/usr/bin/env bash\nexec "/x/ELI_{line}-1.0.0-x86_64.AppImage" "$@"\n', encoding="utf-8")
    _run_appimage_integration(entry, home, appimage, tmp_path / "root")
    assert not generic.exists()
    for name, body in others.items():
        assert (apps / name).read_text(encoding="utf-8") == "[Desktop Entry]\n" + body, name
