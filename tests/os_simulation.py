"""Run every OS-facing capability through ELI's real dispatch as if on Windows, macOS or Linux, and
record every program it would start (tests/test_every_capability_on_every_os.py runs it).

Nothing is started and nothing reaches the desktop: subprocess, os.system, os.startfile, webbrowser,
pyautogui and plyer are replaced by recorders, and audio and D-Bus modules are hidden. It patches
sys.platform and ELI's OS flags for the whole process, so it always runs in a process of its own.
Usage: python tests/os_simulation.py <repo> <windows|macos|linux> <out.json>
"""
import json
import os

# The simulator may import GUI-capable ELI modules while pretending to be
# another OS. Never let Qt attempt to attach to the real desktop/display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import platform as _platform
import subprocess
import sys
import types

REPO, OS_NAME, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, REPO)

LINUX_ONLY = {
    "playerctl", "wmctrl", "xdotool", "ydotool", "pactl", "amixer", "wpctl", "gsettings", "dbus-send",
    "gdbus", "notify-send", "xdg-open", "xdg-email", "xclip", "xsel", "wl-copy", "wl-paste", "paplay",
    "aplay", "pw-play", "nmcli", "systemctl", "loginctl", "xrandr", "lscpu", "xprop", "xdpyinfo",
    "gnome-control-center", "systemsettings", "systemsettings5", "pavucontrol", "nautilus", "zenity",
    "gnome-screenshot", "grim", "slurp", "scrot", "spectacle", "gtk-launch", "kdotool", "wlrctl",
    "xfce4-settings-manager", "mate-control-center", "cinnamon-settings", "kcmshell5", "gedit", "kate",
    "thunderbird", "evolution", "geary", "flatpak", "snap", "top", "pgrep", "pkill", "espeak-ng",
    "espeak", "spd-say", "xfce4-power-manager-settings", "mate-volume-control", "xfce4-mixer",
}
if OS_NAME == "macos":
    LINUX_ONLY -= {"pgrep", "pkill"}  # macOS has its own
HAVE = {
    "windows": {"powershell", "cmd", "explorer", "clip", "notepad", "tasklist", "taskkill", "code"},
    "macos": {"osascript", "open", "pbcopy", "pbpaste", "screencapture", "say", "afplay", "pmset",
              "pgrep", "pkill", "code", "top"},
    "linux": None,  # everything
}[OS_NAME]

calls = []


class _Done:
    returncode = 0
    stdout = ""
    stderr = ""
    pid = 4242

    def __init__(self, *a, **k):
        pass

    def communicate(self, *a, **k):
        return ("", "")

    def wait(self, *a, **k):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass

    def terminate(self):
        pass


def _record(kind, args, kwargs):
    argv = args[0] if args else kwargs.get("args")
    if isinstance(argv, (list, tuple)):
        argv = [str(x) for x in argv]
    else:
        argv = [str(argv)]
    calls.append({"kind": kind, "argv": argv[:12], "shell": bool(kwargs.get("shell"))})


def _run(*a, **k):
    _record("run", a, k)
    d = _Done()
    if k.get("text") or k.get("universal_newlines") or k.get("encoding"):
        return d
    d.stdout, d.stderr = b"", b""
    return d


def _popen(*a, **k):
    _record("popen", a, k)
    return _Done()


def _check_output(*a, **k):
    _record("check_output", a, k)
    return "" if (k.get("text") or k.get("universal_newlines") or k.get("encoding")) else b""


def _call(*a, **k):
    _record("call", a, k)
    return 0


subprocess.run, subprocess.Popen, subprocess.check_output = _run, _popen, _check_output
subprocess.call, subprocess.check_call = _call, _call
os.system = lambda cmd: (calls.append({"kind": "os.system", "argv": [str(cmd)], "shell": True}) or 0)
os.startfile = lambda path, *a: calls.append({"kind": "startfile", "argv": [str(path)], "shell": False})
import webbrowser  # noqa: E402
webbrowser.open = lambda url, *a, **k: (calls.append({"kind": "webbrowser", "argv": [str(url)], "shell": False}) or True)
webbrowser.open_new_tab = webbrowser.open
fake_gui = types.ModuleType("pyautogui")
for _fn in ("press", "hotkey", "write", "typewrite", "click", "moveTo", "moveRel", "move", "scroll",
            "doubleClick", "rightClick", "keyDown", "keyUp", "dragTo", "mouseDown", "mouseUp"):
    setattr(fake_gui, _fn, (lambda name: (lambda *a, **k: calls.append(
        {"kind": "pyautogui", "argv": [name] + [str(x) for x in a], "shell": False})))(_fn))
fake_gui.size = lambda: (1920, 1080)
fake_gui.position = lambda: (10, 10)
fake_gui.screenshot = lambda *a, **k: None
fake_gui.FAILSAFE = False
sys.modules["pyautogui"] = fake_gui
fake_plyer = types.ModuleType("plyer")
fake_plyer.notification = types.SimpleNamespace(notify=lambda **k: calls.append(
    {"kind": "plyer", "argv": ["plyer.notify", str(k.get("title"))], "shell": False}))
sys.modules["plyer"] = fake_plyer
for _m in ("sounddevice", "simpleaudio", "pynput", "pynput.keyboard", "pynput.mouse", "jeepney", "dbus", "pulsectl"):
    sys.modules[_m] = None  # never reach the real desktop from the harness

