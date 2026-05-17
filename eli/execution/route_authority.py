from __future__ import annotations

import threading
from typing import Optional

from eli.runtime.pipeline_models import RouteDecision

_tls = threading.local()

_INTERNAL_PREFIXES = (
    "grounded reply required",
    "critical:",
    "final_response_provider_contract",
    "assembled_response_context",
    "user query:",
)

def begin_route_cycle() -> None:
    _tls.route_cycle_active = True

def end_route_cycle() -> None:
    for k in ("route_cycle_active", "locked_route"):
        try:
            delattr(_tls, k)
        except Exception:
            pass

def is_route_cycle_active() -> bool:
    return bool(getattr(_tls, "route_cycle_active", False))

def lock_route_decision(rd: RouteDecision) -> RouteDecision:
    _tls.locked_route = rd
    return rd

def get_locked_route_decision() -> Optional[RouteDecision]:
    return getattr(_tls, "locked_route", None)

def should_reuse_locked_route(text: str | None) -> bool:
    if not is_route_cycle_active():
        return False
    if get_locked_route_decision() is None:
        return False
    s = str(text or "").strip().lower()
    if not s:
        return False
    return any(s.startswith(p) for p in _INTERNAL_PREFIXES)
