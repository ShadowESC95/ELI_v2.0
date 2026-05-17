from __future__ import annotations

import json
from typing import Any, Dict, List

from eli.planning.proposal_queue import drain_records


def _safe_call(obj: Any, name: str, *args, **kwargs):
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None
    return None


def drain_proposals_to_agent_memory(memory: Any = None, max_items: int = 50, archive: bool = True) -> Dict[str, Any]:
    drained = drain_records(limit=max_items, archive=archive)
    kinds: List[str] = []

    if memory is None:
        try:
            from eli.memory import get_agent_memory
            memory = get_agent_memory()
        except Exception:
            memory = None

    for rec in drained:
        kinds.append(rec.kind)
        payload = {
            "proposal_id": rec.proposal_id,
            "kind": rec.kind,
            "source": rec.source,
            "priority": rec.priority,
            "cwd": rec.cwd,
            "action_class": rec.action_class,
            "emitter": rec.emitter,
            "requested_by": rec.requested_by,
            "approval_state": rec.approval_state,
            "requires_confirmation": rec.requires_confirmation,
            "approved_by": rec.approved_by,
            "policy_reason": rec.policy_reason,
            "payload": rec.payload,
        }
        text = json.dumps(payload, ensure_ascii=False)[:6000]

        if memory is not None:
            ok = _safe_call(
                memory,
                "add_observation",
                category="proposal_queue",
                observation=rec.kind,
                content=text,
            )
            if ok is None:
                _safe_call(memory, "log_improvement", "proposal_queue", text[:4000])

    return {
        "ok": True,
        "count": len(drained),
        "kinds": kinds,
    }
