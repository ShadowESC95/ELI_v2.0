"""Discover media CLI tools — bundled install root, then system PATH.

yt-dlp is a Python package in ELI's requirements and installs into the bundled
Python environment (AppImage / PyInstaller / one-click install). mpv,
playerctl, tesseract, ffmpeg, xdotool/ydotool are OS packages — offered via
grounded_remediation only after a play/control attempt fails.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from eli.utils.log import get_logger

log = get_logger(__name__)

# Binaries ELI may need for media + desktop control (mpv is never pip-installable).
MEDIA_CLI_TOOLS = frozenset({
    "mpv", "yt-dlp", "playerctl", "ffmpeg", "tesseract", "tesseract-ocr",
    "xdotool", "ydotool", "wmctrl", "scrot", "grim", "slurp",
})


def _search_dirs() -> list[str]:
    dirs: list[str] = []
    exe = Path(sys.executable).resolve()
    exe_parent = exe.parent
    # Bundled / frozen interpreter layout (AppImage, PyInstaller, one-click).
    if exe_parent.is_dir():
        dirs.append(str(exe_parent))
    if getattr(sys, "frozen", False):
        dirs.append(str(exe_parent))
    for root_key in ("ELI_INSTALL_ROOT", "ELI_PROJECT_ROOT"):
        root = os.environ.get(root_key)
        if not root:
            continue
        base = Path(root)
        for sub in ("bin", "Scripts", ".venv/bin", "venv/bin"):
            p = base / sub
            if p.is_dir():
                dirs.append(str(p))
    seen: set[str] = set()
    out: list[str] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


_STARTS: dict = {}


def _starts(path: str) -> bool:
    """A Python-script tool whose Python or package has gone (a system Python upgrade) is still an
    executable file but cannot run: ~/.local/bin/yt-dlp and an old install's .venv/bin/yt-dlp after
    Ubuntu 26.04 replaced Python 3.12. Such a script is tried once (per file version) and passed
    over when it fails; anything else is trusted as found."""
    try:
        with open(path, "rb") as f:
            first = f.read(256).split(b"\n", 1)[0]
        key = (path, os.stat(path).st_mtime_ns)
    except OSError:
        return True   # nothing to judge: trust whoever named it
    if not (first.startswith(b"#!") and b"python" in first):
        return True
    if key not in _STARTS:
        try:
            _STARTS[key] = subprocess.run([path, "--version"], capture_output=True,
                                          timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _STARTS[key] = False      # its interpreter is gone, or it hangs
        except Exception:
            return True               # could not tell
        if not _STARTS[key]:
            log.debug("%s does not start; passed over", path)
    return _STARTS[key]


def resolve_binary(name: str) -> str:
    """Return a path for `name` that starts, or '' if there is none: PATH first, then ELI's own
    install. A broken copy earlier on PATH no longer hides a working one later."""
    tool = str(name or "").strip()
    if not tool:
        return ""
    cands: list[str] = []
    first = shutil.which(tool)
    if first:
        if _starts(first):
            return first
        # the first one on PATH is broken: look for a working copy further along it
        cands += [str(Path(d) / name) for d in os.environ.get("PATH", "").split(os.pathsep) if d
                  for name in (tool, f"{tool}.exe")]
    for d in _search_dirs():
        cands += [str(Path(d) / tool), str(Path(d) / f"{tool}.exe")]
    seen: set[str] = set()
    for cand in cands:
        if cand in seen:
            continue
        seen.add(cand)
        if os.path.isfile(cand) and os.access(cand, os.X_OK) and _starts(cand):
            return cand
    return ""


def yt_dlp_for_mpv() -> str:
    """An executable mpv can run as yt-dlp. mpv takes the first yt-dlp on PATH, working or not, so
    it is told which one: a working binary, or a small launcher for the yt-dlp package ELI carries
    (`<python or ELI> -m yt_dlp`; the frozen app accepts -m)."""
    found = resolve_binary("yt-dlp")
    if found or os.name == "nt" or not yt_dlp_module_available():
        return found
    try:
        from eli.core.paths import data_dir
        shim = Path(data_dir()) / "runtime" / "bin" / "yt-dlp"
        body = f'#!/bin/sh\nexec "{sys.executable}" -m yt_dlp "$@"\n'
        if not shim.is_file() or shim.read_text(encoding="utf-8") != body:
            shim.parent.mkdir(parents=True, exist_ok=True)
            shim.write_text(body, encoding="utf-8")
            shim.chmod(0o755)
        return str(shim)
    except Exception:
        log.debug("yt-dlp launcher for mpv unavailable", exc_info=True)
        return ""


def yt_dlp_module_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


def yt_dlp_argv() -> list[str]:
    """Argv to invoke yt-dlp (binary or `python -m yt_dlp`)."""
    path = resolve_binary("yt-dlp")
    if path:
        return [path]
    if yt_dlp_module_available():
        return [sys.executable, "-m", "yt_dlp"]
    return []


def yt_dlp_available() -> bool:
    return bool(yt_dlp_argv())


def mpv_available() -> bool:
    return bool(resolve_binary("mpv"))


def youtube_mpv_ready() -> bool:
    return mpv_available() and yt_dlp_available()


def missing_youtube_tools() -> list[str]:
    missing: list[str] = []
    if not mpv_available():
        missing.append("mpv")
    if not yt_dlp_available():
        missing.append("yt-dlp")
    return missing


def path_env_for_subprocess() -> dict[str, str]:
    """Copy of os.environ with venv/AppImage bin dirs prepended for child processes."""
    env = dict(os.environ)
    prefix: list[str] = []
    for d in _search_dirs():
        if d not in prefix:
            prefix.append(d)
    if prefix:
        env["PATH"] = os.pathsep.join(prefix + [env.get("PATH", "")])
    yt = resolve_binary("yt-dlp")
    if yt:
        env.setdefault("YTDLP_PATH", yt)
    return env


def pip_install_yt_dlp_command() -> str:
    return f"{sys.executable} -m pip install -U yt-dlp"


def normalize_media_tool_name(name: str) -> str:
    raw = str(name or "").strip().lower()
    aliases = {
        "ytdlp": "yt-dlp",
        "yt_dlp": "yt-dlp",
        "youtube-dl": "yt-dlp",
        "tesseract-ocr": "tesseract",
    }
    return aliases.get(raw, raw)


def media_tool_installed(name: str) -> bool:
    tool = normalize_media_tool_name(name)
    if tool == "yt-dlp":
        return yt_dlp_available()
    return bool(resolve_binary(tool))
