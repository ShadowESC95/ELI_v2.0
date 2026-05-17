from pathlib import Path
import py_compile
import shutil
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.generic_portable_runtime_contract"
BACKUP.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/system/portable_app_control.py",
    ROOT / "eli/execution/portable_intent_contract.py",
    ROOT / "eli/execution/router_enhanced.py",
    ROOT / "eli/execution/executor_enhanced.py",
]

def backup(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"BACKUP {path.relative_to(ROOT)} -> {dst}")
    else:
        print(f"NEW_FILE {path.relative_to(ROOT)}")

def write_if_changed(path: Path, text: str):
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if old != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"PATCHED {path.relative_to(ROOT)}")
    else:
        print(f"UNCHANGED {path.relative_to(ROOT)}")

def append_once(path: Path, token: str, text: str):
    src = path.read_text(encoding="utf-8", errors="replace")
    if token in src:
        print(f"UNCHANGED {path.relative_to(ROOT)} token={token}")
        return
    path.write_text(src.rstrip() + "\n\n" + text.strip() + "\n", encoding="utf-8")
    print(f"PATCHED {path.relative_to(ROOT)} token={token}")

def compile_one(path: Path):
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"COMPILE_OK {path.relative_to(ROOT)}")
        return 0
    except Exception as exc:
        print(f"COMPILE_BAD {path.relative_to(ROOT)}: {exc}")
        traceback.print_exc()
        return 1

for p in TARGETS:
    backup(p)

