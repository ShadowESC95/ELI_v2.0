"""Behaviour locks for process-kill safety in CLOSE_APP.

Every case here is a defect observed in a live 2.3.15 session:

  * "close file" logged the user out of their desktop. CLOSE_APP fell through
    to a bare `pkill -f <name>` loop; `-f` matches the *full command line* of
    every process as a regex, and `dbus-daemon --session ... --nopidfile`
    contains "file". On the reporting machine that pattern resolved to three
    dbus-daemon processes (system bus, session bus, at-spi bus) plus dnsmasq,
    rpcd_lsad and every Spotify process — eighteen in total.
  * The same call then reported success, because `pkill` exits 0 when it
    signals anything at all. ELI told the user twice that it had "closed the
    files via pkill" and had not logged them out.
  * `portable_app_control.close_app(force=True)` treated pkill's exit status 1
    ("nothing matched") as success too, so a complete no-op reported a
    force-close that never happened.

The guard's rule is that a kill is verified, not merely name-checked: the
pattern is dry-run through pgrep and every process it resolves to must be an
ordinary user application before a single signal is sent.
"""
import os
import re
import shutil
from pathlib import Path

import pytest

from eli.system import process_guard as pg


# ── the exact pattern that ended the session ────────────────────────────────
@pytest.mark.parametrize("pattern", [
    "file", "files", "folder", "home", "app", "window", "session",
    "python", "python3", "bash", "system", "systemd", "daemon", "eli",
])
def test_generic_patterns_never_match_command_lines(pattern):
    """A generic word inside a command line identifies infrastructure, not an app."""
    plan = pg.check_kill_pattern(pattern, full_cmdline=True)
    assert plan.allowed is False, f"{pattern!r} would be killed by command line: {plan.reason}"
    assert plan.pids == []


def test_empty_and_tiny_targets_are_refused():
    for pattern in ("", "   ", "x", "ab"):
        plan = pg.check_kill_pattern(pattern, full_cmdline=True)
        assert plan.allowed is False, f"{pattern!r} was allowed"


# ── the processes that must never be signalled ─────────────────────────────
@pytest.mark.parametrize("name", [
    "dbus-daemon", "dbus-broker", "systemd", "systemd-logind", "init",
    "gnome-shell", "gnome-session-binary", "gdm3", "Xorg", "Xwayland",
    "mutter", "kwin_x11", "plasmashell", "sshd", "polkitd",
    "pipewire", "wireplumber", "pulseaudio", "gvfsd", "gvfsd-metadata",
    "gsd-housekeeping", "xdg-desktop-portal", "kworker/0:1",
    "winlogon.exe", "explorer.exe", "lsass.exe",
])
def test_session_critical_processes_are_protected(name):
    assert pg.is_protected_process(name) is True, f"{name} is not protected"


def test_unidentifiable_process_is_treated_as_protected():
    """Failing to name a process must fail towards refusing, not towards killing."""
    assert pg.is_protected_process("") is True
    assert pg.is_protected_process(None) is True


def test_ordinary_applications_are_not_blanket_protected():
    for name in ("firefox", "spotify", "nautilus", "code", "gimp", "vlc"):
        assert pg.is_protected_process(name) is False, f"{name} wrongly protected"


# ── a refused plan must send no signal at all ──────────────────────────────
def test_refused_kill_signals_nothing():
    res = pg.safe_pkill("file", full_cmdline=True)
    assert res["ok"] is False
    assert res["killed"] == 0
    assert res["pids"] == []
    assert res["plan"]["allowed"] is False
    assert res["reason"]


@pytest.mark.skipif(os.name != "posix", reason="pgrep/pkill path is POSIX-only")
@pytest.mark.skipif(shutil.which("pgrep") is None, reason="pgrep not installed")
def test_live_dry_run_blocks_patterns_resolving_to_protected_processes():
    """The verification, not the word list, is what has to hold.

    'dbus' is not in the generic list, so this case can only be refused by
    the dry-run actually resolving it to protected processes.
    """
    assert "dbus" not in pg.GENERIC_KILL_PATTERNS
    plan = pg.check_kill_pattern("dbus-daemon", full_cmdline=False)
    if not plan.pids and not plan.blocked:
        pytest.skip("no dbus-daemon running on this machine")
    assert plan.allowed is False, f"dbus-daemon kill was allowed: {plan.reason}"
    assert plan.blocked, "dbus-daemon should have been reported as blocked"


