"""
Cross-platform compatibility layer for ELI.
All platform-specific operations should go through this module.

Usage:
    from eli.utils.platform_compat import platform

    platform.open_url("https://example.com")
    platform.open_file("/path/to/file")
    platform.notify("Title", "Message")
    platform.copy_to_clipboard("text")
    volume = platform.get_volume()
    platform.set_volume(75)
"""

import os
import sys
import shutil
import subprocess
import logging
from pathlib import Path

log = logging.getLogger(__name__)

RAW_PLATFORM = sys.platform.lower()


def _detect_android() -> bool:
    """Best-effort Android/Termux detection.

    CPython in Termux often reports sys.platform as "linux", so check the
    Android-specific environment and runtime hooks before treating it as Linux.
    """
    if RAW_PLATFORM.startswith("android"):
        return True
    if hasattr(sys, "getandroidapilevel"):
        return True
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return True
    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix


ANDROID = _detect_android()
LINUX = RAW_PLATFORM.startswith("linux") and not ANDROID
MACOS = RAW_PLATFORM == "darwin"
WINDOWS = RAW_PLATFORM in {"win32", "cygwin", "msys"}
FREEBSD = RAW_PLATFORM.startswith("freebsd")
OPENBSD = RAW_PLATFORM.startswith("openbsd")
NETBSD = RAW_PLATFORM.startswith("netbsd")
BSD = FREEBSD or OPENBSD or NETBSD
UNIX = (LINUX or MACOS or ANDROID or BSD) and not WINDOWS
POSIX = os.name == "posix"

PLATFORM_CANONICAL = {
    "win": "windows",
    "win32": "windows",
    "win64": "windows",
    "windows": "windows",
    "nt": "windows",
    "cygwin": "windows",
    "msys": "windows",
    "mingw": "windows",
    "mac": "macos",
    "macos": "macos",
    "macosx": "macos",
    "mac os": "macos",
    "mac os x": "macos",
    "osx": "macos",
    "darwin": "macos",
    "linux": "linux",
    "linux2": "linux",
    "gnu/linux": "linux",
    "ubuntu": "linux",
    "debian": "linux",
    "fedora": "linux",
    "arch": "linux",
    "android": "android",
    "termux": "android",
    "bionic": "android",
    "freebsd": "bsd",
    "openbsd": "bsd",
    "netbsd": "bsd",
    "bsd": "bsd",
    "unix": "unix",
    "posix": "posix",
}

PLATFORM_ALIASES = {
    "windows": ("windows", "win", "win32", "win64", "nt", "cygwin", "msys", "mingw"),
    "macos": ("macos", "mac", "darwin", "osx", "mac os", "mac os x"),
    "linux": ("linux", "linux2", "gnu/linux", "ubuntu", "debian", "fedora", "arch"),
    "android": ("android", "termux", "bionic"),
    "bsd": ("bsd", "freebsd", "openbsd", "netbsd"),
    "unix": ("unix", "posix"),
}

COMMON_APP_ALIASES = {
    "browser": "browser",
    "web browser": "browser",
    "mail": "mail",
    "email": "mail",
    "e-mail": "mail",
    "files": "files",
    "file manager": "files",
    "finder": "files",
    "explorer": "files",
    "terminal": "terminal",
    "term": "terminal",
    "shell": "terminal",
    "settings": "settings",
    "system settings": "settings",
    "calculator": "calculator",
    "calc": "calculator",
    "calendar": "calendar",
    "notes": "notes",
    "notepad": "notes",
    "text editor": "editor",
    "editor": "editor",
    "camera": "camera",
    "photos": "photos",
    "pictures": "photos",
    "music": "music",
}

