#!/usr/bin/env python3
"""
ELI ambient vision — optional periodic screen glances for rolling awareness.

OFF by default. When `ambient_vision_enabled` is true, a background thread
captures the screen every `ambient_vision_interval` seconds, runs the local
vision model on it, and stores a short description as memory so ELI has a
rolling sense of what the user is doing.

Because the 7B vision model hot-swaps with the text model (see vision.py), each
glance briefly unloads the text model. To avoid stealing the model mid-thought,
a glance is SKIPPED whenever the shared LLM lock is busy (i.e. ELI is generating
a reply). The toggle and interval are re-read every cycle, so they take effect
without restarting ELI.

Public API:
    start_ambient_vision()           -> starts the guarded background thread (idempotent)
    stop_ambient_vision()            -> stops the thread
    set_ambient_vision(enabled)      -> persist toggle + start/stop accordingly
    ambient_vision_status()          -> dict snapshot for GUI/diagnostics
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict

try:
    from eli.utils.log import get_logger  # type: ignore
    log = get_logger("eli.ambient_vision")
except Exception:  # pragma: no cover
    import logging
    log = logging.getLogger("eli.ambient_vision")


_thread: "threading.Thread | None" = None
_start_lock = threading.Lock()
_stop_event = threading.Event()
_state: Dict[str, Any] = {
    "running": False,
    "last_glance_ts": 0.0,
    "last_glance_ok": None,
    "last_glance_text": "",
    "glances": 0,
    "last_skip_reason": "",
}

_MIN_INTERVAL = 60  # never glance more often than once a minute


def _cfg(key: str, default: Any = None) -> Any:
    try:
        from eli.core import config
        v = config.get(key, default)
        return default if v is None else v
    except Exception:
        return default


def _enabled() -> bool:
    return bool(_cfg("ambient_vision_enabled", False))


def _interval() -> int:
    try:
        return max(_MIN_INTERVAL, int(_cfg("ambient_vision_interval", 300)))
    except Exception:
        return 300


def _llm_busy() -> bool:
    """True if the text model lock is currently held (ELI is generating)."""
    try:
        from eli.cognition import gguf_inference as gi
        lock = getattr(gi, "_LLM_CALL_LOCK", None)
        if lock is None:
            return False
        if lock.acquire(blocking=False):
            lock.release()
            return False
        return True
    except Exception:
        return False


_LARGE_MODEL_GB = 8.0
_LARGE_MODEL_IDLE_S = 900.0


def _swap_is_expensive() -> bool:
    """True when a glance would unload and reload a large chat model, as it does unless the vision model runs beside it."""
    try:
        if bool(_cfg("vision_fast_no_swap", False)):
            return False
        import json
        from pathlib import Path
        from eli.core.paths import get_paths
        snap = json.loads((Path(get_paths().artifacts_dir) / "runtime_snapshot.json").read_text(encoding="utf-8"))
        path = Path(str(snap.get("model_path") or ""))
        return path.is_file() and path.stat().st_size / (1024 ** 3) > _LARGE_MODEL_GB
    except Exception:
        return False


def _too_soon_after_conversation() -> bool:
    """A glance that reloads a big model waits for a quiet spell, so it never lands just before the next message."""
    try:
        from eli.cognition.inference_broker import seconds_since_foreground
        import os
        idle = float(os.environ.get("ELI_AMBIENT_LARGE_MODEL_IDLE_S", _LARGE_MODEL_IDLE_S))
        return _swap_is_expensive() and seconds_since_foreground() < idle
    except Exception:
        return False


def _store_glance(text: str) -> None:
    if not text:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    payload = f"[Screen glance @ {stamp}] {text}"
    try:
        from eli.memory.memory import get_memory
        get_memory().add_memory(
            payload[:2000],
            tags=["screen_awareness", "ambient_vision", "eli_insight"],
        )
    except Exception as e:
        log.debug(f"[AMBIENT_VISION] store failed: {e}")


def _do_glance() -> None:
    """Capture the screen and describe it (best effort)."""
    try:
        from eli.perception import vision as _vision
        ok, reason = _vision.vision_available()
        _fok, _freason = _vision.fast_vision_available()
        if not (ok or _fok):
            _state["last_skip_reason"] = f"vision unavailable: {reason}"
            return
        # Capture the screen.
        try:
            from eli.perception.os_controller import take_screenshot
            ss = take_screenshot(region="full")
            path = ss.get("path") or ss.get("file") or ""
        except Exception as e:
            _state["last_skip_reason"] = f"screenshot failed: {e}"
            return
        if not path:
            _state["last_skip_reason"] = "no screenshot path"
            return
        res = _vision.describe_image(
            path,
            prompt=(
                "Briefly note what the user is doing on screen right now: the focused "
                "app and the task. One or two sentences. Only what you can actually see."
            ),
            prefer_fast=True,  # glances use the small fast model when available
        )
        _state["last_glance_ts"] = time.time()
        _state["last_glance_ok"] = bool(res.get("ok"))
        if res.get("ok"):
            text = str(res.get("text") or "").strip()
            _state["last_glance_text"] = text
            _state["glances"] += 1
            _store_glance(text)
            _state["last_skip_reason"] = ""
        else:
            _state["last_skip_reason"] = str(res.get("error") or "vision failed")
    except Exception as e:
        log.debug(f"[AMBIENT_VISION] glance failed: {e}")
        _state["last_skip_reason"] = f"glance error: {e}"


def _run() -> None:
    log.debug("[AMBIENT_VISION] loop started")
    _state["running"] = True
    # Start the clock now so the first glance waits a full interval. Otherwise (last_glance=0) it
    # fires on toggle-on and collides with startup or an on-demand "what's on my screen",
    # serialising two slow model swaps.
    last_glance = time.time()
    try:
        while not _stop_event.is_set():
            # Re-read the toggle every cycle so it can be flipped at runtime.
            if not _enabled():
                # Idle wait; cheap.
                _stop_event.wait(5)
                continue
            now = time.time()
            if now - last_glance >= _interval():
                if _llm_busy():
                    _state["last_skip_reason"] = "text model busy (conversation active)"
                elif _too_soon_after_conversation():
                    _state["last_skip_reason"] = "a glance would reload the large chat model; waiting for a quiet spell"
                else:
                    _do_glance()
                    last_glance = time.time()
            # Sleep in short steps so disable/interval/stop are responsive.
            _stop_event.wait(5)
    finally:
        _state["running"] = False
        log.debug("[AMBIENT_VISION] loop stopped")


def start_ambient_vision() -> None:
    """Start the guarded ambient-vision thread (idempotent)."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event.clear()
        _thread = threading.Thread(
            target=_run, daemon=True, name="eli-ambient-vision",
        )
        _thread.start()


def stop_ambient_vision() -> None:
    _stop_event.set()


def set_ambient_vision(enabled: bool) -> Dict[str, Any]:
    """Persist the toggle and ensure the loop is running (it self-gates on the flag)."""
    try:
        from eli.core import config
        config.set("ambient_vision_enabled", bool(enabled))
    except Exception as e:
        log.debug(f"[AMBIENT_VISION] could not persist toggle: {e}")
    if enabled:
        start_ambient_vision()
    return ambient_vision_status()


def ambient_vision_status() -> Dict[str, Any]:
    s = dict(_state)
    s["enabled"] = _enabled()
    s["interval"] = _interval()
    return s
