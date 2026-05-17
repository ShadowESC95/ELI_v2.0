from __future__ import annotations

import difflib
import os
import platform
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


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


def _popen(args: list[str]) -> bool:
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
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
    close = difflib.get_close_matches(raw, names, n=1, cutoff=0.55)
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
        if force and shutil.which("pkill"):
            cp = _run(["pkill", "-f", target.name])
            if cp.returncode in (0, 1):
                return _result(True, "CLOSE_APP", f"Force-close attempted for: {target.name}", resolved=target.__dict__)

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