def test_fanout_cap_is_enforced_in_policy():
    assert pg.MAX_KILL_FANOUT <= 20, "a single app is never dozens of processes"


# ── structural lock: the raw kill loop must not come back ──────────────────
def _close_app_branch() -> str:
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    start = src.index('if a == "CLOSE_APP":')
    end = src.index('if a == "ANALYZE_IMAGE":', start)
    return src[start:end]


def test_executor_close_app_has_no_unguarded_kill():
    branch = _close_app_branch()
    assert "safe_pkill" in branch, "CLOSE_APP no longer routes through the guard"
    for forbidden in ('["pkill", "-f", name]', '["pkill", name]', '["killall", name]'):
        assert forbidden not in branch, f"unguarded kill restored: {forbidden}"


def test_portable_app_control_force_close_is_guarded():
    src = Path("eli/system/portable_app_control.py").read_text(encoding="utf-8")
    assert "safe_pkill" in src, "force-close no longer routes through the guard"
    assert not re.search(r'_run\(\["pkill"', src), "unguarded pkill restored in close_app"


def test_close_app_without_a_target_asks_rather_than_guessing():
    from eli.execution import executor_enhanced as ex
    res = ex.execute("CLOSE_APP", {})
    assert isinstance(res, dict)
    assert res.get("ok") is False
    assert "specify" in str(res.get("content", "")).lower()


# ── the guard must protect every platform, not just the one it was written on ──
@pytest.mark.parametrize("name", [
    # macOS: killing any of these ends the session or the window server
    "WindowServer", "loginwindow", "SystemUIServer", "Dock", "Finder",
    "coreaudiod", "securityd", "opendirectoryd", "launchd", "configd",
    "kernel_task", "diskarbitrationd",
])
def test_macos_session_processes_are_protected(name):
    assert pg.is_protected_process(name) is True, f"{name} unprotected on macOS"


def test_macos_full_paths_resolve_to_the_protected_name():
    """`ps -o comm=` returns a full path on macOS, not a bare name."""
    full = ("/System/Library/PrivateFrameworks/SkyLight.framework/"
            "Resources/WindowServer")
    assert pg.is_protected_process(full) is True


@pytest.mark.parametrize("name", [
    "winlogon.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "explorer.exe", "dwm.exe", "smss.exe", "svchost.exe", "fontdrvhost.exe",
    "audiodg.exe", "spoolsv.exe",
])
def test_windows_session_processes_are_protected(name):
    assert pg.is_protected_process(name) is True, f"{name} unprotected on Windows"


def test_windows_has_a_verified_kill_path():
    """Windows had no force-close path at all: pkill is POSIX-only, so
    'kill <app>' silently did nothing there."""
    assert hasattr(pg, "_check_kill_pattern_windows")
    assert hasattr(pg, "_windows_processes")
    src = Path("eli/system/process_guard.py").read_text(encoding="utf-8")
    assert "taskkill" in src, "no Windows kill implementation"
    # The same rules must apply, not a weaker set.
    win = src[src.index("def _check_kill_pattern_windows"):src.index("def check_kill_pattern")]
    for rule in ("is_protected_process", "_own_pids", "MAX_KILL_FANOUT"):
        assert rule in win, f"Windows path skips {rule}"


def test_windows_kill_is_not_forced():
    """/F would kill an app mid-write; the POSIX path sends SIGTERM, so the
    Windows path must be equally polite."""
    src = Path("eli/system/process_guard.py").read_text(encoding="utf-8")
    block = src[src.index('if os.name == "nt":', src.index("def safe_pkill")):]
    assert '"/F"' not in block and "'/F'" not in block, "Windows kill uses /F"
