"""ELI home intelligence — weave the LLM into the home/device system.

Turns raw device usage into things ELI can actually use:
  • note_usage()    — record a *preference* signal into ELI's memory (throttled) so
                      "what do you know about me" reflects how you use your home.
  • home_context()  — a short snapshot (connection, what's on, your usual habits) that
                      ELI's awareness can inject so it *knows* the state of your home.
  • suggestions()   — proactive automation ideas derived from usage ("you usually turn
                      the desk lamp on around 20:00 — automate it?").

All best-effort: never raises into callers, degrades cleanly with no devices.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Throttle memory writes: at most one note per (device, command) per this many seconds.
_NOTE_THROTTLE = 12 * 3600.0
_last_note: Dict[str, float] = {}


def _server():
    try:
        from eli.runtime.device_server import get_server
        return get_server()
    except Exception:
        return None


def note_usage(row: Dict[str, Any]) -> None:
    """Record a home-use preference into ELI's memory — throttled so toggling a light
    repeatedly doesn't spam memory. Best-effort."""
    try:
        key = f"{row.get('id')}:{row.get('command')}"
        now = time.time()
        if now - _last_note.get(key, 0) < _NOTE_THROTTLE:
            return
        _last_note[key] = now
        name = row.get("name") or row.get("id")
        room = (row.get("room") or "").strip()
        hour = row.get("hour")
        where = f" in the {room}" if room else ""
        when = f" around {int(hour):02d}:00" if isinstance(hour, (int, float)) else ""
        text = f"Home preference: turns the {name}{where} {row.get('command')}{when}."
        from eli.memory.memory import get_memory
        mem = get_memory()
        if hasattr(mem, "add_memory"):
            mem.add_memory(text, tags=["home", "preference"])
    except Exception:
        log.debug("home_intel: note_usage failed", exc_info=True)


def home_context(max_chars: int = 420) -> str:
    """One-paragraph home snapshot for ELI's awareness/context. Empty string if there's
    nothing meaningful (no broker / no devices) so it never pollutes the prompt."""
    srv = _server()
    if srv is None:
        return ""
    try:
        state = srv.home_state()
    except Exception:
        return ""
    if not state.get("device_count"):
        return ""
    parts = []
    if state.get("connected"):
        parts.append(f"Home: {state.get('device_count')} device(s) connected.")
    else:
        parts.append("Home: device server configured (broker offline).")
    on = state.get("on") or []
    if on:
        parts.append("On now: " + ", ".join(on[:8]) + ".")
    try:
        usage = srv.usage_summary().get("devices", [])
        habits = [f"{d['name']}" + (f" (~{int(d['favourite_hour']):02d}:00)" if d.get("favourite_hour") is not None else "")
                  for d in usage[:3] if d.get("uses", 0) >= 3]
        if habits:
            parts.append("You most use: " + ", ".join(habits) + ".")
    except Exception:
        pass
    return " ".join(parts)[:max_chars]


def suggestions(min_uses: int = 4) -> List[Dict[str, Any]]:
    """Proactive automation ideas from usage patterns. Each: {device, room, hour, text}."""
    srv = _server()
    if srv is None:
        return []
    out: List[Dict[str, Any]] = []
    try:
        for d in srv.usage_summary().get("devices", []):
            h = d.get("favourite_hour")
            if d.get("uses", 0) >= min_uses and h is not None:
                where = f" in the {d['room']}" if d.get("room") else ""
                out.append({
                    "device": d["id"], "name": d["name"], "room": d.get("room", ""),
                    "hour": int(h),
                    "text": f"You usually use the {d['name']}{where} around {int(h):02d}:00 "
                            f"({d['uses']} times lately). Want ELI to automate it?",
                })
    except Exception:
        log.debug("home_intel: suggestions failed", exc_info=True)
    return out[:6]
