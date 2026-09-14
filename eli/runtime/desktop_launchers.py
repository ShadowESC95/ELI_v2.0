"""Redistribution-safe desktop / Start Menu launchers.

Never embed a versioned extract path
(e.g. ``~/Downloads/ELI_v2-2.4.29-linux-portable``) in ``.desktop``,
``.command``, or Start Menu shortcuts. Those paths die on the next upgrade
and GNOME fails before our guard can even run (``Failed to change to
directory`` when ``Path=`` points at a deleted folder).

Instead:
  1. Write the current install root to a stable per-user pointer file under
     ``~/.local/share/ELI_v2`` (or ``ELI_v3``).
  2. Menu / Desktop entries ``Exec`` only ``~/.local/bin/eli-run <action>``
     — no ``Path=``, no extract-folder absolute path.
  3. ``eli-run`` reads the pointer and launches scripts from that tree.
  4. Setup and every non-AppImage GUI start refresh the pointer + rewrite
     stale entries (including copies dragged onto ``~/Desktop``).

AppImage keeps its own ``--integrate`` path (``Exec`` = the AppImage file).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)

__all__ = [
    "ensure_desktop_launchers",
    "install_desktop_launchers",
    "install_root_pointer_path",
    "read_install_root",
    "write_install_root",
    "product_line",
]


def product_line() -> str:
    """``v2`` or ``v3`` — drives share dir + .desktop filenames."""
    env = (os.environ.get("ELI_PRODUCT_LINE") or "").strip().lower()
    if env in ("v2", "v3", "2", "3"):
        return "v3" if env in ("v3", "3") else "v2"
    try:
        root = _discover_root()
        if root is not None:
            text = (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', text)
            if m and "v3" in m.group(1).lower():
                return "v3"
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    # Imported package path fallback
    try:
        here = Path(__file__).resolve()
        if any(p.name.lower().startswith("eli_v3") for p in here.parents):
            return "v3"
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return "v2"


def _share_dirname() -> str:
    return "ELI_v3" if product_line() == "v3" else "ELI_v2"


def _display_name() -> str:
    return "ELI v3.0" if product_line() == "v3" else "ELI v2.0"


def _desktop_stem() -> str:
    return "eli-v3" if product_line() == "v3" else "eli-v2"


def stable_user_root() -> Path:
    """Per-user data root outside any extract folder (redistribution-safe)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / _share_dirname()).expanduser().resolve()


def install_root_pointer_path() -> Path:
    return stable_user_root() / "runtime" / "install_root"


def write_install_root(root: Path | str) -> Path:
    root_p = Path(root).expanduser().resolve()
    marker = install_root_pointer_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(root_p) + "\n", encoding="utf-8")
    return marker


def read_install_root() -> Optional[Path]:
    marker = install_root_pointer_path()
    try:
        raw = marker.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None
    if not raw:
        return None
    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return p if p.is_dir() else None


def _discover_root(explicit: Optional[Path | str] = None) -> Optional[Path]:
    if explicit is not None:
        p = Path(explicit).expanduser().resolve()
        return p if p.is_dir() else None
    env = os.environ.get("ELI_PROJECT_ROOT") or os.environ.get("ELI_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir() and (p / "eli").is_dir():
            return p
    try:
        from eli.core.paths import project_root
        p = Path(project_root()).resolve()
        if p.is_dir() and (p / "eli").is_dir():
            return p
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "eli").is_dir():
            return parent
    return None


def _bundle_version(root: Optional[Path] = None) -> str:
    try:
        from eli.core.toml_util import load_toml
        r = root or _discover_root()
        if r is None:
            return ""
        return str((load_toml(r / "pyproject.toml").get("project") or {}).get("version") or "")
    except Exception:
        return ""


def _eli_run_path() -> Path:
    if sys.platform == "win32":
        return stable_user_root() / "eli-run.cmd"
    bindir = Path.home() / ".local" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    return bindir / "eli-run"


