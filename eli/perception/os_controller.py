#!/usr/bin/env python3
"""
Cross-platform OS controller for ELI.

Linux desktop integrations still use native tools when available, but Windows
and macOS now get platform-aware screenshot, volume, keyboard, and clipboard
fallbacks instead of falling through to Linux-only binaries.
"""

import os
from datetime import datetime
import subprocess
import shutil
import time
from typing import Optional, Dict, Any
from eli.utils import platform_compat as platform
from eli.utils.platform_compat import LINUX, WINDOWS, MACOS


from eli.utils.log import get_logger
log = get_logger(__name__)

# ----------------------------------------------------------------------
# Environment detection
# ----------------------------------------------------------------------
SESSION_TYPE = os.environ.get('XDG_SESSION_TYPE', 'x11').lower()
DESKTOP = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
IS_WAYLAND = SESSION_TYPE == 'wayland'
IS_X11 = SESSION_TYPE == 'x11'
IS_GNOME = 'gnome' in DESKTOP

def _check_tool(tool: str) -> bool:
    """Return True if tool is installed and executable."""
    return shutil.which(tool) is not None


def _screenshot_path(prefix: str = "Screenshot") -> str:
    pictures = platform.user_pictures_dir()
    pictures.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    return str(pictures / filename)


def _capture_with_imagegrab(path: str) -> Dict[str, Any] | None:
    """Capture the full screen with Pillow ImageGrab when the OS allows it."""
    try:
        from PIL import ImageGrab  # type: ignore

        img = ImageGrab.grab()
        img.save(path)
        return {
            "ok": True,
            "path": path,
            "content": f"Screenshot saved: {path}",
            "response": f"Screenshot saved: {path}",
        }
    except Exception:
        return None

