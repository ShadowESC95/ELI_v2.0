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
    assert "eli-run" in desk
    assert 'Exec="' in desk and " gui" in desk

    pointer = (home / ".local" / "share" / "ELI_v2" / "runtime" / "install_root").read_text(
        encoding="utf-8"
    ).strip()
    assert pointer == str(root.resolve())

    guard = home / ".local" / "bin" / "eli-run"
    assert guard.is_file()
    gtxt = guard.read_text(encoding="utf-8")
    assert "install_root" in gtxt
    assert "linux-portable" not in gtxt


def test_stale_path_line_detected():
    stale = (
        "[Desktop Entry]\nName=ELI v2.0\n"
        'Exec=/home/jess/.local/bin/eli-run "/home/jess/Downloads/ELI_v2-2.4.29-linux-portable" gui\n'
        "Path=/home/jess/Downloads/ELI_v2-2.4.29-linux-portable\n"
    )
    assert dl._desktop_is_stale(stale, Path("/home/jess/.local/bin/eli-run"), "2.4.34")


def test_ensure_rewrites_desktop_copy(tmp_path, monkeypatch):
    home = tmp_path / "home"
    desk = home / "Desktop"
    desk.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(dl, "product_line", lambda: "v2")

    root = tmp_path / "ELI_v2-2.4.34-linux-portable"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "eli-v2.0"\nversion = "2.4.34"\n', encoding="utf-8"
    )

    # Pretend user dragged an old icon to Desktop
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
    assert "eli-run" in refreshed