import shutil  # noqa: E402
_real_which = shutil.which


def _which(name, *a, **k):
    base = os.path.basename(str(name))
    if HAVE is None:
        return _real_which(name, *a, **k) or f"/usr/bin/{base}"
    return (f"C:\\Windows\\System32\\{base}.exe" if OS_NAME == "windows" else f"/usr/bin/{base}") \
        if base in HAVE else None


shutil.which = _which

from eli.utils import platform_compat as pc  # noqa: E402
if OS_NAME != "linux":
    pc.LINUX = False
    pc.ANDROID = False
    pc.WINDOWS = OS_NAME == "windows"
    pc.MACOS = OS_NAME == "macos"
    pc.RAW_PLATFORM = "win32" if pc.WINDOWS else "darwin"
    for k in ("IS_WAYLAND", "IS_X11", "IS_GNOME", "IS_KDE"):
        if hasattr(pc, k):
            setattr(pc, k, False)

from eli.execution import executor_enhanced as ex  # noqa: E402

if OS_NAME != "linux":
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "") or ""
        if not name.startswith("eli"):
            continue
        for k, v in (("LINUX", False), ("WINDOWS", OS_NAME == "windows"), ("MACOS", OS_NAME == "macos"),
                     ("ANDROID", False), ("IS_WAYLAND", False), ("IS_GNOME", False), ("IS_KDE", False)):
            if hasattr(mod, k) and isinstance(getattr(mod, k), bool):
                setattr(mod, k, v)
    sys.platform = "win32" if OS_NAME == "windows" else "darwin"
    _platform.system = lambda: "Windows" if OS_NAME == "windows" else "Darwin"

ACTIONS = [
    ("OPEN_APP", {"name": "settings"}), ("OPEN_APP", {"name": "spotify"}), ("CLOSE_APP", {"name": "settings"}),
    ("CLOSE_APP", {"name": "spotify"}), ("FOCUS_APP", {"name": "spotify"}), ("MINIMIZE_APP", {"name": "spotify"}),
    ("MAXIMISE_WINDOW", {"name": "spotify"}), ("MAXIMISE_WINDOW", {}), ("MINIMISE_ALL", {}),
    ("RESTORE_WINDOWS", {}), ("TILE_WINDOWS", {}), ("NEXT_WINDOW", {}), ("PREVIOUS_WINDOW", {}),
    ("SWITCH_WORKSPACE", {"direction": "right"}),
    ("PLAY_MEDIA", {}), ("PAUSE_MEDIA", {}), ("STOP_MEDIA", {}), ("NEXT_MEDIA", {}), ("PREVIOUS_MEDIA", {}),
    ("NOW_PLAYING", {}), ("SHUFFLE_MEDIA", {}), ("REPEAT_MEDIA", {}), ("MEDIA_CONTROL", {"command": "pause"}),
    ("VOLUME", {"direction": "up", "delta": 10}), ("VOLUME", {"level": 30}),
    ("GET_CLIPBOARD", {}), ("SET_CLIPBOARD", {"text": "hello"}),
    ("KEYBOARD", {"key": "enter"}), ("KEYBOARD", {"type": "hello"}), ("MOUSE_CONTROL", {"action": "click"}),
    ("SCREENSHOT", {}), ("SCREENSHOT", {"region": "area"}),
    ("OPEN_SYSTEM_SETTINGS", {}), ("OPEN_POWER_SETTINGS", {}), ("OPEN_AUDIO_SETTINGS", {}),
    ("OPEN_COMMUNICATION_HUB", {}), ("OPEN_MEDIA_HUB", {}), ("OPEN_FILE_SYSTEM", {"path": "~"}),
    ("OPEN_BROWSER", {"url": "https://example.org"}), ("OPEN_URL", {"url": "https://example.org"}),
    ("OPEN_NETWORK_BROWSER", {}), ("OPEN_IDE", {}), ("OPEN_IN_IDE", {"path": "notes.txt"}),
    ("RUN_CMD", {"cmd": "echo hi"}), ("SHELL_EXEC", {"cmd": "echo hi"}),
    ("CPU_USAGE", {}), ("RAM_USAGE", {}), ("SYSTEM_STATS", {}), ("GPU_STATUS", {}),
    ("SET_TIMER", {"seconds": 1, "label": "t"}), ("SKIP_YOUTUBE_AD", {}),
    ("LIST_DIR", {"path": "~"}),
]

results = []
for action, args in ACTIONS:
    calls.clear()
    try:
        r = ex.execute(action, dict(args))
        r = r if isinstance(r, dict) else {"ok": bool(r), "content": str(r)}
        msg = str(r.get("content") or r.get("response") or r.get("error") or "")[:160]
        ok = bool(r.get("ok"))
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"EXCEPTION {type(e).__name__}: {e}"[:160]
    progs = [os.path.basename(c["argv"][0].replace("\\", "/").split()[0]) if c["argv"] and c["argv"][0] else ""
             for c in calls]
    bad = sorted({p for p in progs if OS_NAME != "linux" and p.replace(".exe", "") in LINUX_ONLY})
    results.append({"action": action, "args": args, "ok": ok, "msg": msg,
                    "calls": [" ".join(c["argv"]) for c in calls][:8], "linux_only": bad})
json.dump(results, open(OUT, "w"), indent=1)
print("done", OS_NAME, len(results))