# ----------------------------------------------------------------------
# Screenshot – GNOME Screenshot first, then grim, then scrot
# ----------------------------------------------------------------------
def take_screenshot(region: str = "full") -> Dict[str, Any]:
    """
    Take a screenshot.
    region: "full" (entire screen) or "area" (select region)
    Returns dict with ok, path, error.
    """
    region = (region or "full").lower()

    # Windows and macOS can usually capture the full screen through Pillow.
    if WINDOWS:
        if region != "full":
            return {
                "ok": False,
                "error": "Area screenshots require a user-selected capture tool on Windows.",
                "content": "Area screenshots are not available on this Windows install.",
                "response": "Area screenshots are not available on this Windows install.",
            }
        path = _screenshot_path()
        result = _capture_with_imagegrab(path)
        if result:
            return result
        return {
            "ok": False,
            "error": "Pillow ImageGrab could not capture the Windows desktop.",
            "content": "Screenshot failed",
            "response": "Screenshot failed",
        }

    if MACOS:
        path = _screenshot_path("Screenshot_area" if region != "full" else "Screenshot")
        cmd = ["screencapture", "-x", path] if region == "full" else ["screencapture", "-i", path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and os.path.exists(path):
                return {
                    "ok": True,
                    "path": path,
                    "content": f"Screenshot saved: {path}",
                    "response": f"Screenshot saved: {path}",
                }
            fallback = _capture_with_imagegrab(path) if region == "full" else None
            if fallback:
                return fallback
            return {
                "ok": False,
                "error": result.stderr.strip() or "screencapture failed",
                "content": "Screenshot failed",
                "response": "Screenshot failed",
            }
        except Exception as e:
            fallback = _capture_with_imagegrab(path) if region == "full" else None
            if fallback:
                return fallback
            return {"ok": False, "error": str(e), "content": "Screenshot failed", "response": "Screenshot failed"}

    # Try a cross-platform Pillow capture before Linux-specific CLIs. On Linux
    # this can work on X11; Wayland often requires portal/native tools.
    if region == "full":
        path = _screenshot_path()
        result = _capture_with_imagegrab(path)
        if result:
            return result

    # Try GNOME Screenshot (works on GNOME Wayland)
    if IS_GNOME and _check_tool("gnome-screenshot"):
        try:
            path = _screenshot_path("Screenshot_area" if region != "full" else "Screenshot")
            if region == "full":
                cmd = ["gnome-screenshot", "-f", path]
            else:
                cmd = ["gnome-screenshot", "-a", "-f", path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return {"ok": True, "path": path, "content": f"Screenshot saved: {path}", "response": f"Screenshot saved: {path}"}
        except Exception:
            pass

    # Try generic Wayland tools (grim + slurp)
    if IS_WAYLAND:
        if region == "full":
            if _check_tool("grim"):
                path = _screenshot_path()
                result = subprocess.run(["grim", path], capture_output=True, text=True)
                if result.returncode == 0:
                    return {"ok": True, "path": path, "content": f"Screenshot saved: {path}", "response": f"Screenshot saved: {path}"}
                else:
                    return {"ok": False, "error": f"grim failed: {result.stderr}", "content": "Screenshot failed", "response": "Screenshot failed"}
            else:
                return {"ok": False, "error": "grim not installed (sudo apt install grim)", "content": "Screenshot failed", "response": "Screenshot failed"}
        else:  # area
            if _check_tool("slurp") and _check_tool("grim"):
                select = subprocess.run(["slurp"], capture_output=True, text=True)
                if select.returncode != 0 or not select.stdout.strip():
                    return {"ok": False, "error": "No area selected", "content": "Screenshot cancelled", "response": "Screenshot cancelled"}
                geometry = select.stdout.strip()
                path = _screenshot_path("Screenshot_area")
                result = subprocess.run(["grim", "-g", geometry, path], capture_output=True, text=True)
                if result.returncode == 0:
                    return {"ok": True, "path": path, "content": f"Screenshot saved: {path}", "response": f"Screenshot saved: {path}"}
                else:
                    return {"ok": False, "error": f"grim failed: {result.stderr}", "content": "Screenshot failed", "response": "Screenshot failed"}
            else:
                return {"ok": False, "error": "slurp or grim not installed (sudo apt install slurp grim)", "content": "Screenshot failed", "response": "Screenshot failed"}

    # X11 fallback (scrot)
    if _check_tool("scrot"):
        if region == "full":
            path = _screenshot_path()
            result = subprocess.run(["scrot", path], capture_output=True, text=True)
            if result.returncode == 0:
                return {"ok": True, "path": path, "content": f"Screenshot saved: {path}", "response": f"Screenshot saved: {path}"}
            else:
                return {"ok": False, "error": f"scrot failed: {result.stderr}", "content": "Screenshot failed", "response": "Screenshot failed"}
        else:
            path = _screenshot_path("Screenshot_area")
            result = subprocess.run(["scrot", "-s", path], capture_output=True, text=True)
            if result.returncode == 0:
                return {"ok": True, "path": path, "content": f"Screenshot saved: {path}", "response": f"Screenshot saved: {path}"}
            else:
                return {"ok": False, "error": f"scrot failed: {result.stderr}", "content": "Screenshot failed", "response": "Screenshot failed"}
    else:
        return {"ok": False, "error": "No screenshot tool found (install gnome-screenshot, grim, or scrot)", "content": "Screenshot failed", "response": "Screenshot failed"}

# ----------------------------------------------------------------------
# Volume control – wpctl (Wayland) then pactl (X11)
# ----------------------------------------------------------------------
def get_volume() -> Optional[int]:
    """Get current volume percentage (0-100)."""
    portable = platform.get_volume()
    if portable is not None:
        return portable

    if LINUX and IS_WAYLAND and _check_tool("wpctl"):
        result = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True)
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            for part in parts:
                try:
                    vol_float = float(part)
                    return int(vol_float * 100)
                except:
                    continue
    return None

def set_volume(level: Optional[int] = None, direction: Optional[str] = None, delta: int = 5) -> Dict[str, Any]:
    """
    Set or adjust volume.
    - level: absolute percentage (0-100)
    - direction: "up" or "down"
    - delta: step percentage for up/down

    NOTE: pactl is used as primary on both Wayland and X11.
    wpctl (WirePlumber) normalises streams and can revert volume immediately,
    so we only fall back to it if pactl is unavailable.
    """
    if level is not None:
        lvl = max(0, min(100, int(level)))
        if platform.set_volume(lvl):
            return {"ok": True, "content": f"Volume set to {lvl}%", "response": f"Volume set to {lvl}%"}
    elif direction in ("up", "raise"):
        if platform.adjust_volume(abs(int(delta))):
            return {"ok": True, "content": f"Volume raised by {delta}%", "response": f"Volume raised by {delta}%"}
    elif direction in ("down", "lower"):
        if platform.adjust_volume(-abs(int(delta))):
            return {"ok": True, "content": f"Volume lowered by {delta}%", "response": f"Volume lowered by {delta}%"}
    elif direction == "mute":
        if platform.set_muted(True):
            return {"ok": True, "content": "Muted", "response": "Muted"}
    elif direction == "unmute":
        if platform.set_muted(False):
            return {"ok": True, "content": "Unmuted", "response": "Unmuted"}

    if not LINUX:
        return {
            "ok": False,
            "error": "Volume control backend unavailable on this OS. On Windows install pycaw/comtypes for full control.",
            "content": "Volume control unavailable",
            "response": "Volume control unavailable",
        }

    # ── pactl (PulseAudio / PipeWire-pulse) ── primary on all sessions ──
    if _check_tool("pactl"):
        try:
            if level is not None:
                lvl = max(0, min(100, level))
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{lvl}%"], check=True, capture_output=True)
                return {"ok": True, "content": f"Volume set to {lvl}%", "response": f"Volume set to {lvl}%"}
            elif direction == "up":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{delta}%"], check=True, capture_output=True)
                return {"ok": True, "content": f"Volume raised by {delta}%", "response": f"Volume raised by {delta}%"}
            elif direction == "down":
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{delta}%"], check=True, capture_output=True)
                return {"ok": True, "content": f"Volume lowered by {delta}%", "response": f"Volume lowered by {delta}%"}
            elif direction == "mute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], check=True, capture_output=True)
                return {"ok": True, "content": "Muted", "response": "Muted"}
            elif direction == "unmute":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=True, capture_output=True)
                return {"ok": True, "content": "Unmuted", "response": "Unmuted"}
        except Exception as e:
            pass  # fall through to wpctl

    # ── wpctl fallback (only if pactl unavailable) ──
    if IS_WAYLAND and _check_tool("wpctl"):
        try:
            if level is not None:
                float_level = max(0, min(100, level)) / 100.0
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{float_level}"], check=True, capture_output=True)
                return {"ok": True, "content": f"Volume set to {level}%", "response": f"Volume set to {level}%"}
            elif direction == "up":
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{delta}%+"], check=True, capture_output=True)
                return {"ok": True, "content": f"Volume raised by {delta}%", "response": f"Volume raised by {delta}%"}
            elif direction == "down":
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{delta}%-"], check=True, capture_output=True)
                return {"ok": True, "content": f"Volume lowered by {delta}%", "response": f"Volume lowered by {delta}%"}
            elif direction == "mute":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], check=True, capture_output=True)
                return {"ok": True, "content": "Muted", "response": "Muted"}
            elif direction == "unmute":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], check=True, capture_output=True)
                return {"ok": True, "content": "Unmuted", "response": "Unmuted"}
        except Exception as e:
            return {"ok": False, "error": str(e), "content": "Volume control failed", "response": "Volume control failed"}

    return {"ok": False, "error": "No volume control tool found (install pulseaudio-utils: sudo apt install pulseaudio-utils)", "content": "Volume control failed", "response": "Volume control failed"}

