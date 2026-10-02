"""Live bug (2026-10-02): a stale `alias eli=...` in ~/.bashrc pointed at an old
portable snapshot. install_eli_command.sh's own `command -v` check never caught
it — aliases don't exist outside an interactive shell, so a script-context
`command -v` can't see them. The user's install LOOKED successful every time,
while the alias silently won in every real terminal.

Fixed: the installer now greps common shell rc files directly for a
conflicting `alias <name>=` and warns.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_eli_command.sh"


def _run_installer(tmp_path, rc_content=None):
    home = tmp_path / "home"
    home.mkdir()
    if rc_content is not None:
        (home / ".bashrc").write_text(rc_content, encoding="utf-8")
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["ELI_BIN_DIR"] = str(home / ".local" / "bin")
    return subprocess.run(
        ["bash", str(SCRIPT), "--force"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )


def test_warns_when_an_rc_alias_points_elsewhere(tmp_path):
    cp = _run_installer(tmp_path, rc_content="alias eli='/some/old/stale/path/eli.sh'\n")
    assert "defines an 'alias eli=' NOT pointing at" in cp.stderr
    assert "/some/old/stale/path/eli.sh" in cp.stderr


def test_no_warning_when_rc_has_no_alias(tmp_path):
    cp = _run_installer(tmp_path, rc_content="# nothing relevant here\n")
    assert "alias eli=" not in cp.stderr


def test_no_warning_when_alias_already_points_at_the_fresh_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    target = home / ".local" / "bin" / "eli"
    (home / ".bashrc").write_text(f"alias eli='{target}'\n", encoding="utf-8")
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["ELI_BIN_DIR"] = str(home / ".local" / "bin")
    cp = subprocess.run(
        ["bash", str(SCRIPT), "--force"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert "alias eli=" not in cp.stderr
