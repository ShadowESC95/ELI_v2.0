from __future__ import annotations

import difflib
import os
import platform
import re
import shlex
import shutil
import subprocess
import threading
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)


@dataclass
class AppCandidate:
    name: str
    command: Optional[list[str]] = None
    desktop_id: Optional[str] = None
    package: Optional[str] = None
    app_id: Optional[str] = None
    source: str = "unknown"


def _system() -> str:
    if os.environ.get("TERMUX_VERSION") or "com.termux" in os.environ.get("PREFIX", "").lower():
        return "android"
    return platform.system().lower()


def _run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


# Launched children we deliberately do not wait for. Dropping the Popen object
# while its child is alive is what produced "ResourceWarning: subprocess <pid>
# is still running" on every app launch -- and, worse, left the finished child
# unreaped as a zombie because nobody ever called wait(). Holding the handle
# until the process actually exits fixes both: the warning is legitimate (we
# WERE discarding a live handle) and the reap is what stops the zombie.
_LAUNCHED: list = []
_LAUNCH_LOCK = threading.Lock()
# An app launcher is a handful of processes; this cap only bounds a pathological
# loop, and reaping runs first so a normal session never approaches it.
_MAX_TRACKED_LAUNCHES = 64


def _reap_launched() -> int:
    """Drop handles whose child has exited, reaping the zombie in the process.

    poll() collects the exit status, which is the call that lets the kernel
    release the process-table entry. Returns how many are still running.
    """
    with _LAUNCH_LOCK:
        alive = []
        for proc in _LAUNCHED:
            try:
                if proc.poll() is None:
                    alive.append(proc)
            except Exception:
                continue          # handle already invalid; drop it
        _LAUNCHED[:] = alive
        if len(_LAUNCHED) > _MAX_TRACKED_LAUNCHES:
            # Keep the newest; the oldest are long-lived apps (a browser, an
            # editor) that will be reaped when they exit or when ELI does.
            del _LAUNCHED[:-_MAX_TRACKED_LAUNCHES]
        return len(_LAUNCHED)


def _popen(args: list[str]) -> bool:
    try:
        _reap_launched()
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        with _LAUNCH_LOCK:
            _LAUNCHED.append(proc)
        return True
    except Exception:
        log.debug("app launch failed: %s", args, exc_info=True)
        return False


def _result(ok: bool, action: str, text: str, **extra) -> dict:
    out = {"ok": bool(ok), "action": action, "content": text, "response": text}
    if not ok:
        out["error"] = text
    out.update(extra)
    return out


def _clean_exec_field(exec_line: str) -> list[str]:
    cleaned = re.sub(r"\s+%[A-Za-z]", "", exec_line or "").strip()
    if not cleaned:
        return []
    try:
        return shlex.split(cleaned)
    except Exception:
        return cleaned.split()


def _linux_desktop_dirs() -> list[Path]:
    dirs = [Path.home() / ".local/share/applications"]
    for base in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if base:
            dirs.append(Path(base) / "applications")
    return dirs


