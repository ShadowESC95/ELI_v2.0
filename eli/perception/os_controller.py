#!/usr/bin/env python3
"""
Cross-platform OS controller for ELI.

Linux desktop integrations still use native tools when available, but Windows
and macOS now get platform-aware screenshot, volume, keyboard, and clipboard
fallbacks instead of falling through to Linux-only binaries.
"""

import os
import re
from datetime import datetime
import subprocess
import shutil
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


def _screenshot_path(prefix: str = "Screenshot", *, keep: bool = True) -> str:
    """Where a screenshot goes: the user's Pictures folder when they asked for one, ELI's own data
    folder when ELI takes it to read the screen (finding a button by its label filled Pictures)."""
    if keep:
        folder = platform.user_pictures_dir()
    else:
        from eli.core.paths import data_dir
        folder = data_dir() / "screens"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    return str(folder / filename)


def _written(path: str) -> bool:
    """A capture counts only when its file is there: gnome-screenshot on GNOME 50 exits 0 having
    written nothing, and that was reported as a screenshot."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _saved(path: str) -> Dict[str, Any]:
    return {"ok": True, "path": path, "content": f"Screenshot saved: {path}", "response": f"Screenshot saved: {path}"}


def _capture_with_tool(cmd: list, path: str, timeout: float = 30.0) -> bool:
    """Run a capture program with a time limit; True when it wrote the picture."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        log.debug("screenshot tool %s did not finish", cmd[0], exc_info=True)
        return False
    return done.returncode == 0 and _written(path)


def _capture_with_imagegrab(path: str) -> Dict[str, Any] | None:
    """Pillow's capture: GDI on Windows (every monitor), XCB on X11, screencapture on macOS. Not on
    Wayland, where it sees only XWayland's windows and falls back to a tool it runs without a time
    limit."""
    if IS_WAYLAND and LINUX:
        return None
    try:
        from PIL import ImageGrab  # type: ignore

        img = ImageGrab.grab(all_screens=True) if WINDOWS else ImageGrab.grab()
        img.save(path)
    except Exception:
        log.debug("Pillow screen grab failed", exc_info=True)
        return None
    return _saved(path) if _written(path) else None