APP_ALIASES_BY_PLATFORM = {
    "linux": {
        "browser": "xdg-open",
        "mail": "thunderbird",
        "files": "xdg-open",
        "terminal": "x-terminal-emulator",
        "settings": "gnome-control-center",
        "calculator": "gnome-calculator",
        "calendar": "gnome-calendar",
        "notes": "gedit",
        "editor": "gedit",
        "camera": "snapshot",
        "photos": "eog",
        "music": "rhythmbox",
        "chrome": "google-chrome",
        "google chrome": "google-chrome",
        "chromium": "chromium",
        "firefox": "firefox",
        "vscode": "code",
        "vs code": "code",
        "visual studio code": "code",
        "codium": "codium",
        "sublime": "subl",
        "sublime text": "subl",
    },
    "macos": {
        "browser": "Safari",
        "mail": "Mail",
        "files": "Finder",
        "terminal": "Terminal",
        "settings": "System Settings",
        "calculator": "Calculator",
        "calendar": "Calendar",
        "notes": "Notes",
        "editor": "TextEdit",
        "camera": "Photo Booth",
        "photos": "Photos",
        "music": "Music",
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "firefox": "Firefox",
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "sublime": "Sublime Text",
        "sublime text": "Sublime Text",
    },
    "windows": {
        "browser": "msedge.exe",
        "mail": "outlook.exe",
        "files": "explorer.exe",
        "terminal": "wt.exe",
        "powershell": "powershell.exe",
        "cmd": "cmd.exe",
        "settings": "ms-settings:",
        "calculator": "calc.exe",
        "calendar": "outlookcal:",
        "notes": "notepad.exe",
        "editor": "notepad.exe",
        "camera": "microsoft.windows.camera:",
        "photos": "ms-photos:",
        "music": "mswindowsmusic:",
        "edge": "msedge.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "vscode": "code.cmd",
        "vs code": "code.cmd",
        "visual studio code": "code.cmd",
    },
    "android": {
        "browser": "com.android.chrome",
        "chrome": "com.android.chrome",
        "firefox": "org.mozilla.firefox",
        "files": "com.google.android.documentsui",
        "terminal": "com.termux",
        "settings": "com.android.settings",
        "calculator": "com.google.android.calculator",
        "calendar": "com.google.android.calendar",
        "notes": "com.google.android.keep",
        "camera": "com.android.camera",
        "photos": "com.google.android.apps.photos",
        "music": "com.google.android.music",
        "termux": "com.termux",
    },
    "bsd": {
        "browser": "xdg-open",
        "files": "xdg-open",
        "terminal": "xterm",
        "settings": "settings",
        "calculator": "xcalc",
        "editor": "vi",
    },
}


def normalize_platform(name: str | None = None) -> str:
    """Normalize OS names and aliases to a stable canonical platform string."""
    if name is None:
        if ANDROID:
            return "android"
        if WINDOWS:
            return "windows"
        if MACOS:
            return "macos"
        if LINUX:
            return "linux"
        if BSD:
            return "bsd"
        if UNIX:
            return "unix"
        return "unknown"
    key = " ".join(str(name).strip().lower().replace("_", " ").replace("-", " ").split())
    return PLATFORM_CANONICAL.get(key, key or "unknown")


def platform_aliases(name: str | None = None) -> tuple[str, ...]:
    """Return accepted aliases for a platform."""
    return PLATFORM_ALIASES.get(normalize_platform(name), ())


def app_aliases(name: str | None = None) -> dict[str, str]:
    """Return app aliases for the current or requested platform."""
    platform = normalize_platform(name)
    aliases = dict(COMMON_APP_ALIASES)
    aliases.update(APP_ALIASES_BY_PLATFORM.get(platform, {}))
    return aliases


def normalize_app_name(name: str, platform_name: str | None = None) -> str:
    """Normalize a spoken app name to a platform-appropriate launcher name."""
    raw = " ".join(str(name or "").strip().lower().split())
    if not raw:
        return ""
    return app_aliases(platform_name).get(raw, raw)


