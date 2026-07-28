from __future__ import annotations
import logging
from typing import Dict
from eli.world.core.schemas import AwarenessState

log = logging.getLogger(__name__)

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
        # Expressed emotion (tone_adaptor) takes the face when it's non-neutral, so the
        # avatar shows the same feeling ELI is speaking in — the third output channel.
        try:
            from eli.cognition import tone_adaptor
            _cur = tone_adaptor.current_tone()
            if _cur.get("tone") not in (None, "neutral"):
                expression = tone_adaptor.expression()
        except Exception:
            log.debug("tone_adaptor expression skipped", exc_info=True)
        return {"expression": expression, "posture": posture, "persona_tint": tint}