def _capture_with_portal(path: str, *, interactive: bool = False, timeout: float = 90.0) -> bool:
    """The desktop's own screenshot service on Linux (xdg-desktop-portal: GNOME, KDE, wlroots
    compositors through xdg-desktop-portal-wlr, Hyprland, and X11 desktops that run it), asked
    through gdbus. The first time, the desktop asks the user whether ELI may take screenshots; the
    wait is for that answer and is bounded. True when the picture was written to `path`."""
    import selectors
    import time
    import urllib.parse
    gdbus = shutil.which("gdbus")
    if not gdbus or not LINUX:
        return False
    token = f"eli_{os.getpid()}_{int(time.time() * 1000)}"
    dest = "org.freedesktop.portal.Desktop"
    try:
        monitor = subprocess.Popen([gdbus, "monitor", "--session", "--dest", dest],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return False
    picker = selectors.DefaultSelector()
    picker.register(monitor.stdout, selectors.EVENT_READ)

    def _line(deadline: float) -> Optional[str]:
        left = deadline - time.monotonic()
        if left <= 0 or not picker.select(left):
            return None
        return monitor.stdout.readline()

    try:
        if _line(time.monotonic() + 5.0) is None:          # listening before the request goes out
            return False
        options = f"{{'handle_token': <'{token}'>, 'interactive': <{'true' if interactive else 'false'}>}}"
        call = subprocess.run([gdbus, "call", "--session", "--dest", dest, "--object-path", "/org/freedesktop/portal/desktop",
                               "--method", "org.freedesktop.portal.Screenshot.Screenshot", "", options],
                              capture_output=True, text=True, timeout=15)
        if call.returncode != 0:
            log.debug("screenshot portal refused the request: %s", (call.stderr or "").strip()[:200])
            return False
        deadline = time.monotonic() + timeout
        while True:
            line = _line(deadline)
            if line is None:
                return False
            if token not in line or "Request.Response" not in line:
                continue
            answer = re.search(r"\(uint32 (\d+),", line)
            uri = re.search(r"'uri': <'([^']+)'>", line)
            if not answer or answer.group(1) != "0" or not uri:
                return False                                  # declined or cancelled
            source = urllib.parse.unquote(urllib.parse.urlparse(uri.group(1)).path)
            if os.path.abspath(source) != os.path.abspath(path):
                shutil.move(source, path)
            return _written(path)
    except (OSError, subprocess.TimeoutExpired, shutil.Error):
        log.debug("screenshot portal failed", exc_info=True)
        return False
    finally:
        monitor.terminate()
        try:
            monitor.wait(timeout=2)
        except subprocess.TimeoutExpired:
            monitor.kill()


def _macos_screen_recording_allowed() -> Optional[bool]:
    """macOS 10.15 and later: whether ELI may record the screen. Without it a capture shows the
    desktop picture and none of the windows. None where it cannot be asked."""
    try:
        import ctypes
        import ctypes.util
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        return bool(cg.CGPreflightScreenCaptureAccess())
    except Exception:
        return None


def _capture_windows_area(path: str, wait: float = 60.0) -> Dict[str, Any] | None:
    """Windows: the user picks the area with Windows' own snip overlay (ms-screenclip:), which puts
    the picture on the clipboard; it is saved from there. None when no new picture arrives."""
    try:
        import time
        from PIL import ImageGrab  # type: ignore

        def _clip_bytes():
            img = ImageGrab.grabclipboard()
            return img.tobytes() if hasattr(img, "tobytes") else None

        before = _clip_bytes()
        os.startfile("ms-screenclip:")  # type: ignore[attr-defined]
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(0.5)
            img = ImageGrab.grabclipboard()
            if hasattr(img, "save") and img.tobytes() != before:
                img.save(path)
                return {"ok": True, "path": path, "content": f"Screenshot saved: {path}",
                        "response": f"Screenshot saved: {path}"}
    except Exception:
        log.debug("Windows area capture failed", exc_info=True)
    return None


# ----------------------------------------------------------------------
# Screenshot — every OS, every Linux desktop (X11 and Wayland)
# ----------------------------------------------------------------------
def take_screenshot(region: str = "full", *, keep: bool = True) -> Dict[str, Any]:
    """Take a screenshot: region "full" (every screen) or "area" (the user picks one).
    `keep`: a screenshot the user asked for goes to their Pictures folder; one ELI takes to read
    the screen goes to its own data folder. Returns {ok, path, error}.

    Each OS and desktop has an ordered list of ways, each with a time limit and counted only when
    it wrote the picture:
      Windows   Pillow (GDI, all monitors); an area through Windows' own snip overlay.
      macOS     screencapture, then Pillow; says so when screen recording is not allowed.
      Linux     on Wayland (GNOME, KDE, Sway, Hyprland, any compositor): the desktop's screenshot
                portal, then grim (+slurp for an area), spectacle, gnome-screenshot.
                On X11 (any desktop): Pillow (XCB), then scrot, maim, ImageMagick's import,
                spectacle, gnome-screenshot, then the portal.
    """
    area = (region or "full").lower() != "full"
    path = _screenshot_path("Screenshot_area" if area else "Screenshot", keep=keep)

    if WINDOWS:
        result = _capture_windows_area(path) if area else _capture_with_imagegrab(path)
        if result:
            return result
        why = ("No area was snipped (Windows' snip overlay closed without a picture)." if area
               else "Windows did not give ELI a picture of the screen.")
        return {"ok": False, "error": why, "content": "Screenshot failed", "response": "Screenshot failed"}

    if MACOS:
        if _capture_with_tool(["screencapture", "-x"] + (["-i"] if area else []) + [path], path,
                              timeout=120 if area else 30) or (not area and _capture_with_imagegrab(path)):
            out = _saved(path)
            if _macos_screen_recording_allowed() is False:
                out["note"] = ("macOS has not allowed ELI to record the screen, so the picture shows the desktop "
                               "without its windows: allow ELI in System Settings › Privacy & Security › Screen "
                               "Recording.")
            return out
        return {"ok": False, "error": "screencapture did not produce a picture", "content": "Screenshot failed",
                "response": "Screenshot failed"}

    tried: list = []
    def _slurp_then_grim() -> bool:
        try:
            pick = subprocess.run(["slurp"], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return False
        geometry = (pick.stdout or "").strip()
        return pick.returncode == 0 and bool(geometry) and _capture_with_tool(["grim", "-g", geometry, path], path)

    if IS_WAYLAND:
        ways = [
            ("the desktop's screenshot portal", lambda: _capture_with_portal(path, interactive=area)),
            ("grim", lambda: (_slurp_then_grim() if _check_tool("slurp") else False) if area
                     else _capture_with_tool(["grim", path], path)),
            ("spectacle", lambda: _capture_with_tool(["spectacle", "-b", "-n", "-r" if area else "-f", "-o", path],
                                                     path, timeout=120 if area else 30)),
            ("gnome-screenshot", lambda: _capture_with_tool(
                ["gnome-screenshot"] + (["-a"] if area else []) + ["-f", path], path, timeout=120 if area else 30)),
        ]
        tools = {"grim": "grim", "spectacle": "spectacle", "gnome-screenshot": "gnome-screenshot"}
    else:
        ways = [
            ("Pillow", lambda: (not area) and bool(_capture_with_imagegrab(path))),
            ("scrot", lambda: _capture_with_tool(["scrot"] + (["-s"] if area else []) + [path], path,
                                                 timeout=120 if area else 30)),
            ("maim", lambda: _capture_with_tool(["maim"] + (["-s"] if area else []) + [path], path,
                                                timeout=120 if area else 30)),
            ("import", lambda: _capture_with_tool(["import"] + ([] if area else ["-window", "root"]) + [path], path,
                                                  timeout=120 if area else 30)),
            ("spectacle", lambda: _capture_with_tool(["spectacle", "-b", "-n", "-r" if area else "-f", "-o", path],
                                                     path, timeout=120 if area else 30)),
            ("gnome-screenshot", lambda: _capture_with_tool(
                ["gnome-screenshot"] + (["-a"] if area else []) + ["-f", path], path, timeout=120 if area else 30)),
            ("the desktop's screenshot portal", lambda: _capture_with_portal(path, interactive=area)),
        ]
        tools = {"scrot": "scrot", "maim": "maim", "import": "import", "spectacle": "spectacle",
                 "gnome-screenshot": "gnome-screenshot"}
    for name, way in ways:
        if name in tools and not _check_tool(tools[name]):
            continue
        tried.append(name)
        if way():
            return _saved(path)

    if IS_WAYLAND:
        advice = ("install your desktop's portal backend (xdg-desktop-portal-gnome, -kde, -wlr or -hyprland), "
                  "or grim on wlroots compositors")
    else:
        advice = "install scrot or maim"
    error = (f"No screenshot was taken ({'tried ' + ', '.join(tried) if tried else 'no capture tool was found'}); "
             f"{advice}.")
    return {"ok": False, "error": error, "content": "Screenshot failed", "response": "Screenshot failed"}


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
            log.debug("suppressed exception", exc_info=True)

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
                log.debug("suppressed exception", exc_info=True)
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
            log.debug("suppressed exception", exc_info=True)
    if _check_tool("xdotool"):
        try:
            subprocess.run(["xdotool", "key", keyname], check=True, capture_output=True)
            return {"ok": True, "content": f"Pressed {key}", "response": f"Pressed {key}"}
        except Exception as e:
            log.debug("suppressed exception", exc_info=True)
    return {"ok": False, "error": "No keyboard simulation tool found (install ydotool or xdotool)", "content": f"Failed to press {key}", "response": f"Failed to press {key}"}

def move_mouse(x: int, y: int) -> Dict[str, Any]:
    """Move the cursor to absolute screen coordinates (pyautogui → xdotool/ydotool)."""
    x, y = int(x), int(y)
    try:
        import pyautogui  # type: ignore
        pyautogui.moveTo(x, y)
        return {"ok": True, "content": f"Moved cursor to ({x},{y})", "response": f"Moved cursor to ({x},{y})"}
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    if IS_WAYLAND and _check_tool("ydotool"):
        try:
            subprocess.run(["ydotool", "mousemove", "--absolute", "-x", str(x), "-y", str(y)],
                           check=True, capture_output=True)
            return {"ok": True, "content": f"Moved cursor to ({x},{y})", "response": f"Moved cursor to ({x},{y})"}
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    if LINUX and _check_tool("xdotool"):
        try:
            subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=True, capture_output=True)
            return {"ok": True, "content": f"Moved cursor to ({x},{y})", "response": f"Moved cursor to ({x},{y})"}
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    return {"ok": False, "error": "No mouse tool (install xdotool or ydotool, or pyautogui).",
            "content": "Couldn't move the cursor.", "response": "Couldn't move the cursor."}


def mouse_click(button: str = "left", x: Optional[int] = None, y: Optional[int] = None,
                double: bool = False) -> Dict[str, Any]:
    """Click (optionally at x,y first). button: left|right|middle."""
    btn = str(button or "left").lower().strip()
    if x is not None and y is not None:
        move_mouse(x, y)
    _label = f"{'double-' if double else ''}{btn} click"
    try:
        import pyautogui  # type: ignore
        pyautogui.click(button=("right" if btn == "right" else "middle" if btn == "middle" else "left"),
                        clicks=2 if double else 1)
        return {"ok": True, "content": f"Performed {_label}", "response": f"Performed {_label}"}
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    _xbtn = {"left": "1", "middle": "2", "right": "3"}.get(btn, "1")
    if LINUX and _check_tool("xdotool"):
        try:
            subprocess.run(["xdotool", "click", "--repeat", "2" if double else "1", _xbtn],
                           check=True, capture_output=True)
            return {"ok": True, "content": f"Performed {_label}", "response": f"Performed {_label}"}
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    if IS_WAYLAND and _check_tool("ydotool"):
        _ybtn = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}.get(btn, "0xC0")
        try:
            args = ["ydotool", "click", _ybtn] + (["0xC0"] if double else [])
            subprocess.run(args, check=True, capture_output=True)
            return {"ok": True, "content": f"Performed {_label}", "response": f"Performed {_label}"}
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    return {"ok": False, "error": "No mouse tool (install xdotool or ydotool, or pyautogui).",
            "content": f"Couldn't {_label}.", "response": f"Couldn't {_label}."}


