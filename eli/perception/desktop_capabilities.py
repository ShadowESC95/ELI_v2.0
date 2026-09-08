"""Cross-OS desktop control capability probe — one place for per-platform truth.

ELI never assumes Linux-only tools. Each platform uses its own stack; missing
tools are reported honestly and offered via grounded_remediation after a failed
attempt — never as a pre-install gate.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Any

from eli.utils import platform_compat as pc
from eli.utils.log import get_logger

log = get_logger(__name__)


def display_server() -> str:
    """Coarse session type for input/screenshot routing."""
    if pc.WINDOWS:
        return "windows"
    if pc.MACOS:
        return "macos"
    if pc.ANDROID:
        return "android"
    if pc.LINUX:
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            return "wayland"
        if os.environ.get("DISPLAY"):
            return "x11"
        return "linux-headless"
    return "other"


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _which(name: str) -> str:
    try:
        from eli.integrations.media.media_deps import resolve_binary
        return resolve_binary(name)
    except Exception:
        return shutil.which(name) or ""


def input_backend() -> dict[str, Any]:
    """Mouse/keyboard injection backend for this host."""
    if pc.ANDROID:
        return {
            "primary": "none",
            "fallback": "none",
            "note": "Android/Termux has app intents and clipboard only — no desktop mouse injection.",
        }
    if pc.WINDOWS:
        py = _has("pyautogui")
        return {
            "primary": "pyautogui" if py else "none",
            "fallback": "powershell_sendkeys",
            "note": "Windows uses PyAutoGUI for pointer/keys; window shortcuts may use PowerShell SendKeys.",
        }
    if pc.MACOS:
        py = _has("pyautogui")
        return {
            "primary": "pyautogui" if py else "none",
            "fallback": "osascript",
            "note": "macOS needs Accessibility permission for synthetic input (System Settings ▸ Privacy).",
        }
    if pc.LINUX:
        ds = display_server()
        if ds == "wayland":
            ydo = _which("ydotool")
            xdo = _which("xdotool")
            return {
                "primary": "ydotool" if ydo else ("xdotool" if xdo else "pyautogui"),
                "fallback": "pyautogui",
                "display": ds,
                "ydotoold_required": bool(ydo),
                "note": (
                    "Wayland: ydotool + ydotoold (uinput) is native; xdotool only reaches XWayland clients."
                    if ds == "wayland"
                    else "Linux desktop input."
                ),
            }
        xdo = _which("xdotool")
        return {
            "primary": "xdotool" if xdo else "pyautogui",
            "fallback": "pyautogui",
            "display": ds,
            "note": "X11: xdotool preferred; PyAutoGUI fallback.",
        }
    return {"primary": "none", "fallback": "none", "note": "Unsupported platform."}


def screenshot_backend() -> dict[str, Any]:
    if pc.WINDOWS:
        return {"primary": "pillow_imagegrab", "fallback": "pyautogui"}
    if pc.MACOS:
        return {"primary": "screencapture", "fallback": "pyautogui"}
    if pc.LINUX:
        ds = display_server()
        if ds == "wayland":
            grim = _which("grim")
            return {
                "primary": "grim+slurp" if grim else "pyautogui",
                "display": ds,
                "note": "Wayland screenshots use grim (+ slurp for region); scrot is X11-only.",
            }
        scrot = _which("scrot")
        return {"primary": "scrot" if scrot else "pyautogui", "display": ds}
    if pc.ANDROID:
        return {"primary": "none", "note": "No desktop screenshot on Android/Termux."}
    return {"primary": "pyautogui"}


def locate_backend() -> dict[str, Any]:
    """Widget/text locate strategies available on this host."""
    backends: list[str] = []
    notes: list[str] = []
    if pc.LINUX:
        try:
            from eli.perception import ui_tree as _ui
            if _ui.available():
                backends.append("atspi")
            else:
                notes.append("AT-SPI unavailable — enable accessibility or launch app with --force-renderer-accessibility.")
        except Exception:
            notes.append("AT-SPI probe failed.")
    elif pc.MACOS:
        notes.append("macOS AX API bridge planned; OCR + optional VL-ground used today.")
    elif pc.WINDOWS:
        notes.append("Windows UI Automation bridge planned; OCR + optional VL-ground used today.")
    tess = _which("tesseract") or (_has("pytesseract") and "pytesseract")
    if tess:
        backends.append("ocr")
    try:
        from eli.perception.ui_ground import configured_precision_backend
        if configured_precision_backend():
            backends.append("vl_ground")
    except Exception:
        log.debug("ui_ground probe skipped", exc_info=True)
    return {"backends": backends, "notes": notes}


def runtime_tools_report() -> dict[str, Any]:
    """Summary for dossier / SELF_TEST / awareness briefing."""
    plat = "android" if pc.ANDROID else ("windows" if pc.WINDOWS else ("macos" if pc.MACOS else "linux"))
    return {
        "platform": plat,
        "python": sys.executable,
        "display_server": display_server(),
        "input": input_backend(),
        "screenshot": screenshot_backend(),
        "locate": locate_backend(),
    }


__all__ = [
    "display_server",
    "input_backend",
    "locate_backend",
    "runtime_tools_report",
    "screenshot_backend",
]
