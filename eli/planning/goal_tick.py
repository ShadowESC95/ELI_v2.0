from __future__ import annotations

import inspect
import time
from typing import Any, Dict, List

from eli.planning.goal_store import due_goals, mark_goal_tick


def _goal_to_proposal(goal) -> Dict[str, Any]:
    return {
        "title": f"Goal tick: {goal.title}",
        "summary": goal.objective or goal.title,
        "rationale": (
            "Autonomy mission-layer due tick. "
            f"goal_id={goal.goal_id} priority={goal.priority} cadence_sec={goal.cadence_sec}"
        ),
        "risk": goal.risk,
        "source": "goal_mission_layer",
        "status": "pending_approval",
        "kind": "mission_goal",
        "metadata": {
            "goal_id": goal.goal_id,
            "goal_title": goal.title,
            "goal_tags": list(goal.tags),
            "constraints": list(goal.constraints),
            "success_criteria": list(goal.success_criteria),
            "autonomy_mode": goal.autonomy_mode,
        },
        "requested_action": {
            "type": "goal_tick",
            "goal_id": goal.goal_id,
            "title": goal.title,
            "objective": goal.objective,
        },
    }


def _emit_governed_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from eli.runtime import proposal_queue as pq
    except Exception as exc:
        return {"ok": False, "error": f"proposal_queue import failed: {exc}", "proposal": proposal}

    fn = getattr(pq, "append_governed_proposal", None)
    if fn is None:
        return {"ok": False, "error": "append_governed_proposal missing", "proposal": proposal}

    try:
        sig = inspect.signature(fn)
        kwargs = {k: v for k, v in proposal.items() if k in sig.parameters}
        if kwargs:
            rec = fn(**kwargs)
        else:
            try:
                rec = fn(proposal)
            except TypeError:
                rec = fn()
        return {"ok": True, "record": rec, "proposal": proposal}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "proposal": proposal}


def governed_goal_tick(limit: int = 3, now: float | None = None) -> Dict[str, Any]:
    now = time.time() if now is None else float(now)
    goals = due_goals(now=now, limit=limit)
    emitted: List[Dict[str, Any]] = []
    for goal in goals:
        proposal = _goal_to_proposal(goal)
        res = _emit_governed_proposal(proposal)
        emitted.append({"goal_id": goal.goal_id, "title": goal.title, "emit": res})
        mark_goal_tick(goal.goal_id, when=now)
    return {
        "ok": True,
        "kind": "governed_goal_tick",
        "count": len(emitted),
        "items": emitted,
    }