def _linux_guard_script() -> str:
    share = _share_dirname()
    return f'''#!/usr/bin/env bash
# ELI launcher (redistribution-safe). Desktop entries must call:
#   eli-run <gui|serve|setup|uninstall>
# Legacy (stale icons): eli-run <install_root> <action> — still accepted.
set -euo pipefail
MARKER="${{XDG_DATA_HOME:-$HOME/.local/share}}/{share}/runtime/install_root"
_err(){{
  command -v zenity >/dev/null 2>&1 && zenity --error --title="ELI" --width=420 --text="$1" 2>/dev/null \\
    || {{ command -v notify-send >/dev/null 2>&1 && notify-send "ELI" "$1" 2>/dev/null; }} \\
    || {{ printf '%s\\n' "$1"; sleep 6; }}
}}
R=""; A=""
if [ "$#" -ge 2 ] && [ -d "$1" ]; then
  R="$1"; A="$2"
else
  A="${{1:-}}"
  if [ -f "$MARKER" ]; then
    R="$(tr -d '\\r\\n' < "$MARKER" 2>/dev/null || true)"
  fi
fi
[ -n "$A" ] || {{ _err "ELI launcher: missing action (gui|serve|setup|uninstall)."; exit 2; }}
[ -n "$R" ] && [ -d "$R" ] || {{ _err "ELI install not found.

Re-run ELI Setup from your current ELI folder (or reinstall the latest release).
The menu icon no longer stores a Downloads/…-portable path — Setup refreshes it."; exit 1; }}
if [ -f "$R/scripts/eli_isolate_env.sh" ]; then
  # shellcheck disable=SC1091
  source "$R/scripts/eli_isolate_env.sh"
  eli_isolate_env "$R" || true
fi
T="$R/scripts/eli_term.sh"
case "$A" in
  gui)       S="$R/scripts/eli_launch.sh";    RUN=(gui) ;;
  serve)     S="$R/scripts/eli_serve.sh";     RUN=(--lan --https) ;;
  setup)     S="$R/scripts/eli_setup.sh";     RUN=() ;;
  uninstall) S="$R/scripts/eli_uninstall.sh"; RUN=() ;;
  *) _err "Unknown ELI action: $A"; exit 2 ;;
esac
if [ "$A" = "gui" ]; then
  [ -x "$S" ] || [ -f "$S" ] || {{ _err "ELI is damaged (missing launcher) at:
$R

Reinstall the latest release."; exit 1; }}
  chmod +x "$S" 2>/dev/null || true
  exec "$S" "${{RUN[@]}}"
fi
{{ [ -f "$T" ] && [ -f "$S" ]; }} || {{ _err "ELI is damaged (missing scripts) at:
$R

Re-run ELI Setup, or reinstall the latest release."; exit 1; }}
chmod +x "$T" "$S" 2>/dev/null || true
exec "$T" "$S" "${{RUN[@]}}"
'''


