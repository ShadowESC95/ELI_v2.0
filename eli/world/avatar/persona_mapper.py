from __future__ import annotations
from typing import Dict
from eli.world.core.schemas import AwarenessState

class PersonaToAvatarMapper:
    def map_persona(self, awareness: AwarenessState, persona_text: str = "") -> Dict[str, object]:
        persona = persona_text.lower()
        tint = {
            "precision": 0.85,
            "dark_wit": 0.45 if ("sarcas" in persona or "dark wit" in persona) else 0.2,
            "directness": 0.85,
            "warmth": 0.35,
            "technicality": 0.9,
            "protective_boundary": 0.75,
        }
        expression = "neutral"
        posture = "idle"
        if awareness.repair_pressure > 0.65:
            expression, posture = "concerned", "diagnosing"
        elif awareness.evidence_confidence < 0.45 or awareness.uncertainty > 0.7:
            expression, posture = "cautious", "checking"
        elif awareness.reflection_depth > 0.55:
            expression, posture = "reflective", "thinking"
        elif awareness.tool_activity > 0.55:
            expression, posture = "focused", "working"
        elif awareness.curiosity > 0.75:
            expression, posture = "curious", "exploring"
        return {"expression": expression, "posture": posture, "persona_tint": tint}