def open_url(url: str) -> bool:
    """Open a URL in the default browser. Cross-platform."""
    import webbrowser
    try:
        if ANDROID and shutil.which("termux-open-url"):
            subprocess.Popen(["termux-open-url", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        webbrowser.open(url)
        return True
    except Exception as e:
        log.warning(f"Failed to open URL: {e}")
        return False


def open_file(path: str | Path) -> bool:
    """Open a file with the system default application."""
    path = str(path)
    try:
        if ANDROID and shutil.which("termux-open"):
            subprocess.Popen(["termux-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif WINDOWS:
            os.startfile(path)
        elif MACOS:
            subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return False
        return True
    except Exception as e:
        log.warning(f"Failed to open file {path}: {e}")
        return False


def open_app(app_name: str) -> bool:
    """Open an application using the current OS launcher conventions."""
    app = normalize_app_name(app_name)
    if not app:
        return False
    try:
        if ANDROID:
            if shutil.which("monkey"):
                subprocess.Popen(["monkey", "-p", app, "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if shutil.which("am"):
                subprocess.Popen(
                    ["am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", app],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            return False
        if WINDOWS:
            if app.endswith(":") or app.startswith(("ms-", "shell:")):
                os.startfile(app)
                return True
            exe = shutil.which(app) or shutil.which(f"{app}.exe")
            subprocess.Popen([exe or app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if MACOS:
            subprocess.Popen(["open", "-a", app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        executable = shutil.which(app)
        if executable:
            subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if app == "xdg-open":
            return open_file(Path.home())
    except Exception as e:
        log.warning(f"Failed to open app {app_name!r}: {e}")
    return False


def notify(title: str, message: str) -> bool:
    """Show a desktop notification."""
    try:
        if LINUX:
            if shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", title, message],
                    timeout=5, capture_output=True
                )
                return True
        elif ANDROID:
            if shutil.which("termux-notification"):
                subprocess.run(
                    ["termux-notification", "--title", title, "--content", message],
                    timeout=5, capture_output=True
                )
                return True
        elif MACOS:
            subprocess.run(
                ["osascript", "-e",
                 'display notification "' + message + '" with title "' + title + '"'],
                timeout=5, capture_output=True
            )
            return True
        elif WINDOWS:
            try:
                from plyer import notification
                notification.notify(title=title, message=message, timeout=5)
                return True
            except ImportError:
                log.debug("plyer not installed, skipping Windows notification")
        return False
    except Exception as e:
        log.warning(f"Notification failed: {e}")
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard."""
    try:
        if ANDROID:
            if shutil.which("termux-clipboard-set"):
                p = subprocess.Popen(["termux-clipboard-set"], stdin=subprocess.PIPE, text=True)
                p.communicate(text)
                return p.returncode == 0
        elif LINUX:
            if shutil.which("wl-copy"):
                p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
                p.communicate(text)
                return p.returncode == 0
            elif shutil.which("xclip"):
                p = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE, text=True
                )
                p.communicate(text)
                return p.returncode == 0
            elif shutil.which("xsel"):
                p = subprocess.Popen(
                    ["xsel", "--clipboard", "--input"],
                    stdin=subprocess.PIPE, text=True
                )
                p.communicate(text)
                return p.returncode == 0
        elif MACOS:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            p.communicate(text)
            return p.returncode == 0
        elif WINDOWS:
            clip = shutil.which("clip") or shutil.which("clip.exe")
            if not clip:
                return False
            subprocess.run(
                [clip], input=text, text=True, check=True, capture_output=True
            )
            return True
        return False
    except Exception as e:
        log.warning(f"Clipboard copy failed: {e}")
        return False


def get_clipboard() -> str:
    """Get text from system clipboard."""
    try:
        if ANDROID:
            if shutil.which("termux-clipboard-get"):
                return subprocess.check_output(
                    ["termux-clipboard-get"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
        elif LINUX:
            if shutil.which("wl-paste"):
                return subprocess.check_output(
                    ["wl-paste", "--no-newline"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
            elif shutil.which("xclip"):
                return subprocess.check_output(
                    ["xclip", "-selection", "clipboard", "-o"],
                    text=True, stderr=subprocess.DEVNULL
                ).strip()
            elif shutil.which("xsel"):
                return subprocess.check_output(
                    ["xsel", "--clipboard", "--output"],
                    text=True
                ).strip()
        elif MACOS:
            return subprocess.check_output(["pbpaste"], text=True).strip()
        elif WINDOWS:
            return subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                text=True
            ).strip()
    except Exception as e:
        log.warning(f"Clipboard read failed: {e}")
    return ""


def get_volume() -> int | None:
    """Get current system volume (0-100). Returns None if unavailable."""
    try:
        if ANDROID:
            return None
        if LINUX:
            if shutil.which("pactl"):
                out = subprocess.check_output(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    text=True, stderr=subprocess.DEVNULL
                )
                import re
                m = re.search(r"(\d+)%", out)
                return int(m.group(1)) if m else None
        elif MACOS:
            out = subprocess.check_output(
                ["osascript", "-e", "output volume of (get volume settings)"],
                text=True
            )
            return int(out.strip())
        elif WINDOWS:
            return _windows_get_volume()
    except Exception as e:
        log.debug(f"Volume query failed: {e}")
    return None


def set_volume(level: int) -> bool:
    """Set system volume (0-100)."""
    level = max(0, min(100, level))
    try:
        if ANDROID:
            return False
        if LINUX:
            if shutil.which("pactl"):
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                    check=True, capture_output=True
                )
                return True
        elif MACOS:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                check=True, capture_output=True
            )
            return True
        elif WINDOWS:
            return _windows_set_volume(level)
    except Exception as e:
        log.warning(f"Set volume failed: {e}")
    return False


def adjust_volume(delta: int) -> bool:
    """Adjust system volume by delta (e.g., +10, -5)."""
    try:
        if ANDROID:
            return False
        if LINUX and shutil.which("pactl"):
            sign = "+" if delta > 0 else "-"
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{abs(delta)}%"],
                check=True, capture_output=True
            )
            return True
        elif MACOS:
            current = get_volume()
            if current is not None:
                return set_volume(current + delta)
        elif WINDOWS:
            current = get_volume()
            if current is not None:
                return set_volume(current + delta)
    except Exception as e:
        log.warning(f"Adjust volume failed: {e}")
    return False


def _windows_volume_interface():
    """Return a pycaw speaker endpoint volume object when pycaw is installed."""
    if not WINDOWS:
        return None
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        log.debug(f"Windows volume backend unavailable: {e}")
        return None


def _windows_get_volume() -> int | None:
    volume = _windows_volume_interface()
    if volume is None:
        return None
    try:
        return int(round(float(volume.GetMasterVolumeLevelScalar()) * 100))
    except Exception as e:
        log.debug(f"Windows volume read failed: {e}")
        return None


def _windows_set_volume(level: int) -> bool:
    volume = _windows_volume_interface()
    if volume is None:
        return False
    try:
        volume.SetMasterVolumeLevelScalar(max(0, min(100, int(level))) / 100.0, None)
        return True
    except Exception as e:
        log.debug(f"Windows volume set failed: {e}")
        return False


def set_muted(muted: bool) -> bool:
    """Set system mute state where the platform exposes a reliable local API."""
    try:
        if ANDROID:
            return False
        if LINUX:
            if shutil.which("pactl"):
                subprocess.run(
                    ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"],
                    check=True, capture_output=True
                )
                return True
        elif MACOS:
            subprocess.run(
                ["osascript", "-e", f"set volume output muted {'true' if muted else 'false'}"],
                check=True, capture_output=True
            )
            return True
        elif WINDOWS:
            volume = _windows_volume_interface()
            if volume is not None:
                volume.SetMute(1 if muted else 0, None)
                return True
    except Exception as e:
        log.warning(f"Mute control failed: {e}")
    return False


def play_sound(path: str | Path) -> bool:
    """Play an audio file. Best-effort cross-platform."""
    path = str(path)
    try:
        if ANDROID:
            if shutil.which("termux-media-player"):
                subprocess.Popen(
                    ["termux-media-player", "play", path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return True
        elif LINUX:
            if shutil.which("paplay"):
                subprocess.Popen(
                    ["paplay", path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return True
            elif shutil.which("aplay"):
                subprocess.Popen(
                    ["aplay", path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return True
        elif MACOS:
            subprocess.Popen(
                ["afplay", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
        elif WINDOWS:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
    except Exception as e:
        log.warning(f"Play sound failed: {e}")
    return False


def find_executable(name: str, extra_paths: list[str] | None = None) -> str | None:
    """Find an executable on PATH, with optional extra search directories."""
    result = shutil.which(name)
    if result:
        return result
    if extra_paths:
        for p in extra_paths:
            candidate = Path(p) / name
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
            # Windows: try with .exe
            if WINDOWS:
                candidate = Path(p) / f"{name}.exe"
                if candidate.exists():
                    return str(candidate)
    return None


def user_documents_dir() -> Path:
    """Cross-platform user documents directory."""
    if ANDROID:
        sdcard = Path("/sdcard/Documents")
        return sdcard if sdcard.exists() else Path.home() / "Documents"
    if WINDOWS:
        return Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    elif MACOS:
        return Path.home() / "Documents"
    else:
        return Path.home() / "Documents"


def user_pictures_dir() -> Path:
    """Cross-platform user pictures directory."""
    if ANDROID:
        sdcard = Path("/sdcard/Pictures")
        return sdcard if sdcard.exists() else Path.home() / "Pictures"
    if WINDOWS:
        return Path(os.environ.get("USERPROFILE", Path.home())) / "Pictures"
    elif MACOS:
        return Path.home() / "Pictures"
    else:
        return Path.home() / "Pictures"


def key_press(key: str) -> bool:
    """Best-effort cross-platform key press using pyautogui when available."""
    try:
        import pyautogui  # type: ignore

        pyautogui.press(key)
        return True
    except Exception as e:
        log.debug(f"pyautogui key press failed: {e}")
    return False


def type_text(text: str) -> bool:
    """Best-effort cross-platform text entry using pyautogui when available."""
    try:
        import pyautogui  # type: ignore

        pyautogui.write(text)
        return True
    except Exception as e:
        log.debug(f"pyautogui type failed: {e}")
    return False

# --- Platform detection functions (added for audit) ---
def is_linux() -> bool:
    """Return True if running on Linux."""
    return LINUX

def is_android() -> bool:
    """Return True if running on Android or Termux."""
    return ANDROID

def is_macos() -> bool:
    """Return True if running on macOS."""
    return MACOS

def is_windows() -> bool:
    """Return True if running on Windows."""
    return WINDOWS

def is_bsd() -> bool:
    """Return True if running on a BSD platform."""
    return BSD

def is_unix() -> bool:
    """Return True for Unix-like platforms."""
    return UNIX

# --- Alias for audit compatibility ---
def is_mac() -> bool:
    """Return True if running on macOS (alias for is_macos)."""
    return is_macos()

# --- get_platform for audit compatibility ---
def get_platform() -> str:
    """Return current canonical platform name."""
    return normalize_platform()

# --- Added for audit compatibility ---
def open_file_manager(path: str = None) -> bool:
    """Open the system file manager at the given path (or home if None)."""
    import os

    target = os.path.expanduser(path or "~")
    if ANDROID:
        if shutil.which("termux-open"):
            try:
                subprocess.Popen(["termux-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False
        return False
    if WINDOWS:
        try:
            os.startfile(target)
            return True
        except Exception:
            return False
    if MACOS:
        try:
            subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
    if shutil.which("nautilus"):
        subprocess.Popen(["nautilus", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    elif shutil.which("dolphin"):
        subprocess.Popen(["dolphin", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    elif shutil.which("thunar"):
        subprocess.Popen(["thunar", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    elif shutil.which("pcmanfm"):
        subprocess.Popen(["pcmanfm", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    return False

# --- Missing functions for audit compatibility ---
def get_config_dir() -> str:
    """Return the platform-specific config directory."""
    from eli.core.paths import config_dir
    return str(config_dir())

def get_data_dir() -> str:
    """Return the platform-specific data directory."""
    from eli.core.paths import data_dir
    return str(data_dir())

def get_cache_dir() -> str:
    """Return the platform-specific cache directory."""
    from eli.core.paths import cache_dir
    return str(cache_dir())

def get_log_dir() -> str:
    """Return the platform-specific log directory."""
    from eli.core.paths import logs_dir
    return str(logs_dir())
