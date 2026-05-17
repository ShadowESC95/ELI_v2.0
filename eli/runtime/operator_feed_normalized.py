from __future__ import annotations

from typing import Any, Dict, List

from eli.runtime.tool_result_store import load_recent_tool_results


def build_normalized_operator_feed(limit: int = 20) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    for rec in reversed(load_recent_tool_results(limit=limit)):
        items.append({
            "kind": "tool_result",
            "action": rec.action,
            "state": rec.status,
            "ok": rec.ok,
            "summary": rec.summary,
            "source": rec.source,
            "created_at": rec.created_at,
            "payload": dict(rec.payload or {}),
        })

    return {
        "ok": True,
        "kind": "normalized_operator_feed",
        "count": len(items),
        "items": items[:limit],
    }
