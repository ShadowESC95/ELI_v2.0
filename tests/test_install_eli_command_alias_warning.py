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


def test_the_help_names_what_the_installed_command_runs(tmp_path):
    """The help said the command runs scripts/eli_startup.sh; the launcher it writes runs eli.sh."""
    cp = _run_installer(tmp_path)
    launcher = (tmp_path / "home" / ".local" / "bin" / "eli-v2").read_text(encoding="utf-8")
    runs = [line.split()[1] for line in launcher.splitlines() if line.startswith("exec ")]
    assert cp.returncode == 0 and runs == [f'"{ROOT}/eli.sh"']
    shown = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=30).stdout
    said = shown.split("The installed command runs:", 1)[1].split()[0]
    assert said == f"{ROOT}/eli.sh", shown


def test_warns_when_an_rc_alias_points_elsewhere(tmp_path):
    cp = _run_installer(tmp_path, rc_content="alias eli-v2='/some/old/stale/path/eli.sh'\n")
    assert "defines an 'alias eli-v2=' NOT pointing at" in cp.stderr
    assert "/some/old/stale/path/eli.sh" in cp.stderr


def test_no_warning_when_rc_has_no_alias(tmp_path):
    cp = _run_installer(tmp_path, rc_content="# nothing relevant here\n")
    assert "alias eli-v2=" not in cp.stderr


