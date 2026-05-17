from __future__ import annotations
from typing import Dict, Tuple

ROOM_COORDS: Dict[str, Tuple[float, float]] = {
    "core_room": (0.0, 0.0),
    "memory_archive": (-220.0, 0.0),
    "workshop": (220.0, 0.0),
    "reflection_chamber": (0.0, -180.0),
    "debug_basement": (0.0, 180.0),
    "upgrade_bay": (220.0, -180.0),
    "simulation_lab": (-220.0, -180.0),
    "anomaly_room": (-220.0, 180.0),
    "evidence_wall": (220.0, 180.0),
}

def target_for_room(room: str) -> Tuple[float, float]:
    return ROOM_COORDS.get(room, (0.0, 0.0))
