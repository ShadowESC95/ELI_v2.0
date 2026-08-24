"""Desktop input and app-launch must not leak, and must work off X11.

Three defects from the live session logs, all in the same family -- a
convenience library used on a path where a subprocess is both safer and more
capable:

  * `platform.key_press()` and `type_text()` tried pyautogui FIRST on every
    platform with no native fallback in the function at all. On Linux that
    routes every keystroke through Xlib, which leaked a display socket and two
    file handles per call (the `Xlib/xauth.py ResourceWarning: unclosed file`
    entries), and under Wayland pyautogui cannot inject input at all, so there
    was no working path. MOUSE_CONTROL was already fixed to prefer native
    tools; this is the other half of the same feature.
  * `_popen()` discarded the Popen handle while the child was still running:
    "ResourceWarning: subprocess <pid> is still running" on every app launch.
    Worse than the warning, nothing ever reaped the child, so finished
    launches accumulated as zombies.
"""
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from eli.utils import platform_compat as pc
from eli.system import portable_app_control as pac


# ── keyboard: native first on Linux ────────────────────────────────────────
def test_key_press_prefers_native_tools_on_linux():
    import inspect
    src = inspect.getsource(pc.key_press)
    assert "_native_input_tool()" in src, "key_press no longer tries a native tool"
    idx_native = src.index("_native_input_tool()")
    idx_pyauto = src.index("import pyautogui")
    assert idx_native < idx_pyauto, "pyautogui is tried before the native tool again"


def test_type_text_prefers_native_tools_on_linux():
    import inspect
    src = inspect.getsource(pc.type_text)
    assert "_native_input_tool()" in src
    assert src.index("_native_input_tool()") < src.index("import pyautogui")


def test_wayland_selects_ydotool_over_xdotool(monkeypatch):
    """xdotool speaks X11 only; under Wayland it cannot reach native windows."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(pc.shutil, "which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr(pc, "LINUX", True)
    tool, proto = pc._native_input_tool()
    assert tool == "ydotool" and proto == "wayland"


def test_x11_selects_xdotool(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(pc.shutil, "which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr(pc, "LINUX", True)
    tool, proto = pc._native_input_tool()
    assert tool == "xdotool" and proto == "x11"


def test_native_tool_is_none_off_linux(monkeypatch):
    monkeypatch.setattr(pc, "LINUX", False)
    assert pc._native_input_tool() is None


@pytest.mark.parametrize("word,keysym", [
    ("enter", "Return"), ("escape", "Escape"), ("pageup", "Page_Up"),
    ("backspace", "BackSpace"), ("space", "space"), ("a", "a"),
])
def test_key_words_map_to_x_keysyms(word, keysym):
    """xdotool/ydotool take keysyms, not the lowercase words pyautogui accepts."""
    assert pc._xkey(word) == keysym


def test_empty_key_is_rejected():
    assert pc.key_press("") is False
    assert pc.type_text("") is False


# ── app launch: no warning, no zombies ─────────────────────────────────────
def test_launched_children_are_tracked_and_reaped():
    before = pac._reap_launched()
    assert pac._popen(["true"]) is True
    # The handle is retained while the child lives, which is what makes the
    # warning legitimate to silence rather than suppressed.
    assert len(pac._LAUNCHED) >= 1
    import time
    for _ in range(40):
        if pac._reap_launched() <= before:
            break
        time.sleep(0.05)
    assert pac._reap_launched() <= before, "finished child was never reaped"


def test_popen_emits_no_resource_warning():
    """The live log showed this on every OPEN_APP."""
    proc = subprocess.run(
        [sys.executable, "-W", "error::ResourceWarning", "-c",
         "import gc, time\n"
         "from eli.system.portable_app_control import _popen, _reap_launched\n"
         "[_popen(['true']) for _ in range(4)]\n"
         "gc.collect(); time.sleep(0.4); gc.collect()\n"
         "_reap_launched()\n"
         "print('ok')\n"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, timeout=180,
    )
    err = proc.stderr.decode("utf-8", "replace")
    assert "ResourceWarning" not in err, err[-400:]
    assert proc.returncode == 0, err[-400:]


def test_tracking_list_is_bounded():
    """A pathological loop must not grow the handle list without limit."""
    assert pac._MAX_TRACKED_LAUNCHES <= 256
    for _ in range(pac._MAX_TRACKED_LAUNCHES + 20):
        pac._LAUNCHED.append(type("P", (), {"poll": lambda self: None})())
    pac._reap_launched()
    assert len(pac._LAUNCHED) <= pac._MAX_TRACKED_LAUNCHES
    pac._LAUNCHED.clear()
