"""Cross-platform system helpers shared by executor and effectors (v3).

Leaf module — no imports from executor_enhanced to avoid circular dependencies.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from eli.utils.log import get_logger

log = get_logger(__name__)


def browser_user_dir() -> Path:
    try:
        from eli.core.paths import get_paths
        base = Path(get_paths().config_dir)
    except Exception:
        base = Path.home() / ".config" / "eli"
    return (base / "browser").expanduser().resolve()


def open_app_with_timeout(argv, timeout=30):
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=0.7)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": out,
                "stderr": err,
                "argv": argv,
            }
        except subprocess.TimeoutExpired:
            return {"ok": True, "spawned": True, "pid": proc.pid, "argv": argv}
    except Exception as e:
        return {"ok": False, "error": repr(e), "argv": argv}


def open_file_system(path: str = "~") -> Dict[str, Any]:
    try:
        from eli.utils.platform_compat import open_file
        target = os.path.expanduser(path)
        if open_file(target):
            msg = f"Opened folder: {target}"
            return {"ok": True, "action": "OPEN_FILE_SYSTEM", "path": target,
                    "content": msg, "response": msg}
        msg = f"Could not open folder: {target}"
        return {"ok": False, "action": "OPEN_FILE_SYSTEM", "path": target,
                "content": msg, "response": msg}
    except Exception as e:
        msg = "Failed to open file system."
        return {"ok": False, "action": "OPEN_FILE_SYSTEM", "error": repr(e),
                "content": msg, "response": msg}


def open_browser(url: str = "https://duckduckgo.com", urls: list | None = None) -> Dict[str, Any]:
    try:
        from eli.utils.platform_compat import open_url
        targets = [str(u) for u in (urls or []) if str(u).strip()]
        if not targets:
            targets = [str(url)]
        opened = 0
        for target in targets:
            if open_url(target):
                opened += 1
        if opened == 0:
            msg = (
                "Couldn't open the browser — it may be hung or missing. "
                "On Linux set ELI_BROWSER=chromium or close Firefox and try again."
            )
            return {"ok": False, "action": "OPEN_BROWSER", "content": msg, "response": msg}
        if len(targets) == 1:
            msg = f"Opened browser: {targets[0]}"
            return {"ok": True, "action": "OPEN_BROWSER", "url": targets[0],
                    "content": msg, "response": msg}
        msg = f"Opened {opened} browser tab(s)."
        return {"ok": True, "action": "OPEN_BROWSER", "urls": targets,
                "content": msg, "response": msg}
    except Exception as e:
        msg = f"Failed to open browser: {e}"
        return {"ok": False, "action": "OPEN_BROWSER", "error": repr(e),
                "content": msg, "response": msg}


def _run_ok(argv, timeout=2.0) -> bool:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def volume_fallback(direction: str, delta: int = 10, level: int | None = None) -> Dict[str, Any]:
    """Linux volume fallback when platform_compat is insufficient."""
    direction = (direction or "").strip().lower()
    try:
        from eli.utils.platform_compat import adjust_volume, get_volume, set_volume, set_muted
        if direction == "set" and level is not None:
            if set_volume(int(level)):
                msg = f"Volume set to {int(level)}%"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction in ("up", "raise"):
            if adjust_volume(int(delta)):
                msg = "Volume up"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction in ("down", "lower"):
            if adjust_volume(-int(delta)):
                msg = "Volume down"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction == "mute":
            if set_muted(True):
                msg = "Muted"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction == "unmute":
            if set_muted(False):
                msg = "Unmuted"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction == "get":
            vol = get_volume()
            if vol is not None:
                msg = f"Volume is {vol}%"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
    except Exception as e:
        return {"ok": False, "action": "VOLUME", "error": str(e),
                "content": str(e), "response": str(e)}

    # Legacy direct-tool path (kept for environments where platform_compat misses)
    try:
        if direction == "set" and level is not None:
            if shutil.which("wpctl") and _run_ok(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{int(level)}%"]
            ):
                msg = f"Volume set to {int(level)}%"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
            if shutil.which("pactl") and _run_ok(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(level)}%"]
            ):
                msg = f"Volume set to {int(level)}%"
                return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction in ("up", "raise"):
            for tool, argv in (
                ("wpctl", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{int(delta)}%+"]),
                ("pactl", ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{int(delta)}%"]),
                ("amixer", ["amixer", "-D", "pulse", "sset", "Master", f"{int(delta)}%+"]),
            ):
                if shutil.which(tool) and _run_ok(argv):
                    msg = "Volume up"
                    return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
        if direction in ("down", "lower"):
            for tool, argv in (
                ("wpctl", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{int(delta)}%-"]),
                ("pactl", ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{int(delta)}%"]),
                ("amixer", ["amixer", "-D", "pulse", "sset", "Master", f"{int(delta)}%-"]),
            ):
                if shutil.which(tool) and _run_ok(argv):
                    msg = "Volume down"
                    return {"ok": True, "action": "VOLUME", "content": msg, "response": msg}
    except Exception as e:
        return {"ok": False, "action": "VOLUME", "error": str(e),
                "content": str(e), "response": str(e)}

    msg = "Volume control failed — no wpctl, pactl, or amixer available"
    return {"ok": False, "action": "VOLUME", "content": msg, "response": msg}
