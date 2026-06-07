"""State providers — the hook that lets components expose save/restore state to a
project's "Save State" / "Resume" (Phase 4, the previously-undone 20%).

A component (e.g. the Labs Sim-IDE) registers a name + a capture callable and a
restore callable. On Save State the Projects tab calls `capture_all()` and stores
the dict in the project's `last_state["providers"]`; on Resume it calls
`restore_all(data)`. Everything is best-effort and exception-isolated, so a
misbehaving provider can never break save/resume.

This is the honest, extensible form of "simulation/internal-state resume": any
component that can serialise its state participates; those that can't, don't.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

_LOCK = threading.RLock()
# name -> (capture() -> Any, restore(Any) -> None)
_PROVIDERS: Dict[str, Tuple[Callable[[], Any], Callable[[Any], None]]] = {}


def register(name: str, capture: Callable[[], Any], restore: Callable[[Any], None]) -> None:
    """Register a state provider. Last registration for a name wins (handles a
    component being rebuilt). Pass capture/restore as bound methods."""
    if not name or not callable(capture) or not callable(restore):
        return
    with _LOCK:
        _PROVIDERS[name] = (capture, restore)


def unregister(name: str) -> None:
    with _LOCK:
        _PROVIDERS.pop(name, None)


def capture_all() -> Dict[str, Any]:
    """Snapshot every provider's current state. Best-effort."""
    out: Dict[str, Any] = {}
    with _LOCK:
        items = list(_PROVIDERS.items())
    for name, (cap, _restore) in items:
        try:
            val = cap()
            if val is not None:
                out[name] = val
        except Exception as e:
            log.debug(f"[STATE] capture '{name}' failed: {e}")
    return out


def restore_all(data: Dict[str, Any]) -> int:
    """Restore providers from a captured dict. Returns how many were restored."""
    if not isinstance(data, dict):
        return 0
    n = 0
    with _LOCK:
        providers = dict(_PROVIDERS)
    for name, val in data.items():
        pair = providers.get(name)
        if not pair:
            continue
        try:
            pair[1](val)
            n += 1
        except Exception as e:
            log.debug(f"[STATE] restore '{name}' failed: {e}")
    return n


def provider_names() -> list:
    with _LOCK:
        return sorted(_PROVIDERS)


__all__ = ["register", "unregister", "capture_all", "restore_all", "provider_names"]