def _iter_linux_apps() -> Iterable[AppCandidate]:
    seen = set()
    for directory in _linux_desktop_dirs():
        if not directory.exists():
            continue
        for path in directory.glob("*.desktop"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            name = None
            exec_line = None
            hidden = False
            no_display = False

            for line in text.splitlines():
                if line.startswith("Name=") and name is None:
                    name = line.split("=", 1)[1].strip()
                elif line.startswith("Exec=") and exec_line is None:
                    exec_line = line.split("=", 1)[1].strip()
                elif line.startswith("Hidden="):
                    hidden = line.split("=", 1)[1].strip().lower() == "true"
                elif line.startswith("NoDisplay="):
                    no_display = line.split("=", 1)[1].strip().lower() == "true"

            if not name or hidden or no_display:
                continue

            key = name.lower()
            if key in seen:
                continue
            seen.add(key)

            yield AppCandidate(
                name=name,
                command=_clean_exec_field(exec_line or ""),
                desktop_id=path.stem,
                source="linux-desktop",
            )


def _iter_macos_apps() -> Iterable[AppCandidate]:
    for root in (Path("/Applications"), Path.home() / "Applications"):
        if not root.exists():
            continue
        for path in root.glob("*.app"):
            yield AppCandidate(name=path.stem, command=["open", "-a", path.stem], source="macos-app")


def _iter_windows_apps() -> Iterable[AppCandidate]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return
    cp = _run([powershell, "-NoProfile", "-Command", "Get-StartApps | ForEach-Object { $_.Name + '||' + $_.AppID }"])
    for line in cp.stdout.splitlines():
        if "||" not in line:
            continue
        name, app_id = line.split("||", 1)
        name = name.strip()
        app_id = app_id.strip()
        if name:
            yield AppCandidate(name=name, app_id=app_id, source="windows-startapps")


def _iter_android_apps() -> Iterable[AppCandidate]:
    pm = shutil.which("pm")
    if not pm:
        return
    cp = _run([pm, "list", "packages"])
    for line in cp.stdout.splitlines():
        if line.startswith("package:"):
            package = line.split(":", 1)[1].strip()
            label = package.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ")
            yield AppCandidate(name=label, package=package, source="android-package")


def iter_installed_apps() -> list[AppCandidate]:
    sysname = _system()
    if sysname == "linux":
        return list(_iter_linux_apps())
    if sysname == "darwin":
        return list(_iter_macos_apps())
    if sysname == "windows":
        return list(_iter_windows_apps())
    if sysname == "android":
        return list(_iter_android_apps())
    return []


def resolve_app(query: str) -> AppCandidate:
    raw = str(query or "").strip()
    if not raw:
        return AppCandidate(name="")
    apps = iter_installed_apps()
    if not apps:
        return AppCandidate(name=raw)

    q = raw.lower()
    for app in apps:
        if app.name.lower() == q:
            return app

    contains = [app for app in apps if q in app.name.lower()]
    if contains:
        contains.sort(key=lambda app: len(app.name))
        return contains[0]

    names = [app.name for app in apps]
    close = difflib.get_close_matches(raw, names, n=1, cutoff=0.72)
    if close:
        for app in apps:
            if app.name == close[0]:
                return app

    return AppCandidate(name=raw)


def open_app(name: str) -> dict:
    target = resolve_app(name)
    sysname = _system()
    if not target.name:
        return _result(False, "OPEN_APP", "No app name supplied.")

    if sysname == "linux":
        launcher = shutil.which("gtk-launch")
        if launcher and target.desktop_id and _popen([launcher, target.desktop_id]):
            return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)
        if target.command and shutil.which(target.command[0]) and _popen(target.command):
            return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)
        exe = shutil.which(target.name)
        if exe and _popen([exe]):
            return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    if sysname == "darwin":
        opener = shutil.which("open")
        if opener and _popen([opener, "-a", target.name]):
            return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    if sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            if target.app_id:
                cmd = f'Start-Process "shell:AppsFolder\\{target.app_id}"'
            else:
                safe = target.name.replace("'", "''")
                cmd = f"Start-Process -FilePath '{safe}'"
            cp = _run([powershell, "-NoProfile", "-Command", cmd])
            if cp.returncode == 0:
                return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    if sysname == "android":
        monkey = shutil.which("monkey")
        if monkey and target.package:
            cp = _run([monkey, "-p", target.package, "1"])
            if cp.returncode == 0:
                return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    return _result(False, "OPEN_APP", f"Could not open app: {name}", resolved=target.__dict__)


def close_app(name: str, force: bool = False) -> dict:
    target = resolve_app(name)
    sysname = _system()
    if not target.name:
        return _result(False, "CLOSE_APP", "No app name supplied.")

    if sysname == "linux":
        wmctrl = shutil.which("wmctrl")
        if wmctrl:
            cp = _run([wmctrl, "-lx"])
            q = target.name.lower()
            for line in cp.stdout.splitlines():
                if q in line.lower():
                    win_id = line.split(None, 1)[0]
                    rc = _run([wmctrl, "-i", "-c", win_id]).returncode
                    if rc == 0:
                        return _result(True, "CLOSE_APP", f"Closed app/window: {target.name}", resolved=target.__dict__)
        if force:
            # `pkill -f` matches the full command line of every process as a
            # regex, so a short target signals unrelated infrastructure — a
            # "file" target matches `dbus-daemon --session ... --nopidfile`
            # and ends the login session. The guard dry-runs the pattern and
            # only signals processes it has verified are ordinary apps.
            # The old code also treated pkill's "nothing matched" exit status
            # as success, so a no-op reported a force-close that never happened.
            from eli.system.process_guard import safe_pkill

            res = safe_pkill(target.name, full_cmdline=True)
            if res.get("ok"):
                return _result(True, "CLOSE_APP",
                               f"Force-closed {target.name} ({res.get('killed')} process(es)).",
                               resolved=target.__dict__, kill_plan=res.get("plan"))
            return _result(False, "CLOSE_APP",
                           f"Did not force-close {target.name}: {res.get('reason')}",
                           resolved=target.__dict__, kill_plan=res.get("plan"))

    if sysname == "darwin":
        osascript = shutil.which("osascript")
        if osascript:
            cp = _run([osascript, "-e", f'tell application "{target.name}" to quit'])
            if cp.returncode == 0:
                return _result(True, "CLOSE_APP", f"Closed app: {target.name}", resolved=target.__dict__)

    if sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            safe = target.name.replace("'", "''")
            cmd = "$q='" + safe + "'; $p=Get-Process | Where-Object { $_.MainWindowTitle -like \"*$q*\" -or $_.ProcessName -like \"*$q*\" }; if($p){ $p | ForEach-Object { $_.CloseMainWindow() | Out-Null }; exit 0 } else { exit 2 }"
            cp = _run([powershell, "-NoProfile", "-Command", cmd])
            if cp.returncode == 0:
                return _result(True, "CLOSE_APP", f"Closed app/window: {target.name}", resolved=target.__dict__)

    if sysname == "android":
        am = shutil.which("am")
        if am and target.package:
            cp = _run([am, "force-stop", target.package])
            if cp.returncode == 0:
                return _result(True, "CLOSE_APP", f"Closed app: {target.name}", resolved=target.__dict__)

    return _result(False, "CLOSE_APP", f"Could not close app/window: {name}", resolved=target.__dict__)


