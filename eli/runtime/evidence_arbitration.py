from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


@dataclass
class EvidenceItem:
    kind: str
    source: str
    score: float
    summary: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "score": float(self.score),
            "summary": self.summary,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at,
        }


def _trim(text: Any, n: int = 280) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _fingerprint(item: EvidenceItem) -> str:
    return "|".join([
        item.kind,
        item.source,
        _trim(item.summary, 160),
    ])


def _score_stage_packet(pkt: Any) -> EvidenceItem:
    kind = str(_get(pkt, "kind", "") or "")
    stage = str(_get(pkt, "stage", "") or "")
    summary = _trim(_get(pkt, "summary", "") or f"{stage}:{kind}")
    payload = _get(pkt, "payload", {}) or {}
    created_at = str(_get(pkt, "created_at", "") or _utc_now())

    score = 0.35
    if "retrieval" in kind or stage in {"hyde", "retrieval", "hybrid_merge", "rerank"}:
        score = 0.90
    elif "tool_result" in kind or stage == "tool_result":
        score = 0.84
    elif "execution" in kind or stage.startswith("execution"):
        score = 0.80
    elif "response" in kind or stage in {"final_response", "assembly"}:
        score = 0.70
    elif "stage_packet" in kind:
        score = 0.40

    return EvidenceItem(
        kind=kind or "stage_packet",
        source=f"stage:{stage or 'unknown'}",
        score=score,
        summary=summary,
        payload=dict(payload if isinstance(payload, dict) else {"repr": repr(payload)[:400]}),
        created_at=created_at,
    )


def _score_tool_result(rec: Any) -> EvidenceItem:
    ok = bool(_get(rec, "ok", True))
    status = str(_get(rec, "status", "ok") or "ok")
    action = str(_get(rec, "action", "") or "")
    summary = _trim(_get(rec, "summary", "") or action or status)
    payload = _get(rec, "payload", {}) or {}
    created_at = str(_get(rec, "created_at", "") or _utc_now())

    score = 0.86 if ok else 0.30
    if status in {"approved", "applied", "executed"}:
        score += 0.05
    if status in {"error", "blocked"}:
        score -= 0.08

    return EvidenceItem(
        kind="tool_result",
        source=f"tool:{action or 'unknown'}",
        score=max(0.0, min(1.0, score)),
        summary=summary,
        payload=dict(payload if isinstance(payload, dict) else {"repr": repr(payload)[:400]}),
        created_at=created_at,
    )


def _score_goal(goal: Any) -> EvidenceItem:
    goal_id = str(_get(goal, "goal_id", "") or "")
    title = str(_get(goal, "title", "") or goal_id or "goal")
    objective = str(_get(goal, "objective", "") or "")
    priority = _coerce_float(_get(goal, "priority", 0.5), 0.5)
    status = str(_get(goal, "status", "active") or "active")
    enabled = bool(_get(goal, "enabled", True))
    created_at = str(_get(goal, "created_at", "") or _utc_now())

    score = 0.42 + max(0.0, min(1.0, priority)) * 0.28
    if enabled and status == "active":
        score += 0.08

    return EvidenceItem(
        kind="goal_evidence",
        source=f"goal:{goal_id or title}",
        score=max(0.0, min(1.0, score)),
        summary=_trim(f"{title}: {objective}" if objective else title),
        payload={
            "goal_id": goal_id,
            "title": title,
            "objective": objective,
            "priority": priority,
            "status": status,
            "enabled": enabled,
        },
        created_at=created_at,
    )


def arbitrate_evidence(limit: int = 40) -> Dict[str, Any]:
    items: List[EvidenceItem] = []

    try:
        from eli.runtime.stage_packet_store import current_stage_packets
        for pkt in list(current_stage_packets() or [])[-limit:]:
            items.append(_score_stage_packet(pkt))
    except Exception:
        pass

    try:
        from eli.runtime.tool_result_store import load_recent_tool_results
        for rec in load_recent_tool_results(limit=limit):
            items.append(_score_tool_result(rec))
    except Exception:
        pass

    try:
        from eli.planning.goal_store import list_active_goals
        for goal in list(list_active_goals() or [])[: max(1, min(10, limit // 4))]:
            items.append(_score_goal(goal))
    except Exception:
        pass

    dedup: Dict[str, EvidenceItem] = {}
    for item in items:
        fp = _fingerprint(item)
        cur = dedup.get(fp)
        if cur is None or item.score > cur.score:
            dedup[fp] = item

    ranked = sorted(
        dedup.values(),
        key=lambda x: (round(float(x.score), 6), x.created_at, x.kind),
        reverse=True,
    )[:limit]

    return {
        "ok": True,
        "kind": "evidence_arbitration_bundle",
        "count": len(ranked),
        "items": [x.to_dict() for x in ranked],
        "top_summary": [x.summary for x in ranked[:8]],
    }


def build_evidence_context_text(limit: int = 12) -> str:
    bundle = arbitrate_evidence(limit=limit)
    lines = ["Evidence bundle:"]
    for i, item in enumerate(bundle.get("items", [])[:limit], start=1):
        lines.append(
            f"{i}. [{item.get('kind')}] score={item.get('score'):.2f} "
            f"{item.get('source')}: {item.get('summary')}"
        )
    return "\n".join(lines)
