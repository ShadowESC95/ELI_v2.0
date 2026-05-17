from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
import time
import uuid


def _now() -> float:
    return time.time()


@dataclass
class GoalSpec:
    title: str
    objective: str = ""
    priority: float = 0.5
    cadence_sec: int = 900
    enabled: bool = True
    autonomy_mode: str = "proposal_only"
    risk: str = "medium"
    success_criteria: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    goal_id: str = field(default_factory=lambda: f"goal_{uuid.uuid4().hex[:12]}")
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    last_tick_at: float = 0.0
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "title": self.title,
            "objective": self.objective,
            "priority": float(self.priority),
            "cadence_sec": int(self.cadence_sec),
            "enabled": bool(self.enabled),
            "autonomy_mode": self.autonomy_mode,
            "risk": self.risk,
            "success_criteria": list(self.success_criteria),
            "tags": list(self.tags),
            "constraints": list(self.constraints),
            "metadata": dict(self.metadata),
            "created_at": float(self.created_at),
            "updated_at": float(self.updated_at),
            "last_tick_at": float(self.last_tick_at),
            "status": self.status,
        }

    @classmethod
    def from_any(cls, obj: Dict[str, Any] | "GoalSpec") -> "GoalSpec":
        if isinstance(obj, GoalSpec):
            return obj
        data = dict(obj or {})
        return cls(
            title=str(data.get("title") or "").strip(),
            objective=str(data.get("objective") or "").strip(),
            priority=float(data.get("priority", 0.5)),
            cadence_sec=int(data.get("cadence_sec", 900)),
            enabled=bool(data.get("enabled", True)),
            autonomy_mode=str(data.get("autonomy_mode", "proposal_only")),
            risk=str(data.get("risk", "medium")),
            success_criteria=list(data.get("success_criteria") or []),
            tags=list(data.get("tags") or []),
            constraints=list(data.get("constraints") or []),
            metadata=dict(data.get("metadata") or {}),
            goal_id=str(data.get("goal_id") or f"goal_{uuid.uuid4().hex[:12]}"),
            created_at=float(data.get("created_at", _now())),
            updated_at=float(data.get("updated_at", _now())),
            last_tick_at=float(data.get("last_tick_at", 0.0)),
            status=str(data.get("status", "active")),
        )
