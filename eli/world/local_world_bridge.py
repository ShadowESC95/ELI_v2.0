from __future__ import annotations
from typing import Any, Dict, Optional
from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.agency.reflection_bridge import load_persona_text
from eli.world.core.schemas import WorldEvent

def get_world_state() -> Dict[str, Any]:
    return EliWorldAutonomyEngine().load().to_dict()

def append_event(event_type: str, source: str, summary: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    engine = EliWorldAutonomyEngine()
    event = WorldEvent(event_type=event_type, source=source, summary=summary, payload=payload or {})
    state = engine.ingest_event(event, persona_text=load_persona_text())
    return state.to_dict()

if __name__ == "__main__":
    state = append_event("reflection", "manual_test", "Eli's World frontier local autonomy engine initialized.", {"depth": 0.75, "offline": True})
    print(state["avatar"])