def _write_eli_run() -> Path:
    dest = _eli_run_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        share = _share_dirname()
        body = (
            "@echo off\r\n"
            "setlocal\r\n"
            f'set "MARKER=%LOCALAPPDATA%\\{share}\\runtime\\install_root"\r\n'
            "set \"A=%~1\"\r\n"
            "if \"%A%\"==\"\" (\r\n"
            "  echo ELI launcher: missing action & exit /b 2\r\n"
            ")\r\n"
            "set \"R=\"\r\n"
            "if exist \"%MARKER%\" set /p R=<\"%MARKER%\"\r\n"
            "if not defined R (\r\n"
            "  echo ELI install not found. Re-run ELI Setup. & exit /b 1\r\n"
            ")\r\n"
            "if not exist \"%R%\\\" (\r\n"
            "  echo ELI install not found at %R%. Re-run ELI Setup. & exit /b 1\r\n"
            ")\r\n"
            "if /I \"%A%\"==\"gui\" (\r\n"
            "  if exist \"%R%\\eli.bat\" (cd /d \"%R%\" & \"%R%\\eli.bat\" & exit /b %ERRORLEVEL%)\r\n"
            "  if exist \"%R%\\scripts\\eli_launch.ps1\" (\r\n"
            "    powershell -ExecutionPolicy Bypass -File \"%R%\\scripts\\eli_launch.ps1\" gui & exit /b %ERRORLEVEL%\r\n"
            "  )\r\n"
            ")\r\n"
            "if /I \"%A%\"==\"serve\" (\r\n"
            "  powershell -ExecutionPolicy Bypass -NoExit -File \"%R%\\scripts\\eli_serve.ps1\" -Lan & exit /b %ERRORLEVEL%\r\n"
            ")\r\n"
            "if /I \"%A%\"==\"uninstall\" (\r\n"
            "  powershell -ExecutionPolicy Bypass -NoExit -File \"%R%\\scripts\\uninstall.ps1\" & exit /b %ERRORLEVEL%\r\n"
            ")\r\n"
            "echo Unknown ELI action: %A% & exit /b 2\r\n"
        )
        dest.write_text(body, encoding="utf-8")
        return dest
    dest.write_text(_linux_guard_script(), encoding="utf-8")
    dest.chmod(0o755)
    return dest


def _icon_for(root: Path) -> str:
    try:
        from eli.gui.branding import prepare_launcher_icons
        return str(prepare_launcher_icons(root=root) or "eli")
    except Exception:
        for rel in (
            "packaging/desktop/Eli_Icon.png",
            "blueprints/Eli_Icon.png",
            "packaging/desktop/eli-256.png",
        ):
            cand = root / rel
            if cand.is_file():
                return str(cand)
    return "eli"


def _apps_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"


def _desktop_search_dirs() -> list[Path]:
    dirs = [_apps_dir()]
    # User-dragged copies on the Desktop stay stale unless we rewrite them too.
    for key in ("XDG_DESKTOP_DIR",):
        raw = os.environ.get(key)
        if raw:
            dirs.append(Path(raw).expanduser())
    desk = Path.home() / "Desktop"
    if desk.is_dir():
        dirs.append(desk)
    # user-dirs.dirs
    try:
        cfg = Path.home() / ".config" / "user-dirs.dirs"
        if cfg.is_file():
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    val = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                    dirs.append(Path(val))
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    # dedupe
    out: list[Path] = []
    seen = set()
    for d in dirs:
        try:
            r = d.resolve()
        except Exception:
            r = d
        if r in seen:
            continue
        seen.add(r)
        out.append(d)
    return out


def _desktop_is_stale(text: str, eli_run: Path, version: str) -> bool:
    if re.search(r"(?m)^Path=", text):
        return True
    if str(eli_run) not in text and "eli-run" not in text:
        return True
    # Old style: Exec=…/eli-run "/path/to/ELI_v2-2.4.29-linux-portable" gui
    if re.search(r"linux-portable|/ELI_v[23]-[\d.]+", text):
        return True
    if version:
        m = re.search(r"(?m)^X-ELI-Version=(.*)$", text)
        if not m or m.group(1).strip() != version:
            return True
    # Exec pointing at a missing AppImage / extract (legacy)
    for line in text.splitlines():
        if not line.startswith("Exec="):
            continue
        raw = line.split("=", 1)[1].strip()
        # skip if it's our shim
        if "eli-run" in raw:
            continue
        tok = raw.split(None, 1)[0].strip().strip('"').strip("'")
        if tok.endswith(".AppImage") and not os.path.isfile(tok):
            return True
        if ("ELI_v" in tok or "linux-portable" in tok) and not os.path.exists(tok):
            return True
    return False