# ----------------------------------------------------------------------
# Keyboard simulation – ydotool (Wayland) then xdotool (X11)
# ----------------------------------------------------------------------
def press_key(key: str) -> Dict[str, Any]:
    """Simulate a key press."""
    key_raw = (key or "").strip()
    key_norm = key_raw.lower().replace("control", "ctrl").replace("cmd", "command")
    if "+" in key_norm:
        parts = [p.strip() for p in key_norm.split("+") if p.strip()]
        pyautogui_parts = [
            {"ctrl": "ctrl", "control": "ctrl", "cmd": "command", "super": "win"}.get(p, p)
            for p in parts
        ]
        try:
            import pyautogui  # type: ignore
            pyautogui.hotkey(*pyautogui_parts)
            return {"ok": True, "content": f"Pressed {key_raw}", "response": f"Pressed {key_raw}"}
        except Exception:
            pass

        xdotool_map = {
            "ctrl": "ctrl",
            "control": "ctrl",
            "shift": "shift",
            "alt": "alt",
            "super": "super",
            "command": "super",
            "cmd": "super",
            "tab": "Tab",
            "w": "w",
            "t": "t",
            "l": "l",
            "r": "r",
            "enter": "Return",
            "escape": "Escape",
            "esc": "Escape",
        }
        keyname = "+".join(xdotool_map.get(p, p) for p in parts)
        if _check_tool("xdotool"):
            try:
                subprocess.run(["xdotool", "key", "--clearmodifiers", keyname], check=True, capture_output=True)
                return {"ok": True, "content": f"Pressed {key_raw}", "response": f"Pressed {key_raw}"}
            except Exception:
                pass
        return {
            "ok": False,
            "error": "Keyboard shortcut simulation requires pyautogui or xdotool.",
            "content": f"Failed to press {key_raw}",
            "response": f"Failed to press {key_raw}",
        }

    if platform.key_press(key_norm):
        return {"ok": True, "content": f"Pressed {key}", "response": f"Pressed {key}"}
    if not LINUX:
        return {
            "ok": False,
            "error": "Keyboard simulation requires pyautogui and OS accessibility permissions on this platform.",
            "content": f"Failed to press {key}",
            "response": f"Failed to press {key}",
        }

    key_map = {
        "enter": "Return", "return": "Return", "tab": "Tab", "space": "space",
        "backspace": "BackSpace", "delete": "Delete", "escape": "Escape",
        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
        "home": "Home", "end": "End", "pageup": "Page_Up", "pagedown": "Page_Down",
        "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "super": "Super",
    }
    keyname = key_map.get(key.lower(), key)

    if IS_WAYLAND and _check_tool("ydotool"):
        try:
            subprocess.run(["ydotool", "key", f"{keyname}:1", f"{keyname}:0"], check=True, capture_output=True)
            return {"ok": True, "content": f"Pressed {key}", "response": f"Pressed {key}"}
        except Exception as e:
            pass
    if _check_tool("xdotool"):
        try:
            subprocess.run(["xdotool", "key", keyname], check=True, capture_output=True)
            return {"ok": True, "content": f"Pressed {key}", "response": f"Pressed {key}"}
        except Exception as e:
            pass
    return {"ok": False, "error": "No keyboard simulation tool found (install ydotool or xdotool)", "content": f"Failed to press {key}", "response": f"Failed to press {key}"}