def minimize_app(name: str) -> dict:
    target = resolve_app(name)
    sysname = _system()
    if not target.name:
        return _result(False, "MINIMIZE_APP", "No app name supplied.")

    if sysname == "linux":
        wmctrl = shutil.which("wmctrl")
        if wmctrl:
            cp = _run([wmctrl, "-lx"])
            q = target.name.lower()
            for line in cp.stdout.splitlines():
                if q in line.lower():
                    win_id = line.split(None, 1)[0]
                    rc = _run([wmctrl, "-i", "-r", win_id, "-b", "add,hidden"]).returncode
                    if rc == 0:
                        return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

        xdotool = shutil.which("xdotool")
        if xdotool:
            cp = _run([xdotool, "search", "--onlyvisible", "--name", target.name])
            ids = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
            if ids and _run([xdotool, "windowminimize", ids[0]]).returncode == 0:
                return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

    if sysname == "darwin":
        osascript = shutil.which("osascript")
        if osascript:
            script = f'tell application "System Events" to set miniaturized of windows of process "{target.name}" to true'
            cp = _run([osascript, "-e", script])
            if cp.returncode == 0:
                return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

    if sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            safe = target.name.replace("'", "''")
            cmd = (
                "$sig='[DllImport(\"user32.dll\")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);'; "
                "Add-Type -MemberDefinition $sig -Name Win32ShowWindowAsync -Namespace Win32; "
                "$q='" + safe + "'; "
                "$p=Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ($_.MainWindowTitle -like \"*$q*\" -or $_.ProcessName -like \"*$q*\") } | Select-Object -First 1; "
                "if($p){ [Win32.Win32ShowWindowAsync]::ShowWindowAsync($p.MainWindowHandle, 6) | Out-Null; exit 0 } else { exit 2 }"
            )
            cp = _run([powershell, "-NoProfile", "-Command", cmd])
            if cp.returncode == 0:
                return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

    if sysname == "android":
        input_bin = shutil.which("input")
        if input_bin and _run([input_bin, "keyevent", "KEYCODE_HOME"]).returncode == 0:
            return _result(True, "MINIMIZE_APP", "Sent current Android app to background/home.", resolved=target.__dict__)

    return _result(False, "MINIMIZE_APP", f"Could not minimize app/window: {name}", resolved=target.__dict__)


def display_server() -> str:
    """"wayland", "x11", or "" when neither can be determined.

    Window control on Linux is not one problem but two. wmctrl and xdotool
    speak the X11 protocol: under Wayland they see only XWayland clients, so a
    native Wayland window is invisible to them and every command silently does
    nothing. Reporting that honestly is worth more than a generic failure.
    """
    if _system() != "linux":
        return ""
    sess = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if sess in {"wayland", "x11"}:
        return sess
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return ""


def _wayland_window_tools() -> list[str]:
    """Compositor-specific window tools that do work under Wayland."""
    return [t for t in ("kdotool", "wlrctl") if shutil.which(t)]


def _wayland_window_advice(what: str) -> str:
    """Explain the limitation instead of returning a bare failure."""
    tools = _wayland_window_tools()
    if tools:
        return (f"Could not {what} — this is a Wayland session and neither "
                f"{'/'.join(tools)} nor XWayland could reach that window.")
    return (
        f"Could not {what}: this is a Wayland session, where wmctrl and xdotool "
        f"can only see XWayland windows, not native Wayland ones. Wayland has no "
        f"general window-control protocol by design. On KDE, installing kdotool "
        f"gives ELI window control; on wlroots compositors, wlrctl does. "
        f"Logging in on X11 restores full window control everywhere."
    )