portable_app_control = r'''
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
    termux = os.environ.get("TERMUX_VERSION") or os.environ.get("PREFIX", "").lower().find("com.termux") >= 0
    if termux:
        return "android"
    return platform.system().lower()


def _run(args: list[str], timeout: float = 6.0) -> subprocess.CompletedProcess:
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


def _clean_exec_field(exec_line: str) -> list[str]:
    cleaned = re.sub(r"\s+%[A-Za-z]", "", exec_line or "").strip()
    if not cleaned:
        return []
    try:
        return shlex.split(cleaned)
    except Exception:
        return cleaned.split()


def _linux_desktop_dirs() -> list[Path]:
    dirs = []
    home = Path.home()
    dirs.append(home / ".local" / "share" / "applications")
    for base in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if base:
            dirs.append(Path(base) / "applications")
    return dirs


def _iter_linux_apps() -> Iterable[AppCandidate]:
    seen = set()
    for d in _linux_desktop_dirs():
        if not d.exists():
            continue
        for path in d.glob("*.desktop"):
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
    try:
        cp = _run([powershell, "-NoProfile", "-Command", "Get-StartApps | ForEach-Object { $_.Name + '||' + $_.AppID }"], timeout=8)
    except Exception:
        return
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
    try:
        cp = _run([pm, "list", "packages"], timeout=8)
    except Exception:
        return
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
    exact = [a for a in apps if a.name.lower() == q]
    if exact:
        return exact[0]

    contains = [a for a in apps if q in a.name.lower()]
    if contains:
        contains.sort(key=lambda a: len(a.name))
        return contains[0]

    names = [a.name for a in apps]
    close = difflib.get_close_matches(raw, names, n=1, cutoff=0.55)
    if close:
        for a in apps:
            if a.name == close[0]:
                return a

    return AppCandidate(name=raw)


def open_app(name: str) -> dict:
    target = resolve_app(name)
    sysname = _system()

    if not target.name:
        return _result(False, "OPEN_APP", "No app name supplied.")

    if sysname == "linux":
        gtk_launch = shutil.which("gtk-launch")
        if gtk_launch and target.desktop_id:
            if _popen([gtk_launch, target.desktop_id]):
                return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

        if target.command and shutil.which(target.command[0]):
            if _popen(target.command):
                return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

        executable = shutil.which(target.name)
        if executable and _popen([executable]):
            return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    elif sysname == "darwin":
        open_bin = shutil.which("open")
        if open_bin and _popen([open_bin, "-a", target.name]):
            return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    elif sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            if target.app_id:
                cmd = f'Start-Process "shell:AppsFolder\\{target.app_id}"'
            else:
                safe = target.name.replace("'", "''")
                cmd = f"Start-Process -FilePath '{safe}'"
            cp = _run([powershell, "-NoProfile", "-Command", cmd], timeout=8)
            if cp.returncode == 0:
                return _result(True, "OPEN_APP", f"Opened app: {target.name}", resolved=target.__dict__)

    elif sysname == "android":
        monkey = shutil.which("monkey")
        if monkey and target.package:
            cp = _run([monkey, "-p", target.package, "1"], timeout=8)
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
            cp = _run([wmctrl, "-lx"], timeout=6)
            q = target.name.lower()
            for line in cp.stdout.splitlines():
                if q in line.lower():
                    win_id = line.split(None, 1)[0]
                    rc = _run([wmctrl, "-i", "-c", win_id], timeout=4).returncode
                    if rc == 0:
                        return _result(True, "CLOSE_APP", f"Closed app/window: {target.name}", resolved=target.__dict__)

        if force:
            pkill = shutil.which("pkill")
            if pkill:
                cp = _run([pkill, "-f", target.name], timeout=6)
                if cp.returncode in (0, 1):
                    return _result(True, "CLOSE_APP", f"Force-close attempted for: {target.name}", resolved=target.__dict__)

    elif sysname == "darwin":
        osascript = shutil.which("osascript")
        if osascript:
            script = f'tell application "{target.name}" to quit'
            cp = _run([osascript, "-e", script], timeout=8)
            if cp.returncode == 0:
                return _result(True, "CLOSE_APP", f"Closed app: {target.name}", resolved=target.__dict__)

    elif sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            safe = target.name.replace("'", "''")
            cmd = (
                "$q='" + safe + "'; "
                "$p=Get-Process | Where-Object { "
                "$_.MainWindowTitle -like \"*$q*\" -or $_.ProcessName -like \"*$q*\" "
                "}; "
                "if($p){ $p | ForEach-Object { $_.CloseMainWindow() | Out-Null }; exit 0 } else { exit 2 }"
            )
            cp = _run([powershell, "-NoProfile", "-Command", cmd], timeout=10)
            if cp.returncode == 0:
                return _result(True, "CLOSE_APP", f"Closed app/window: {target.name}", resolved=target.__dict__)

    elif sysname == "android":
        am = shutil.which("am")
        if am and target.package:
            cp = _run([am, "force-stop", target.package], timeout=8)
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
            cp = _run([wmctrl, "-lx"], timeout=6)
            q = target.name.lower()
            for line in cp.stdout.splitlines():
                if q in line.lower():
                    win_id = line.split(None, 1)[0]
                    rc = _run([wmctrl, "-i", "-r", win_id, "-b", "add,hidden"], timeout=4).returncode
                    if rc == 0:
                        return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

        xdotool = shutil.which("xdotool")
        if xdotool:
            cp = _run([xdotool, "search", "--onlyvisible", "--name", target.name], timeout=6)
            ids = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
            if ids:
                rc = _run([xdotool, "windowminimize", ids[0]], timeout=4).returncode
                if rc == 0:
                    return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

    elif sysname == "darwin":
        osascript = shutil.which("osascript")
        if osascript:
            script = f'tell application "System Events" to set miniaturized of windows of process "{target.name}" to true'
            cp = _run([osascript, "-e", script], timeout=8)
            if cp.returncode == 0:
                return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

    elif sysname == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            safe = target.name.replace("'", "''")
            cmd = r'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@;
$q=''' + "'" + safe + "'" + r''';
$p=Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ($_.MainWindowTitle -like "*$q*" -or $_.ProcessName -like "*$q*") } | Select-Object -First 1;
if($p){ [Win32]::ShowWindowAsync($p.MainWindowHandle, 6) | Out-Null; exit 0 } else { exit 2 }
'''
            cp = _run([powershell, "-NoProfile", "-Command", cmd], timeout=10)
            if cp.returncode == 0:
                return _result(True, "MINIMIZE_APP", f"Minimized app/window: {target.name}", resolved=target.__dict__)

    elif sysname == "android":
        input_bin = shutil.which("input")
        if input_bin:
            cp = _run([input_bin, "keyevent", "KEYCODE_HOME"], timeout=5)
            if cp.returncode == 0:
                return _result(True, "MINIMIZE_APP", "Sent Android app to background/home.", resolved=target.__dict__)

    return _result(False, "MINIMIZE_APP", f"Could not minimize app/window: {name}", resolved=target.__dict__)