def gaze_click(button: str = "left", double: bool = False) -> Dict[str, Any]:
    """Click where the user is LOOKING — move the cursor to the live gaze point
    (from the gaze engine) and click. Requires gaze tracking to be running."""
    try:
        from eli.perception.gaze_engine import get_last_gaze, is_gaze_running
    except Exception as e:
        return {"ok": False, "error": f"gaze engine unavailable: {e}",
                "content": "Gaze tracking isn't available.", "response": "Gaze tracking isn't available."}
    try:
        if not is_gaze_running():
            return {"ok": False, "error": "gaze engine not running",
                    "content": "Gaze tracking isn't on — turn it on first.",
                    "response": "Gaze tracking isn't on — turn it on first."}
        g = get_last_gaze() or {}
        if "screen_x" not in g or "screen_y" not in g:
            return {"ok": False, "error": "no gaze fix",
                    "content": "I can't tell where you're looking right now.",
                    "response": "I can't tell where you're looking right now."}
        x, y = int(float(g["screen_x"])), int(float(g["screen_y"]))
        res = mouse_click(button=button, x=x, y=y, double=double)
        if res.get("ok"):
            _what = "opened" if double else f"{button}-clicked"
            res["content"] = res["response"] = f"{_what} where you're looking ({x},{y})"
        return res
    except Exception as e:
        return {"ok": False, "error": str(e),
                "content": "Gaze click failed.", "response": "Gaze click failed."}


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
            log.debug("suppressed exception", exc_info=True)
    if _check_tool("xdotool"):
        try:
            subprocess.run(["xdotool", "type", text], check=True, capture_output=True)
            return {"ok": True, "content": f"Typed: {text}", "response": f"Typed: {text}"}
        except Exception as e:
            log.debug("suppressed exception", exc_info=True)
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
            log.debug("suppressed exception", exc_info=True)
    return None
