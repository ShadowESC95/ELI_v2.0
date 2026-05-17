from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_call(obj: Any, name: str, *args, **kwargs):
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return fn(*args, **kwargs)
        except TypeError:
            try:
                return fn(*args)
            except Exception:
                return None
        except Exception:
            return None
    return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _trim(value: Any, n: int = 280) -> str:
    s = " ".join(str(value or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _coerce_rows(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        for k in ("items", "rows", "results", "hits", "matches", "data"):
            v = value.get(k)
            if isinstance(v, list):
                return list(v)
        return [value]
    return [value]


def _extract_text(row: Any) -> str:
    keys = (
        "text", "content", "summary", "observation", "description", "error",
        "message", "memory", "value", "query", "assistant", "user"
    )
    for k in keys:
        v = _get(row, k)
        if v:
            t = _trim(v, 320)
            if t:
                return t
    return _trim(row, 320)


def _extract_row_id(row: Any) -> str:
    for k in ("id", "memory_id", "rowid", "uuid", "key"):
        v = _get(row, k)
        if v not in (None, ""):
            return str(v)
    return ""


def _coerce_score(row: Any, base: float) -> float:
    for k in ("score", "confidence", "similarity"):
        v = _get(row, k, None)
        try:
            f = float(v)
            if 0.0 <= f <= 1.0:
                return max(base, f)
        except Exception:
            pass
    return float(base)


def _memory_instance():
    try:
        from eli.memory import get_memory
        mem = get_memory()
        if mem is not None:
            return mem
    except Exception:
        pass
    return None


def infer_current_query(limit: int = 20) -> str:
    try:
        from eli.runtime.stage_packet_store import current_stage_packets
        packets = list(current_stage_packets() or [])
    except Exception:
        packets = []

    for pkt in reversed(packets[-limit:]):
        payload = _get(pkt, "payload", {}) or {}
        if isinstance(payload, dict):
            for k in ("query", "message", "user_input", "prompt", "objective", "request"):
                v = payload.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()[:500]
        summary = _get(pkt, "summary", "")
        if isinstance(summary, str) and summary.strip():
            s = summary.strip()
            if len(s) >= 16:
                return s[:500]
    return ""


def _normalize_rows(rows: List[Any], method: str, source_kind: str, base_score: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    for idx, row in enumerate(rows, start=1):
        text = _extract_text(row)
        if not text:
            continue
        fp = text.lower()
        if fp in seen:
            continue
        seen.add(fp)

        row_id = _extract_row_id(row) or f"{source_kind}_{idx}"
        score = _coerce_score(row, base_score)
        out.append({
            "kind": "memory_evidence",
            "source": f"memory:{source_kind}:{row_id}",
            "score": float(max(0.0, min(1.0, score))),
            "summary": text,
            "payload": {
                "method": method,
                "source_kind": source_kind,
                "row_id": row_id,
                "raw_score": _get(row, "score", _get(row, "confidence", _get(row, "similarity", None))),
                "row_type": type(row).__name__,
            },
            "created_at": _utc_now(),
        })
    return out


def collect_memory_evidence(query: str | None = None, limit: int = 12) -> Dict[str, Any]:
    mem = _memory_instance()
    q = (query or infer_current_query() or "").strip()

    if mem is None:
        return {
            "ok": True,
            "kind": "memory_evidence_bundle",
            "query": q,
            "count": 0,
            "items": [],
        }

    collected: List[Dict[str, Any]] = []

    if q:
        attempts = [
            ("search_memory", {"query": q, "limit": limit}, "search", 0.74),
            ("search_memory", {"text": q, "limit": limit}, "search", 0.74),
            ("search_memory", {"q": q, "limit": limit}, "search", 0.74),
            ("recall_memory", {"query": q, "limit": limit}, "recall", 0.72),
            ("recall_memory", {"text": q, "limit": limit}, "recall", 0.72),
        ]
        for name, kwargs, source_kind, base_score in attempts:
            raw = _safe_call(mem, name, **kwargs)
            rows = _coerce_rows(raw)
            if rows:
                collected.extend(_normalize_rows(rows, name, source_kind, base_score))
                break

    recent_specs = [
        ("get_recent_processed_memories", {"limit": max(4, min(limit, 8))}, "processed", 0.62),
        ("get_recent_observations", {"limit": max(4, min(limit, 8))}, "observations", 0.58),
        ("get_recent_conversation", {"limit": max(4, min(limit, 8))}, "conversation", 0.48),
    ]
    for name, kwargs, source_kind, base_score in recent_specs:
        raw = _safe_call(mem, name, **kwargs)
        rows = _coerce_rows(raw)
        if rows:
            collected.extend(_normalize_rows(rows, name, source_kind, base_score))

    dedup: Dict[tuple, Dict[str, Any]] = {}
    for item in collected:
        fp = (item.get("kind"), item.get("source"), item.get("summary"))
        cur = dedup.get(fp)
        if cur is None or float(item.get("score", 0.0)) > float(cur.get("score", 0.0)):
            dedup[fp] = item

    ranked = sorted(
        dedup.values(),
        key=lambda x: (float(x.get("score", 0.0)), str(x.get("created_at", "")), str(x.get("source", ""))),
        reverse=True,
    )[:limit]

    return {
        "ok": True,
        "kind": "memory_evidence_bundle",
        "query": q,
        "count": len(ranked),
        "items": ranked,
    }


def build_memory_evidence_text(limit: int = 8, query: str | None = None) -> str:
    bundle = collect_memory_evidence(query=query, limit=limit)
    lines = ["Memory evidence:"]
    for i, item in enumerate(bundle.get("items", [])[:limit], start=1):
        lines.append(
            f"{i}. [memory_evidence] score={float(item.get('score', 0.0)):.2f} "
            f"{item.get('source')}: {item.get('summary')}"
        )
    return "\n".join(lines)
