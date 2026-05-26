from __future__ import annotations
import threading
import time
from typing import Any, Dict, List, Optional

# Cooldown: autonomy_pressure SELF_IMPROVE suggestion fires at most once per hour
_SELF_IMPROVE_SUGGEST_COOLDOWN = 3600.0
_last_self_improve_suggest: float = 0.0
from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.agency.reflection_bridge import load_persona_text
from eli.world.core.schemas import AwarenessState, EliWorldState, WorldEvent

# Singleton — EliWorldAutonomyEngine is stateful; creating a new instance on
# every call discards in-memory caches and re-parses JSON on every event.
_engine_instance: Optional[EliWorldAutonomyEngine] = None
_engine_lock = threading.Lock()


def _get_engine() -> EliWorldAutonomyEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = EliWorldAutonomyEngine()
    return _engine_instance


def get_world_state() -> Dict[str, Any]:
    return _get_engine().load().to_dict()


def append_event(event_type: str, source: str, summary: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    engine = _get_engine()
    event = WorldEvent(event_type=event_type, source=source, summary=summary, payload=payload or {})
    state = engine.ingest_event(event, persona_text=load_persona_text())
    return state.to_dict()


def get_awareness_driven_suggestions() -> List[Dict[str, Any]]:
    """Read the current AwarenessState and return runtime suggestions for the
    proactive daemon.

    This closes the world→runtime feedback loop: the autonomy engine updates
    AwarenessState based on events; this function converts those awareness
    values into concrete runtime actions the daemon should consider executing.

    Each suggestion is a dict:
        {"action": str, "reason": str, "priority": float}

    Priority 1.0 = urgent, 0.0 = informational.
    The daemon decides whether and when to act; this is advisory only.
    """
    try:
        state: EliWorldState = _get_engine().load()
        a: AwarenessState = state.awareness
    except Exception:
        return []

    suggestions: List[Dict[str, Any]] = []

    # High repair pressure → run self-analysis to surface unresolved faults
    if a.repair_pressure > 0.65:
        suggestions.append({
            "action": "SELF_ANALYZE",
            "reason": f"repair_pressure={a.repair_pressure:.2f} — unresolved faults likely",
            "priority": min(1.0, a.repair_pressure),
        })

    # Low memory confidence → run a memory health check
    if a.memory_confidence < 0.40:
        suggestions.append({
            "action": "MEMORY_STATUS",
            "reason": f"memory_confidence={a.memory_confidence:.2f} — memory layer may be degraded",
            "priority": round(1.0 - a.memory_confidence, 2),
        })

    # High autonomy pressure + sufficient reflection depth → trigger self-improvement
    # Throttled: at most once per hour to prevent auto-trigger loops
    global _last_self_improve_suggest
    if a.autonomy_pressure > 0.65 and a.reflection_depth > 0.40:
        _now = time.monotonic()
        if _now - _last_self_improve_suggest >= _SELF_IMPROVE_SUGGEST_COOLDOWN:
            _last_self_improve_suggest = _now
            suggestions.append({
                "action": "SELF_IMPROVE",
                "reason": (
                    f"autonomy_pressure={a.autonomy_pressure:.2f} "
                    f"reflection_depth={a.reflection_depth:.2f} — "
                    "self-improvement cycle warranted"
                ),
                "priority": round((a.autonomy_pressure + a.reflection_depth) / 2, 2),
            })

    # High uncertainty + weak evidence → log the state for review (no aggressive action)
    if a.uncertainty > 0.75 and a.evidence_confidence < 0.45:
        suggestions.append({
            "action": "SELF_ANALYZE",
            "reason": (
                f"uncertainty={a.uncertainty:.2f} "
                f"evidence_confidence={a.evidence_confidence:.2f} — "
                "evidence quality needs review"
            ),
            "priority": round((a.uncertainty - a.evidence_confidence) / 2, 2),
        })

    return suggestions


if __name__ == "__main__":
    state = append_event("reflection", "manual_test", "Eli's World frontier local autonomy engine initialized.", {"depth": 0.75, "offline": True})
    print(state["avatar"])
