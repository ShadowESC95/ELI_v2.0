from __future__ import annotations
from pathlib import Path
from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.core.schemas import WorldEvent

COMMON_PERSONA_PATHS = [Path("eli/cognition/persona.auto.txt"), Path("eli/cognition/persona.txt")]

def load_persona_text() -> str:
    chunks = []
    for path in COMMON_PERSONA_PATHS:
        if path.exists():
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace")[:12000])
            except Exception:
                pass
    return "\n\n".join(chunks)

def send_reflection_to_world(summary: str, depth: float = 0.7, source: str = "reflection_bridge"):
    engine = EliWorldAutonomyEngine()
    event = WorldEvent(event_type="reflection", source=source, summary=summary, payload={"depth": depth})
    return engine.ingest_event(event, persona_text=load_persona_text())