def type_text(text: str) -> Dict[str, Any]:
    """Type a string."""
    if platform.type_text(text):
        return {"ok": True, "content": f"Typed: {text}", "response": f"Typed: {text}"}
    if not LINUX:
        return {
            "ok": False,
            "error": "Text entry requires pyautogui and OS accessibility permissions on this platform.",
            "content": "Failed to type",
            "response": "Failed to type",
        }

    if IS_WAYLAND and _check_tool("ydotool"):
        try:
            subprocess.run(["ydotool", "type", text], check=True, capture_output=True)
            return {"ok": True, "content": f"Typed: {text}", "response": f"Typed: {text}"}
        except Exception as e:
            pass
    if _check_tool("xdotool"):
        try:
            subprocess.run(["xdotool", "type", text], check=True, capture_output=True)
            return {"ok": True, "content": f"Typed: {text}", "response": f"Typed: {text}"}
        except Exception as e:
            pass
    return {"ok": False, "error": "No keyboard simulation tool found", "content": f"Failed to type", "response": f"Failed to type"}

# ----------------------------------------------------------------------
# CLIPBOARD – finally fixed: no timeouts, foreground mode for wl-copy
# ----------------------------------------------------------------------
def set_clipboard(text: str) -> Dict[str, Any]:
    """Set clipboard content with platform-native fallbacks."""
    if platform.copy_to_clipboard(text):
        return {"ok": True, "content": "Clipboard set", "response": "Clipboard set"}
    if not LINUX:
        return {
            "ok": False,
            "error": "No clipboard backend works on this platform.",
            "content": "Failed to set clipboard",
            "response": "Failed to set clipboard",
        }

    # Wayland – use -f to keep in foreground, no timeout
    if _check_tool("wl-copy"):
        try:
            # No timeout – let it finish naturally
            proc = subprocess.run(
                ["wl-copy", "-f"],  # -f = foreground, prevents forking
                input=text,
                text=True,
                capture_output=True
            )
            if proc.returncode == 0:
                return {"ok": True, "content": "Clipboard set", "response": "Clipboard set"}
            else:
                log.debug(f"[CLIPBOARD] wl-copy failed: {proc.stderr}")
        except Exception as e:
            log.debug(f"[CLIPBOARD] wl-copy exception: {e}")

    # X11 fallback
    if _check_tool("xclip"):
        try:
            # No timeout
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                capture_output=True
            )
            if proc.returncode == 0:
                return {"ok": True, "content": "Clipboard set", "response": "Clipboard set"}
            else:
                log.debug(f"[CLIPBOARD] xclip failed: {proc.stderr}")
        except Exception as e:
            log.debug(f"[CLIPBOARD] xclip exception: {e}")

    return {"ok": False, "error": "No clipboard tool works",
            "content": "Failed to set clipboard", "response": "Failed to set clipboard"}

def get_clipboard() -> Optional[str]:
    """Get clipboard content. Returns None if unavailable."""
    portable = platform.get_clipboard()
    if portable:
        return portable
    if not LINUX:
        return None

    if _check_tool("wl-paste"):
        try:
            proc = subprocess.run(
                ["wl-paste"],  # no timeout
                capture_output=True,
                text=True
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
            else:
                log.debug(f"[CLIPBOARD] wl-paste failed: {proc.stderr}")
        except Exception as e:
            log.debug(f"[CLIPBOARD] wl-paste exception: {e}")

    if _check_tool("xclip"):
        try:
            proc = subprocess.run(
                ["xclip", "-o", "-selection", "clipboard"],
                capture_output=True,
                text=True
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
        except Exception:
            pass
    return None
