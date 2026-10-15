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