def _result(ok: bool, action: str, text: str, **extra) -> dict:
    out = {
        "ok": bool(ok),
        "action": action,
        "content": text,
        "response": text,
    }
    if not ok:
        out["error"] = text
    out.update(extra)
    return out
'''

portable_intent_contract = r'''
from __future__ import annotations

import re
from typing import Optional


def normalise_voice_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace(" per cent", "%").replace(" percent", "%")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_target(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;")
    return text


def infer_script_language(text: str) -> str:
    norm = normalise_voice_text(text)

    m = re.search(r"\b(?:in|using|with)\s+([a-z0-9+#.\-]{1,40})\b", norm)
    if m:
        return m.group(1)

    m = re.search(
        r"\b(?:generate|write|create|build|make)\s+(?:a|an|the)?\s*([a-z0-9+#.\-]{1,40})\s+(?:script|code|program|module|tool|app)\b",
        norm,
    )
    if m:
        candidate = m.group(1)
        if candidate not in {"potent", "powerful", "advanced", "basic", "simple", "new"}:
            return candidate

    return "auto"


def try_route(text: str) -> Optional[dict]:
    raw = str(text or "").strip()
    norm = normalise_voice_text(raw)
    if not norm:
        return None

    # Generic app/window commands. No app names are hard-coded.
    m = re.fullmatch(r"(?:open|launch|start|run|opens)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        return {
            "action": "OPEN_APP",
            "args": {"name": target, "target": target},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.open_app"},
        }

    m = re.fullmatch(r"(?:close|closed|exit|quit)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        return {
            "action": "CLOSE_APP",
            "args": {"name": target, "target": target},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.close_app"},
        }

    m = re.fullmatch(r"(?:kill|force close|force quit)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        return {
            "action": "CLOSE_APP",
            "args": {"name": target, "target": target, "force": True},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.force_close_app"},
        }

    m = re.fullmatch(r"(?:minimize|minimise|hide)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        return {
            "action": "MINIMIZE_APP",
            "args": {"name": target, "target": target},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.minimize_app"},
        }

    # Generic absolute volume.
    m = re.fullmatch(r"(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?", norm)
    if m:
        level = max(0, min(100, int(m.group(1))))
        return {
            "action": "VOLUME",
            "args": {"level": level, "percent": level, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "portable_intent_contract.volume_absolute"},
        }

    # Generic media command: play arbitrary query on arbitrary target service/app.
    m = re.fullmatch(r"play\s+(.+?)\s+(?:on|using|with)\s+(.+)", norm)
    if m:
        query = _clean_target(m.group(1))
        target = _clean_target(m.group(2))
        return {
            "action": "PLAY_MEDIA",
            "args": {"query": query, "target": target, "service": target},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.play_query_on_target"},
        }

    # Generic script/code/program generation. No language restriction.
    if re.search(r"\b(?:generate|write|create|build|make)\b", norm) and re.search(r"\b(?:script|code|program|module|tool|app)\b", norm):
        language = infer_script_language(raw)
        return {
            "action": "GENERATE_SCRIPT",
            "args": {
                "description": raw,
                "prompt": raw,
                "language": language,
                "destination": "labs_sim_ide",
                "open_in_labs": True,
                "open_in_ide": True,
            },
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.generate_script"},
        }

    return None


def wrap_router_callable(fn):
    if not callable(fn) or getattr(fn, "_portable_intent_contract_wrapped", False):
        return fn

    def wrapped(*args, **kwargs):
        text = ""
        for item in args:
            if isinstance(item, str) and item.strip():
                text = item
                break
        if not text:
            for key in ("text", "message", "command", "prompt", "query", "utterance"):
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    text = value
                    break

        route = try_route(text)
        if route is not None:
            return route
        return fn(*args, **kwargs)

    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    wrapped.__doc__ = getattr(fn, "__doc__", None)
    wrapped._portable_intent_contract_wrapped = True
    return wrapped
'''

router_hook = r'''
# portable_intent_contract_hook
try:
    from eli.execution.portable_intent_contract import wrap_router_callable as _eli_portable_wrap_router

    for _eli_name in (
        "route", "route_text", "route_command", "route_intent",
        "parse", "parse_intent", "parse_command",
        "classify", "classify_intent",
    ):
        _eli_fn = globals().get(_eli_name)
        if callable(_eli_fn):
            globals()[_eli_name] = _eli_portable_wrap_router(_eli_fn)

    for _eli_obj in list(globals().values()):
        if isinstance(_eli_obj, type):
            for _eli_name in (
                "route", "route_text", "route_command", "route_intent",
                "parse", "parse_intent", "parse_command",
                "classify", "classify_intent",
            ):
                try:
                    _eli_method = getattr(_eli_obj, _eli_name, None)
                    if callable(_eli_method):
                        setattr(_eli_obj, _eli_name, _eli_portable_wrap_router(_eli_method))
                except Exception:
                    pass
except Exception as _eli_portable_router_err:
    print(f"[portable_intent_contract] router hook unavailable: {_eli_portable_router_err}")
'''

executor_hook = r'''
# portable_executor_contract_hook
try:
    _ELI_PORTABLE_ORIG_EXECUTE
except NameError:
    _ELI_PORTABLE_ORIG_EXECUTE = globals().get("execute")
    _ELI_PORTABLE_ORIG_EXECUTE_ACTION = globals().get("execute_action")

    def _eli_portable_action_name(action):
        return str(action or "").strip().upper().replace("-", "_")

    def _eli_portable_args(args):
        return args if isinstance(args, dict) else {}

    def _eli_portable_direct_execute(action, args=None):
        action_name = _eli_portable_action_name(action)
        data = _eli_portable_args(args)

        if action_name in {"OPEN_APP", "LAUNCH_APP", "OPEN_APPLICATION"}:
            from eli.system.portable_app_control import open_app
            return open_app(data.get("name") or data.get("target") or data.get("app") or "")

        if action_name in {"CLOSE_APP", "QUIT_APP", "EXIT_APP", "CLOSE_APPLICATION"}:
            from eli.system.portable_app_control import close_app
            return close_app(
                data.get("name") or data.get("target") or data.get("app") or "",
                force=bool(data.get("force", False)),
            )

        if action_name in {"MINIMIZE_APP", "MINIMISE_APP", "HIDE_APP", "MINIMIZE_WINDOW", "MINIMISE_WINDOW"}:
            from eli.system.portable_app_control import minimize_app
            return minimize_app(data.get("name") or data.get("target") or data.get("app") or "")

        return None

    if callable(_ELI_PORTABLE_ORIG_EXECUTE):
        def execute(action, args=None, *pargs, **kwargs):
            direct = _eli_portable_direct_execute(action, args)
            if direct is not None:
                return direct
            return _ELI_PORTABLE_ORIG_EXECUTE(action, args, *pargs, **kwargs)

    if callable(_ELI_PORTABLE_ORIG_EXECUTE_ACTION):
        def execute_action(action, args=None, *pargs, **kwargs):
            direct = _eli_portable_direct_execute(action, args)
            if direct is not None:
                return direct
            return _ELI_PORTABLE_ORIG_EXECUTE_ACTION(action, args, *pargs, **kwargs)
'''

write_if_changed(ROOT / "eli/system/portable_app_control.py", portable_app_control.strip() + "\n")
write_if_changed(ROOT / "eli/execution/portable_intent_contract.py", portable_intent_contract.strip() + "\n")
append_once(ROOT / "eli/execution/router_enhanced.py", "portable_intent_contract_hook", router_hook)
append_once(ROOT / "eli/execution/executor_enhanced.py", "portable_executor_contract_hook", executor_hook)

rc = 0
for p in TARGETS:
    if p.exists():
        rc |= compile_one(p)

print(f"BACKUP={BACKUP}")
print(f"PATCH_RC={rc}")