def test_no_warning_when_alias_already_points_at_the_fresh_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    target = home / ".local" / "bin" / "eli-v2"  # v2's own command name
    (home / ".bashrc").write_text(f"alias eli-v2='{target}'\n", encoding="utf-8")
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["ELI_BIN_DIR"] = str(home / ".local" / "bin")
    cp = subprocess.run(
        ["bash", str(SCRIPT), "--force"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert "alias eli-v2=" not in cp.stderr


# ── scripts/eli_uninstall.sh takes away what the install added, and only that ─────────────────
def _install_copy(tmp_path, name):
    """A folder holding copies of the scripts that add and remove ELI's commands, as an install has."""
    import shutil
    root = tmp_path / name
    (root / "scripts").mkdir(parents=True)
    (root / "artifacts").mkdir()
    (root / "artifacts" / "memory.txt").write_text("the user's data\n", encoding="utf-8")
    for script in ("eli_uninstall.sh", "install_eli_command.sh", "fix_eli_shell_env.sh"):
        shutil.copy(ROOT / "scripts" / script, root / "scripts" / script)
    return root


def _env_for(home):
    env = {k: v for k, v in os.environ.items() if k not in ("ELI_BIN_DIR", "ELI_COMMAND_NAME")}
    env.update(HOME=str(home), XDG_DATA_HOME=str(home / ".local" / "share"))
    return env


def _set_up(root, home):
    """What install.sh's shell step and the menu launchers leave: the commands, the aliases, the pointer."""
    subprocess.run(["bash", str(root / "scripts" / "fix_eli_shell_env.sh"), "--yes"], env=_env_for(home),
                   capture_output=True, text=True, timeout=60, check=True)
    pointer = home / ".local" / "share" / "ELI_v2" / "runtime" / "install_root"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(f"{root}\n", encoding="utf-8")
    return pointer


def _uninstall(root, home, *args):
    # by its full path, as the menu's Uninstall entry starts it
    return subprocess.run(["bash", str(root / "scripts" / "eli_uninstall.sh"), *args], env=_env_for(home),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)


def test_uninstall_removes_the_commands_aliases_and_pointer_this_install_added(tmp_path):
    """The uninstaller left ~/.local/bin/eli-v2 and eli2, the alias block in the shell files and the
    install pointer behind; it also stopped itself (its own command line matched the processes it
    stops), and --yes deleted the whole folder although it is documented to keep it."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("export EDITOR=vi\n", encoding="utf-8")
    (home / ".profile").write_text("umask 022\n\nexport LANG=C.UTF-8\n", encoding="utf-8")
    root = _install_copy(tmp_path, "ELI_v2-portable")
    pointer = _set_up(root, home)
    bin_dir = home / ".local" / "bin"
    assert (bin_dir / "eli-v2").is_file() and (bin_dir / "eli2").is_file()
    assert "ELI v2 launcher" in (home / ".bashrc").read_text(encoding="utf-8")

    done = _uninstall(root, home, "--yes")
    assert done.returncode == 0 and "Done." in done.stdout, (done.returncode, done.stdout, done.stderr)
    assert not (bin_dir / "eli-v2").exists() and not (bin_dir / "eli2").exists()
    assert (home / ".bashrc").read_text(encoding="utf-8") == "export EDITOR=vi\n"
    assert (home / ".profile").read_text(encoding="utf-8") == "umask 022\n\nexport LANG=C.UTF-8\n"
    assert not pointer.exists()
    assert (root / "artifacts" / "memory.txt").is_file(), "--yes deleted the install folder"


def test_uninstall_leaves_what_another_install_added(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("export EDITOR=vi\n", encoding="utf-8")
    mine, theirs = _install_copy(tmp_path, "mine"), _install_copy(tmp_path, "theirs")
    pointer = _set_up(theirs, home)
    before = {p: p.read_text(encoding="utf-8") for p in
              (home / ".local" / "bin" / "eli-v2", home / ".local" / "bin" / "eli2", home / ".bashrc", pointer)}

    done = _uninstall(mine, home, "--yes")
    assert done.returncode == 0 and "Done." in done.stdout, done.stdout + done.stderr
    assert {p: p.read_text(encoding="utf-8") for p in before} == before

    gone = _uninstall(mine, home, "--purge")
    assert gone.returncode == 0 and not mine.exists() and theirs.is_dir()


def _not_comments(text: str, comment: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(comment))


def test_the_windows_uninstallers_take_away_the_launcher_and_pointer_this_install_added(monkeypatch):
    """scripts/uninstall.ps1 and both Inno uninstallers left %LOCALAPPDATA%\\ELI_v2\\eli-run.cmd and the
    install pointer behind (and the shortcuts that start it). Every v2 install writes the same ones, so
    they go when the pointer names this install, as in eli_uninstall.sh, and stay for the install it
    names otherwise; a shortcut goes only when it starts that launcher or a file in this folder (v3 uses
    some of the same names), and a folder only when that leaves it empty (the app's data is in ELI_v2)."""
    import eli.runtime.desktop_launchers as dl
    monkeypatch.setattr(dl, "product_line", lambda: "v2")
    labels = [f"{label}.lnk" for label, _action in dl.windows_shortcuts()]
    assert labels and all("v3" not in label for label in labels)

    ps = _not_comments((ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8-sig"), "#")
    assert 'Join-Path $env:LOCALAPPDATA "ELI_v2"' in ps
    assert '$Launcher = Join-Path $Share "eli-run.cmd"' in ps and '$Pointer = Join-Path $Share "runtime\\install_root"' in ps
    for label in labels:
        assert f'"{label}"' in ps, label
    read = ps.index("Get-Content -LiteralPath $Pointer -Encoding UTF8")
    mine = ps.index("$Mine = ")
    assert read < mine < ps.index("Remove-Item") and "(Get-FullPath $Root)" in ps[mine:mine + 200]
    links = ps[ps.index("foreach ($n in"):ps.index("if ($Mine) {")]
    assert "CreateShortcut($lnk).TargetPath" in links and "(Get-FullPath $Launcher)" in links and "$Inside" in links
    ours = ps[ps.index("if ($Mine) {"):]
    ours = ours[:ours.index("\n} else {")]
    assert "@($Launcher, $Pointer)" in ours and "[System.IO.Directory]::Delete($d, $false)" in ours
    assert ps.count("-Recurse") == 1, "only the folder the user agreed to delete goes recursively"

    include = ROOT / "packaging" / "windows" / "eli_launchers.iss"
    pas = _not_comments(include.read_text(encoding="utf-8"), "{")
    body = pas[pas.index("procedure RemoveEliLaunchers(const Root: String);"):]
    assert "LoadStringsFromFile(Pointer, Lines)" in body and "EliSamePath(Pointed, Root)" in body
    for label in labels:
        assert f"'{label}'" in body, label
    assert "EliSamePath(Target, Launcher)" in body and "EliInside(Target, Root)" in body
    assert "DeleteFile(Launcher)" in body and "DeleteFile(Pointer)" in body and "DelTree" not in body
    for name, root in (("installer.iss", "ExpandConstant('{localappdata}\\ELI_v2')"),
                       ("ELI_Setup.iss", "ExpandConstant('{app}')")):
        iss = (ROOT / "packaging" / "windows" / name).read_text(encoding="utf-8")
        code = iss[iss.index("[Code]"):]
        assert '#include "eli_launchers.iss"' in code, name
        step = code[code.index("procedure CurUninstallStepChanged"):]
        assert "usPostUninstall" in step and f"RemoveEliLaunchers({root})" in step, name
        assert b"\r\n" not in (ROOT / "packaging" / "windows" / name).read_bytes(), name
    assert b"\r\n" not in include.read_bytes()


def test_the_windows_uninstaller_does_not_stop_itself():
    """uninstall.ps1 stops every process whose command line names the install folder, and its own
    (powershell -File <folder>\\scripts\\uninstall.ps1) does: it ended before removing the shortcuts."""
    text = (ROOT / "scripts" / "uninstall.ps1").read_text(encoding="utf-8-sig")
    stop = text[text.index("Get-CimInstance Win32_Process"):text.index("Stop-Process")]
    assert "$cur = $PID" in stop and "ParentProcessId" in stop
    assert "($own -notcontains $_.ProcessId) -and (" in stop