def _write_linux_desktop(root: Path, *, force: bool = False) -> list[Path]:
    eli_run = _write_eli_run()
    write_install_root(root)
    version = _bundle_version(root)
    icon = _icon_for(root)
    stem = _desktop_stem()
    name = _display_name()
    ver_suffix = f" {version}" if version else ""
    entries = {
        f"{stem}.desktop": (
            f"{name}{ver_suffix}",
            f'"{eli_run}" gui',
            "Local, private AI assistant (desktop GUI)",
            False,
        ),
        "eli-server.desktop": (
            f"ELI Server (phone & web){ver_suffix}",
            f'"{eli_run}" serve',
            "ELI phone/web server with console output",
            True,
        ),
        "eli-setup.desktop": (
            f"ELI Setup{ver_suffix}",
            f'"{eli_run}" setup',
            "One-click install — models, database, shortcuts, then launch",
            False,
        ),
        "eli-uninstall.desktop": (
            f"Uninstall {name}{ver_suffix}",
            f'"{eli_run}" uninstall',
            "Remove ELI menu entries; optionally delete this install",
            False,
        ),
    }
    written: list[Path] = []
    apps = _apps_dir()
    apps.mkdir(parents=True, exist_ok=True)
    # Drop legacy names that baked extract paths
    for old in apps.glob("eli*.desktop"):
        try:
            txt = old.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if force or _desktop_is_stale(txt, eli_run, version) or old.name in entries:
            # will rewrite known names; delete unknown eli* that are stale
            if old.name not in entries and _desktop_is_stale(txt, eli_run, version):
                old.unlink(missing_ok=True)

    for fname, (label, execline, comment, terminal) in entries.items():
        body = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={label}\n"
            f"Comment={comment}\n"
            f"Exec={execline}\n"
            f"Icon={icon}\n"
            "Categories=Utility;\n"
            f"Terminal={'true' if terminal else 'false'}\n"
            "StartupNotify=true\n"
        )
        if "gui" in execline:
            body += "StartupWMClass=ELI\n"
        if version:
            body += f"X-ELI-Version={version}\n"
        # Never set Path= — GNOME fails hard if that directory is missing.
        dest = apps / fname
        dest.write_text(body, encoding="utf-8")
        dest.chmod(0o755)
        written.append(dest)

    # Refresh Desktop copies that still point at deleted extract folders
    for desk_dir in _desktop_search_dirs():
        try:
            if desk_dir.resolve() == apps.resolve():
                continue
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        if not desk_dir.is_dir():
            continue
        for old in list(desk_dir.glob("eli*.desktop")) + list(desk_dir.glob("ELI*.desktop")):
            try:
                txt = old.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not _desktop_is_stale(txt, eli_run, version) and str(eli_run) in txt:
                continue
            nm = ""
            m = re.search(r"(?m)^Name=(.*)$", txt)
            if m:
                nm = m.group(1)
            if "Server" in nm:
                key = "eli-server.desktop"
            elif "Setup" in nm:
                key = "eli-setup.desktop"
            elif "Uninstall" in nm:
                key = "eli-uninstall.desktop"
            else:
                key = f"{stem}.desktop"
            src = apps / key
            if src.is_file():
                shutil.copy2(src, old)
                written.append(old)

    try:
        subprocess_update = shutil.which("update-desktop-database")
        if subprocess_update:
            import subprocess
            subprocess.run([subprocess_update, str(apps)], capture_output=True, check=False)
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return written


def _write_macos_commands(root: Path) -> list[Path]:
    eli_run = _write_eli_run()
    write_install_root(root)
    apps = Path.home() / "Applications"
    apps.mkdir(parents=True, exist_ok=True)
    name = _display_name()
    written: list[Path] = []
    mapping = {
        f"{name}.command": "gui",
        "ELI Server (Web App).command": "serve",
        "ELI Setup.command": "setup",
        "ELI Uninstall.command": "uninstall",
    }
    for fname, action in mapping.items():
        dest = apps / fname
        dest.write_text(
            "#!/bin/bash\n"
            f'exec "{eli_run}" {action}\n',
            encoding="utf-8",
        )
        dest.chmod(0o755)
        written.append(dest)
    return written


