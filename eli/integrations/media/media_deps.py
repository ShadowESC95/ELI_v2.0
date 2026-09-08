"""Discover media CLI tools — bundled install root, then system PATH.

yt-dlp is a Python package in ELI's requirements and installs into the bundled
Python environment (AppImage / PyInstaller / one-click install). mpv,
playerctl, tesseract, ffmpeg, xdotool/ydotool are OS packages — offered via
grounded_remediation only after a play/control attempt fails.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

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


def resolve_binary(name: str) -> str:
    """Return an executable path for `name`, or '' if not found."""
    tool = str(name or "").strip()
    if not tool:
        return ""
    hit = shutil.which(tool)
    if hit:
        return hit
    for d in _search_dirs():
        for cand in (Path(d) / tool, Path(d) / f"{tool}.exe"):
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
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
