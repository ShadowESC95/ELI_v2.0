from __future__ import annotations
from time import time
from typing import Any, Dict, List

DEFAULT_HABITS = [
    {"name": "memory_continuity_check", "description": "Periodically inspect memory confidence and create repair objects if needed.", "enabled": True, "interval_hint": "session"},
    {"name": "evidence_wall_check", "description": "Move uncertain claims to the evidence wall or anomaly room.", "enabled": True, "interval_hint": "session"},
    {"name": "world_journal_update", "description": "Record significant autonomous world changes.", "enabled": True, "interval_hint": "major_action"},
]

def ensure_default_habits(habits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing = {h.get("name") for h in habits}
    for habit in DEFAULT_HABITS:
        if habit["name"] not in existing:
            row = dict(habit)
            row["created"] = time()
            habits.append(row)
    return habits
