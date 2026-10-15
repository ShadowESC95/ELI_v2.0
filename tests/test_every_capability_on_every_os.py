"""Every capability that touches the OS works on Windows, macOS and Linux.

Two halves. On Linux, tests/os_simulation.py runs each OS-facing action through ELI's real dispatch as
if on Windows and on macOS and records every program it would start (nothing is started). On the
Windows and macOS CI runners, the scripts ELI builds for that OS are compiled or parsed for real.

What this caught (2.5.17): macOS "show desktop" sent ⌘D (Finder duplicates the selected files),
"maximise" sent ⌘↑ (Finder: up a folder), "next window" ⌥Tab, and the media fallback "key code 16" (the
Y key); Windows "show desktop" sent SendKeys "#d" and "switch desktop" Ctrl+→; sound, power and mail
opened Linux programs everywhere; RUN_CMD could not run dir/echo on Windows; links ignored the
default browser on every OS.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ── simulated Windows and macOS (run on Linux) ──────────────────────────────


def _simulate(os_name: str, tmp: Path) -> dict:
    out = tmp / f"{os_name}.json"
    sb = tmp / f"sb-{os_name}"
    runtime_dir = sb / "home" / "run"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    # XDG runtime dirs are required to be private to the user.  Native desktop
    # libraries may reject or mis-handle a world-readable synthetic runtime dir.
    runtime_dir.chmod(0o700)

    # Deliberately hermetic environment: the simulator must never inherit the
    # developer's display/session bus or launch anything on the real desktop.
    env = {
        "HOME": str(sb / "home"),
        "XDG_RUNTIME_DIR": str(runtime_dir),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "ELI_OFFLINE": "1",
        "ELI_TEST_MODE": "1",
        "ELI_FORCE_CPU": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "QT_ACCESSIBILITY": "0",
        "NO_AT_BRIDGE": "1",
        "GTK_MODULES": "",
        "GTK3_MODULES": "",
        "GTK4_MODULES": "",
        "ELI_DATA_DIR": str(sb / "data"),
        "ELI_CONFIG_DIR": str(sb / "config"),
        "ELI_ARTIFACTS_DIR": str(sb / "artifacts"),
        "ELI_USER_DB": str(sb / "data" / "user.sqlite3"),
        "ELI_MEMORY_DB": str(sb / "data" / "memory.sqlite3"),
        "ELI_AGENT_DB": str(sb / "data" / "agent.sqlite3"),
    }

    simulator = [
        sys.executable,
        str(ROOT / "tests" / "os_simulation.py"),
        str(ROOT),
        os_name,
        str(out),
    ]

    # tests/conftest.py intentionally gives the pytest process a dead D-Bus
    # address so tests cannot touch the real desktop.  Some native GTK/AT-SPI
    # libraries abort (SIGABRT) rather than degrade when there is no session bus
    # at all.  Give the simulator an isolated private D-Bus instead.  This keeps
    # the real desktop unreachable while allowing native libraries to initialise.
    dbus_run = shutil.which("dbus-run-session")
    cmd = [dbus_run, "--", *simulator] if dbus_run else simulator

    cp = subprocess.run(
        cmd,
        env=env,
        check=False,
        timeout=600,
        capture_output=True,
        text=True,
        cwd=str(sb),
    )

    if cp.returncode != 0:
        raise RuntimeError(
            f"{os_name} simulator exited {cp.returncode}\n"
            f"cwd: {sb}\n"
            f"command: {' '.join(cmd)}\n"
            f"--- stdout ---\n{cp.stdout}\n"
            f"--- stderr ---\n{cp.stderr}"
        )

    if not out.is_file():
        raise RuntimeError(
            f"{os_name} simulator exited 0 but did not create {out}\n"
            f"--- stdout ---\n{cp.stdout}\n"
            f"--- stderr ---\n{cp.stderr}"
        )

    rows = json.loads(out.read_text(encoding="utf-8"))
    return {(r["action"], json.dumps(r["args"], sort_keys=True)): r for r in rows}


@pytest.fixture(scope="module")
def simulated(tmp_path_factory):
    if not sys.platform.startswith("linux"):
        pytest.skip("the OS simulation runs on the Linux runner")
    tmp = tmp_path_factory.mktemp("os_simulation")
    return {name: _simulate(name, tmp) for name in ("windows", "macos")}


def _calls(sim: dict, action: str, **args) -> str:
    return "\n".join(sim[(action, json.dumps(args, sort_keys=True))]["calls"])


def test_no_linux_program_is_started_on_windows_or_macos(simulated):
    for os_name, rows in simulated.items():
        bad = {f"{r['action']} {r['args']}": r["linux_only"] for r in rows.values() if r["linux_only"]}
        assert not bad, f"{os_name} would start Linux programs: {bad}"


def test_macos_window_commands_are_macos_own(simulated):
    mac = simulated["macos"]
    every = "\n".join("\n".join(r["calls"]) for r in mac.values())
    for wrong in ('keystroke "d" using {command down}', "key code 126 using {command down}",
                  "using {option down}", "key code 16", "key code 17", "key code 18"):
        assert wrong not in every, wrong
    assert "keystroke tab using {command down}" in _calls(mac, "NEXT_WINDOW")
    assert "AXZoomButton" in _calls(mac, "MAXIMISE_WINDOW")
    assert "set visible of" in _calls(mac, "MINIMISE_ALL")
    assert "AXMinimized" in _calls(mac, "RESTORE_WINDOWS")
    assert "bounds of window of desktop" in _calls(mac, "TILE_WINDOWS")
    assert "-l JavaScript" in _calls(mac, "PAUSE_MEDIA")  # a real media key when no player app runs


def test_windows_window_commands_are_windows_own(simulated):
    win = simulated["windows"]
    assert "MinimizeAll()" in _calls(win, "MINIMISE_ALL")
    assert "UndoMinimizeALL()" in _calls(win, "RESTORE_WINDOWS")
    assert "TileVertically()" in _calls(win, "TILE_WINDOWS")
    assert "@(17,91,39)" in _calls(win, "SWITCH_WORKSPACE", direction="right")  # Ctrl+Win+→
    every = "\n".join("\n".join(r["calls"]) for r in win.values())
    assert "SendWait('#d')" not in every and "SendWait('^{Right}')" not in every


def test_settings_mail_and_links_use_the_os_own_handlers(simulated):
    win, mac = simulated["windows"], simulated["macos"]
    assert "ms-settings:sound" in _calls(win, "OPEN_AUDIO_SETTINGS")
    assert "ms-settings:powersleep" in _calls(win, "OPEN_POWER_SETTINGS")
    assert "x-apple.systempreferences:com.apple.preference.sound" in _calls(mac, "OPEN_AUDIO_SETTINGS")
    assert "x-apple.systempreferences:com.apple.preference.battery" in _calls(mac, "OPEN_POWER_SETTINGS")
    assert "mail.google.com" not in _calls(win, "OPEN_COMMUNICATION_HUB") + _calls(mac, "OPEN_COMMUNICATION_HUB")
    assert _calls(win, "OPEN_URL", url="https://example.org").splitlines()[0] == "https://example.org"
    assert _calls(mac, "OPEN_BROWSER", url="https://example.org").splitlines()[0] == "open https://example.org"


def test_windows_runs_cmd_builtins_inside_cmd(simulated):
    win = simulated["windows"]
    assert _calls(win, "RUN_CMD", cmd="echo hi").splitlines()[0] == "cmd.exe /d /s /c echo hi"
    assert _calls(simulated["macos"], "SHELL_EXEC", cmd="echo hi").splitlines()[0] == "/bin/sh -c echo hi"


# ── closing an app by the program ELI opened ────────────────────────────────


def test_the_program_of_an_app_on_every_os():
    from eli.system.portable_app_control import AppCandidate, app_program
    assert app_program(AppCandidate("Settings", command=["gnome-control-center"])) == "gnome-control-center"
    assert app_program(AppCandidate("Spotify", command=["/usr/bin/flatpak", "run", "--branch=stable",
                                                        "--command=spotify", "com.spotify.Client", "@@u"])) == "spotify"
    assert app_program(AppCandidate("Firefox", command=["/snap/bin/firefox"])) == "firefox"
    assert app_program(AppCandidate("Editor", command=["env", "GDK_BACKEND=x11", "gedit"])) == "gedit"
    assert app_program(AppCandidate("VS Code", app_id=r"C:\Users\x\AppData\Local\Programs\Microsoft VS Code\Code.exe")) == "Code.exe"
    assert app_program(AppCandidate("Calculator", app_id="Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")) == "Microsoft.WindowsCalculator"
    assert app_program(AppCandidate("Spotify", command=["open", "-a", "Spotify"])) == ""


@pytest.mark.skipif(not shutil.which("grep"), reason="needs grep -E, as pgrep reads the pattern")
def test_closing_settings_never_matches_gsd_xsettings():
    """"close settings" was refused live: pkill by the word "settings" also matched gsd-xsettings."""
    from eli.system.portable_app_control import _posix_program_pattern
    pattern = _posix_program_pattern("gnome-control-center")
    lines = ["/usr/bin/gnome-control-center", "gnome-control-center --overview",
             "/usr/libexec/gsd-xsettings", "/usr/libexec/gnome-control-center-search-provider",
             "playerctl -p gnome-control-center"]
    hit = subprocess.run(["grep", "-E", pattern], input="\n".join(lines), capture_output=True, text=True).stdout.split("\n")
    assert [h for h in hit if h] == lines[:2]


def test_closing_an_app_uses_its_program_when_no_window_tool_can(monkeypatch):
    from eli.system import portable_app_control as pac, process_guard
    seen = []
    monkeypatch.setattr(pac, "_system", lambda: "linux")
    monkeypatch.setattr(pac, "resolve_app", lambda q: pac.AppCandidate("Settings", command=["gnome-control-center"],
                                                                      desktop_id="org.gnome.Settings", source="linux-desktop"))
    monkeypatch.setattr(pac.shutil, "which", lambda name: None)
    monkeypatch.setattr(process_guard, "safe_pkill",
                        lambda pattern, full_cmdline=False: seen.append((pattern, full_cmdline)) or
                        {"ok": True, "killed": 1, "plan": {"pids": [1]}})
    r = pac.close_app("settings")
    assert r["ok"] and seen == [(pac._posix_program_pattern("gnome-control-center"), True)]


# ── the real Windows and macOS (their CI runners) ───────────────────────────


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("osacompile"), reason="macOS only")
def test_every_macos_script_compiles(tmp_path):
    from eli.integrations.media import system_session
    from eli.system import portable_app_control as pac
    from eli.utils import platform_compat as pc
    scripts = [("AppleScript", s) for s in pac._MACOS_SCRIPTS.values()]
    quoted_note = pc._applescript_text('a "quoted" note')
    scripts.append(("AppleScript", f'display notification "{quoted_note}" with title "ELI"'))
    scripts += [("JavaScript", system_session.macos_media_key_script(k)) for k in ("play-pause", "next", "previous")]
    for i, (lang, script) in enumerate(scripts):
        cp = subprocess.run(["osacompile", "-l", lang, "-o", str(tmp_path / f"s{i}.scpt"), "-e", script],
                            capture_output=True, text=True)
        assert cp.returncode == 0, (script, cp.stderr)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_every_windows_script_parses_and_the_media_session_answers():
    from eli.integrations.media import system_session
    from eli.utils import platform_compat as pc
    scripts = [system_session.windows_script(w) for w in system_session._WIN_BODY]
    scripts += [pc.WINDOWS_TOAST_SCRIPT, pc.windows_keys_script(0x11, 0x5B, 0x27)]
    for script in scripts:
        check = ("$e = $null; $null = [System.Management.Automation.Language.Parser]::ParseInput($env:ELI_PS, "
                 "[ref]$null, [ref]$e); if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }")
        cp = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", check],
                            env=dict(os.environ, ELI_PS=script), capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0, (script[:200], cp.stdout, cp.stderr)
    # the WinRT media session loads and answers on a real Windows (nothing is playing on a runner)
    now = system_session.info()
    assert now is None or isinstance(now, dict)
    assert re.match(r"^(ms-settings:|code\.cmd)", pc.WINDOWS_APP_CANDIDATES["sound settings"][0])