def _write_windows_shortcuts(root: Path) -> list[Path]:
    write_install_root(root)
    eli_run = _write_eli_run()
    try:
        import win32com.client  # type: ignore
    except Exception:
        # Fall back: write a tiny PowerShell that creates shortcuts without pywin32
        return _write_windows_shortcuts_ps(root, eli_run)

    programs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    name = _display_name()
    icon = None
    for rel in ("packaging/desktop/Eli_Icon.ico", "packaging/desktop/Eli_Icon.png"):
        cand = root / rel
        if cand.is_file():
            icon = str(cand)
            break
    written: list[Path] = []
    for label, action in (
        (name, "gui"),
        ("ELI Server (Web App)", "serve"),
        ("ELI Uninstall", "uninstall"),
    ):
        path = programs / f"{label}.lnk"
        sc = shell.CreateShortcut(str(path))
        sc.TargetPath = str(eli_run)
        sc.Arguments = action
        sc.WorkingDirectory = str(stable_user_root())  # NOT the extract folder
        sc.Description = f"ELI — {action}"
        if icon:
            sc.IconLocation = icon
        sc.Save()
        written.append(path)
    return written


def _write_windows_shortcuts_ps(root: Path, eli_run: Path) -> list[Path]:
    """Create Start Menu .lnk via PowerShell when pywin32 is unavailable."""
    import subprocess
    programs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    name = _display_name()
    written: list[Path] = []
    for label, action in (
        (name, "gui"),
        ("ELI Server (Web App)", "serve"),
        ("ELI Uninstall", "uninstall"),
    ):
        path = programs / f"{label}.lnk"
        wd = str(stable_user_root())
        ps = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{path}"); '
            f'$s.TargetPath = "{eli_run}"; '
            f'$s.Arguments = "{action}"; '
            f'$s.WorkingDirectory = "{wd}"; '
            f'$s.Save()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            check=False,
        )
        if path.is_file():
            written.append(path)
    return written


def install_desktop_launchers(
    root: Optional[Path | str] = None,
    *,
    force: bool = True,
) -> list[Path]:
    """Install / refresh launchers for *root*. Returns paths written."""
    r = _discover_root(root)
    if r is None:
        raise FileNotFoundError("ELI install root not found")
    if sys.platform == "darwin":
        return _write_macos_commands(r)
    if sys.platform == "win32":
        return _write_windows_shortcuts(r)
    if sys.platform.startswith("linux"):
        return _write_linux_desktop(r, force=force)
    return []


def ensure_desktop_launchers(root: Optional[Path | str] = None) -> bool:
    """Best-effort refresh at GUI / Setup start. No-op for AppImage (owns integrate)."""
    if os.environ.get("APPIMAGE") or os.environ.get("ELI_SKIP_DESKTOP_REFRESH") == "1":
        return False
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        # Frozen AppImage / pyinstaller Linux uses eli_entry._integrate
        return False
    try:
        r = _discover_root(root)
        if r is None:
            return False
        # Always refresh pointer; rewrite desktops if stale or pointer changed
        # Always rewrite pointer + eli-run + desktops. Cheap, and the only way
        # to guarantee no leftover Path=/extract-folder after an upgrade.
        install_desktop_launchers(r, force=True)
        return True
    except Exception:
        return False
    return False


def main(argv: Optional[Iterable[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="eli.runtime.desktop_launchers")
    ap.add_argument("command", choices=("install", "ensure", "show-root"))
    ap.add_argument("--root", default=None, help="ELI install / extract root")
    ns = ap.parse_args(list(argv) if argv is not None else None)
    if ns.command == "show-root":
        print(read_install_root() or "")
        return 0
    if ns.command == "ensure":
        ok = ensure_desktop_launchers(ns.root)
        return 0 if ok or read_install_root() else 1
    written = install_desktop_launchers(ns.root, force=True)
    for p in written:
        print(p)
    print(f"[OK] install_root → {read_install_root()}")
    print(f"[OK] eli-run → {_eli_run_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