# Phrases that mean "the window I am looking at", not a window called "it".
# Shared so the executor branch and the dispatch middleware cannot disagree
# about what counts as a named target — they already did once, which is how
# "maximise" ended up with two different notions of a bare request.
BARE_WINDOW_TARGETS = frozenset({
    "", "it", "this", "that", "current", "active", "window", "screen",
    "current window", "this window", "that window", "active window",
    "the current window", "the active window", "the window",
    "current one", "this one",
})


def maximize_app(name: str) -> dict:
    """Maximise a *named* window, on every platform.

    This exists because the executor's MAXIMISE_WINDOW branch had no target
    handling at all: it ran `wmctrl -r :ACTIVE: -b add,maximized_*`
    unconditionally, so "maximise prime video" maximised whatever window
    happened to be focused — the router extracted the window name correctly
    and the executor discarded it. Mirrors minimize_app so the two halves of
    window control behave the same way.

    Returns ok=False when the named window cannot be found. Callers must NOT
    fall back to the active window: silently acting on a different window than
    the one the user named is the defect this function was written to remove.
    """
    target = resolve_app(name)
    sysname = _system()
    if not target.name:
        return _result(False, "MAXIMIZE_APP", "No app name supplied.")

    if sysname == "linux":
        wmctrl = shutil.which("wmctrl")
        if wmctrl:
            cp = _run([wmctrl, "-lx"])
            q = target.name.lower()
            for line in cp.stdout.splitlines():
                if q in line.lower():
                    win_id = line.split(None, 1)[0]
                    # Raise it before resizing — maximising a window that stays
                    # behind another one looks like nothing happened.
                    _run([wmctrl, "-i", "-a", win_id])
                    rc = _run([wmctrl, "-i", "-r", win_id, "-b",
                               "add,maximized_vert,maximized_horz"]).returncode
                    if rc == 0:
                        return _result(True, "MAXIMIZE_APP", f"Maximised app/window: {target.name}", resolved=target.__dict__)

        # kdotool mirrors xdotool's CLI but drives KWin, so it reaches native
        # Wayland windows on KDE. Try whichever of the two is present.
        for tool in [t for t in ("xdotool", *_wayland_window_tools()) if shutil.which(t)]:
            if tool == "wlrctl":
                if _run([tool, "toplevel", "maximize", target.name]).returncode == 0:
                    return _result(True, "MAXIMIZE_APP", f"Maximised app/window: {target.name}", resolved=target.__dict__)
                continue
            cp = _run([tool, "search", "--name", target.name])
            ids = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
            if ids:
                _run([tool, "windowactivate", ids[0]])
                if _run([tool, "windowsize", ids[0], "100%", "100%"]).returncode == 0:
                    return _result(True, "MAXIMIZE_APP", f"Maximised app/window: {target.name}", resolved=target.__dict__)

        if display_server() == "wayland":
            return _result(False, "MAXIMIZE_APP",
                           _wayland_window_advice(f"maximise {target.name}"),
                           resolved=target.__dict__, display_server="wayland")

    if sysname == "darwin":
        osascript = shutil.which("osascript")
        if osascript:
            script = (
                f'tell application "System Events" to tell process "{target.name}" to '
                f'click (first button whose subrole is "AXZoomButton") of window 1'
            )
            cp = _run([osascript, "-e", script])
            if cp.returncode == 0:
                return _result(True, "MAXIMIZE_APP", f"Maximised app/window: {target.name}", resolved=target.__dict__)

    if sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            safe = target.name.replace("'", "''")
            cmd = (
                "$sig='[DllImport(\"user32.dll\")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);'; "
                "Add-Type -MemberDefinition $sig -Name Win32ShowWindowMax -Namespace Win32; "
                "$q='" + safe + "'; "
                "$p=Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ($_.MainWindowTitle -like \"*$q*\" -or $_.ProcessName -like \"*$q*\") } | Select-Object -First 1; "
                # 3 = SW_MAXIMIZE (minimize_app uses 6 = SW_MINIMIZE)
                "if($p){ [Win32.Win32ShowWindowMax]::ShowWindowAsync($p.MainWindowHandle, 3) | Out-Null; exit 0 } else { exit 2 }"
            )
            cp = _run([powershell, "-NoProfile", "-Command", cmd])
            if cp.returncode == 0:
                return _result(True, "MAXIMIZE_APP", f"Maximised app/window: {target.name}", resolved=target.__dict__)

    if sysname == "android":
        return _result(False, "MAXIMIZE_APP", "Android apps are always full-screen; nothing to maximise.",
                       resolved=target.__dict__)

    return _result(False, "MAXIMIZE_APP", f"Could not find a window for: {name}", resolved=target.__dict__)
