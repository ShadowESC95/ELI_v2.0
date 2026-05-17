from __future__ import annotations
from time import time
from typing import Any, Dict, List

def decay_goals(goals: List[Dict[str, Any]], decay: float = 0.02) -> List[Dict[str, Any]]:
    now = time()
    out = []
    for goal in goals:
        g = dict(goal)
        g["urgency"] = max(0.0, float(g.get("urgency", 0.5)) - decay)
        g["last_ecology_update"] = now
        if not g.get("abandoned", False):
            out.append(g)
    return out

def add_goal(goals: List[Dict[str, Any]], title: str, source: str, urgency: float = 0.5) -> List[Dict[str, Any]]:
    goals.append({"title": title, "source": source, "urgency": urgency, "created": time(), "status": "active"})
    return goals
