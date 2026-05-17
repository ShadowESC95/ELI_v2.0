from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any

from eli.planning.goal_models import GoalSpec


def _default_goal_store() -> Path:
    env = os.environ.get("ELI_GOAL_STORE", "").strip()
    if env:
        return Path(env).expanduser()
    return Path("artifacts/runtime/goals.json")


def goal_store_path() -> Path:
    path = _default_goal_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_goals() -> List[GoalSpec]:
    path = goal_store_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw if isinstance(raw, list) else raw.get("goals", [])
    return [GoalSpec.from_any(x) for x in items if isinstance(x, dict)]


def save_goals(goals: List[GoalSpec]) -> Path:
    path = goal_store_path()
    payload = [g.to_dict() for g in goals]
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def upsert_goal(goal: Dict[str, Any] | GoalSpec) -> GoalSpec:
    goals = load_goals()
    spec = GoalSpec.from_any(goal)
    now = time.time()
    spec.updated_at = now
    replaced = False
    for i, cur in enumerate(goals):
        if cur.goal_id == spec.goal_id:
            spec.created_at = cur.created_at
            goals[i] = spec
            replaced = True
            break
    if not replaced:
        if not spec.created_at:
            spec.created_at = now
        goals.append(spec)
    save_goals(goals)
    return spec


def list_active_goals() -> List[GoalSpec]:
    return [
        g for g in load_goals()
        if g.enabled and g.status.lower() in {"active", "queued", "running"}
    ]


def due_goals(now: float | None = None, limit: int = 5) -> List[GoalSpec]:
    now = time.time() if now is None else float(now)
    goals = list_active_goals()
    scored = []
    for g in goals:
        due = (g.last_tick_at + max(1, int(g.cadence_sec))) <= now
        if due:
            age = max(0.0, now - float(g.last_tick_at or 0.0))
            score = (float(g.priority) * 1000.0) + min(age, 86400.0)
            scored.append((score, g))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [g for _, g in scored[:max(1, int(limit))]]


def mark_goal_tick(goal_id: str, when: float | None = None) -> bool:
    when = time.time() if when is None else float(when)
    goals = load_goals()
    changed = False
    for g in goals:
        if g.goal_id == goal_id:
            g.last_tick_at = when
            g.updated_at = when
            changed = True
            break
    if changed:
        save_goals(goals)
    return changed


def summarize_goals() -> Dict[str, Any]:
    goals = load_goals()
    active = [g for g in goals if g.enabled and g.status == "active"]
    return {
        "ok": True,
        "path": str(goal_store_path()),
        "total": len(goals),
        "active": len(active),
        "titles": [g.title for g in active[:10]],
    }
