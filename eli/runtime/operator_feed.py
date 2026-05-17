from __future__ import annotations

from typing import Any, Dict, List

from eli.runtime.operator_state import safe_recent_proposals, safe_active_goals
from eli.execution.operator_policy import load_policy
from eli.planning.attention_queue import top_attention

def safe_operator_feed(limit: int = 25) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []

    policy = load_policy()
    events.append({
        "kind": "policy",
        "id": "runtime_policy",
        "title": f"mode={policy.get('mode', 'proposal_only')}",
        "state": policy.get("mode", "proposal_only"),
        "source": "operator_policy",
        "rank_score": 999.0,
    })

    att = top_attention(limit=limit)
    for rec in att.get("items", [])[:limit]:
        events.append({
            "kind": "attention",
            "id": rec.get("attention_id"),
            "title": rec.get("title") or "attention",
            "state": rec.get("state") or "pending",
            "source": rec.get("source") or "attention_queue",
            "rank_score": float(rec.get("rank_score") or 0.0),
        })

    p = safe_recent_proposals(limit=limit, include_archived=False)
    for rec in p.get("items", [])[:limit]:
        events.append({
            "kind": "proposal",
            "id": rec.get("proposal_id") or rec.get("id"),
            "title": rec.get("title") or rec.get("summary") or "proposal",
            "state": rec.get("approval_state") or "pending",
            "source": rec.get("source") or rec.get("kind") or "",
            "rank_score": 0.0,
        })

    g = safe_active_goals(limit=limit)
    for goal in g.get("items", [])[:limit]:
        events.append({
            "kind": "goal",
            "id": goal.get("goal_id"),
            "title": goal.get("title") or goal.get("objective") or "goal",
            "state": goal.get("status") or "active",
            "source": "goal_store",
            "rank_score": 0.0,
        })

    events = sorted(events, key=lambda e: float(e.get("rank_score") or 0.0), reverse=True)
    return {"ok": True, "count": len(events[:limit]), "items": events[:limit]}

