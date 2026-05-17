from __future__ import annotations

from typing import Any, Dict, List

from eli.planning.goal_store import load_goals, save_goals, upsert_goal
from eli.planning.goal_models import GoalSpec

VALID_AUTONOMY_MODES = {
    "proposal_only",
    "operator_supervised",
    "goal_driven",
}

_PRIORITY_MAP = {
    "lowest": 0.10,
    "low": 0.25,
    "normal": 0.50,
    "medium": 0.50,
    "default": 0.50,
    "high": 0.75,
    "urgent": 0.90,
    "critical": 1.00,
}


def _coerce_priority(value: Any) -> float:
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        raw = str(value or "").strip().lower()
        if raw in _PRIORITY_MAP:
            out = _PRIORITY_MAP[raw]
        else:
            try:
                out = float(raw)
            except Exception:
                out = _PRIORITY_MAP["normal"]
    if out < 0.0:
        out = 0.0
    if out > 1.0:
        out = 1.0
    return out


def _coerce_cadence(value: Any) -> int:
    try:
        out = int(value)
    except Exception:
        out = 3600
    return max(1, out)


def _coerce_autonomy_mode(value: Any) -> str:
    mode = str(value or "proposal_only").strip()
    if mode not in VALID_AUTONOMY_MODES:
        return "proposal_only"
    return mode


def create_goal(
    title: str,
    objective: str = "",
    priority: Any = "normal",
    cadence_sec: Any = 3600,
    autonomy_mode: str = "proposal_only",
    constraints: List[str] | None = None,
    success_criteria: List[str] | None = None,
    tags: List[str] | None = None,
) -> Dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}

    spec = GoalSpec.from_any({
        "title": title,
        "objective": str(objective or title).strip(),
        "priority": _coerce_priority(priority),
        "cadence_sec": _coerce_cadence(cadence_sec),
        "autonomy_mode": _coerce_autonomy_mode(autonomy_mode),
        "constraints": list(constraints or []),
        "success_criteria": list(success_criteria or []),
        "tags": list(tags or []),
        "enabled": True,
        "status": "active",
    })
    out = upsert_goal(spec)
    return {"ok": True, "goal": out.to_dict() if hasattr(out, "to_dict") else dict(out.__dict__)}


def set_goal_enabled(goal_id: str, enabled: bool) -> Dict[str, Any]:
    goals = load_goals()
    changed = False
    out = None
    for g in goals:
        if g.goal_id == goal_id:
            g.enabled = bool(enabled)
            if not g.enabled and g.status == "active":
                g.status = "paused"
            elif g.enabled and g.status in {"paused", "inactive"}:
                g.status = "active"
            changed = True
            out = g
            break
    if not changed:
        return {"ok": False, "error": "goal not found", "goal_id": goal_id}
    save_goals(goals)
    return {"ok": True, "goal": out.to_dict() if hasattr(out, "to_dict") else dict(out.__dict__)}


def update_goal_fields(goal_id: str, **fields: Any) -> Dict[str, Any]:
    goals = load_goals()
    out = None
    changed = False

    for g in goals:
        if g.goal_id != goal_id:
            continue

        normalized = dict(fields)
        if "priority" in normalized and normalized["priority"] is not None:
            normalized["priority"] = _coerce_priority(normalized["priority"])
        if "cadence_sec" in normalized and normalized["cadence_sec"] is not None:
            normalized["cadence_sec"] = _coerce_cadence(normalized["cadence_sec"])
        if "autonomy_mode" in normalized and normalized["autonomy_mode"] is not None:
            normalized["autonomy_mode"] = _coerce_autonomy_mode(normalized["autonomy_mode"])

        for key, val in normalized.items():
            if val is None or not hasattr(g, key):
                continue
            setattr(g, key, val)
            changed = True

        out = g
        break

    if out is None:
        return {"ok": False, "error": "goal not found", "goal_id": goal_id}

    if changed:
        save_goals(goals)

    return {
        "ok": True,
        "changed": changed,
        "goal": out.to_dict() if hasattr(out, "to_dict") else dict(out.__dict__),
    }
