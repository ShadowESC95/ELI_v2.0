"""Unified memory retrieval for orchestrator and agent bus.

Single authority: ``retrieve_for_turn`` owns semantic + conversation recall.
Orchestrator keyword/semantic stages consume this module instead of parallel
``recall_memory_query`` / FAISS paths that diverged in budget and verification.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from eli.memory.retrieval import TurnRetrievalResult, retrieve_for_turn
from eli.runtime.memory_provenance import is_explicit_memory_audit_query

_VERIFIED_MARKER = "Verified stored memories"


def split_verified_evidence_packet(text: str) -> Tuple[str, str]:
    """Split the verified-memory block from the rest of agent/bus context."""
    ctx = str(text or "").strip()
    if not ctx or _VERIFIED_MARKER not in ctx:
        return "", ctx
    start = ctx.find(_VERIFIED_MARKER)
    if start < 0:
        return "", ctx
    # Block runs until the next blank-line section header or end.
    rest = ctx[start:]
    end = rest.find("\n\n[")
    if end > 0:
        verified = rest[:end].strip()
        remainder = (ctx[:start] + rest[end:]).strip()
    else:
        verified = rest.strip()
        remainder = ctx[:start].strip()
    return verified, remainder


def _normalize_hit(hit: Dict[str, Any], *, default_source: str) -> Dict[str, Any]:
    text = (hit.get("text") or hit.get("content") or "").strip()
    src = str(hit.get("_source") or default_source or "fts").lower()
    score = float(hit.get("weight") or hit.get("importance") or hit.get("score") or 0.5)
    return {
        "source": "fts5" if src in ("fts", "like") else "vector" if src == "vector" else src,
        "score": score,
        "text": text,
        "meta": dict(hit),
    }


def orchestrator_retrieve(
    engine: Any,
    user_input: str,
    hyde_query: str,
    retrieval_plan: Dict[str, Any],
    *,
    session_id: str = "",
    user_id: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], TurnRetrievalResult]:
    """Run unified recall; return (keyword_hits, semantic_hits, turn_result)."""
    mem = getattr(engine, "memory", None)
    empty = TurnRetrievalResult()
    if mem is None:
        return [], [], empty

    kw_limit = int(retrieval_plan.get("keyword_limit") or 12)
    sem_limit = int(retrieval_plan.get("semantic_limit") or 12)
    merge_limit = max(kw_limit, sem_limit, 8)
    verified_only = not is_explicit_memory_audit_query(user_input)

    need_keyword = bool(retrieval_plan.get("need_keyword", True))
    need_semantic = bool(retrieval_plan.get("need_semantic", True))
    if not need_keyword and not need_semantic:
        return [], [], empty

    tr = retrieve_for_turn(
        mem,
        str(hyde_query or user_input or "").strip(),
        user_id=user_id or str(getattr(engine, "user_id", "") or ""),
        session_id=session_id or str(getattr(engine, "session_id", "") or ""),
        semantic_limit=merge_limit,
        conv_limit=max(4, merge_limit // 2),
        recent_limit=int(retrieval_plan.get("recent_limit") or 12),
        summary_limit=int(retrieval_plan.get("summary_limit") or 4),
        hop2_limit=int(retrieval_plan.get("hop2_limit") or 6),
        merge_cap=int(retrieval_plan.get("merge_cap") or 24),
        enable_hop2=bool(retrieval_plan.get("enable_hop2", True)),
        rerank=True,
        use_cache=True,
        verified_only=verified_only,
    )

    keyword_hits: List[Dict[str, Any]] = []
    semantic_hits: List[Dict[str, Any]] = []

    if need_keyword or need_semantic:
        for h in tr.semantic_hits:
            src = str(h.get("_source") or "fts").lower()
            norm = _normalize_hit(h, default_source=src)
            if not norm["text"]:
                continue
            if src in ("fts", "like") and need_keyword:
                keyword_hits.append(norm)
            elif need_semantic:
                semantic_hits.append(norm)

    for h in tr.conv_hits:
        text = (h.get("content") or h.get("text") or "").strip()
        if not text:
            continue
        role = str(h.get("role") or "?")
        prefix = "User said: " if role == "user" else "Assistant said: "
        semantic_hits.append({
            "source": "conversation",
            "score": 0.85,
            "text": f"{prefix}{text}",
            "meta": dict(h),
        })

    return keyword_hits[:kw_limit], semantic_hits[:sem_limit], tr


def format_verified_memory_block(
    tr: TurnRetrievalResult,
    *,
    shown: int = 6,
) -> str:
    """Format verified semantic hits the same way BusMemoryAgent does."""
    hits = list(getattr(tr, "semantic_hits", None) or [])
    if not hits:
        return ""
    lines: List[str] = []
    try:
        from eli.runtime.memory_provenance import format_grounding_memory_line
    except Exception:
        format_grounding_memory_line = None  # type: ignore
    import time as _time
    for h in hits[:shown]:
        if format_grounding_memory_line:
            line = format_grounding_memory_line(h)
            raw_ts = h.get("ts") or h.get("timestamp") or 0
            try:
                ts_str = _time.strftime(
                    "%Y-%m-%d %H:%M", _time.localtime(float(raw_ts)),
                ) if raw_ts else ""
            except Exception:
                ts_str = str(raw_ts or "")
            if ts_str:
                line = line.replace("] ", f"] [{ts_str}] ", 1)
            lines.append(line)
            continue
        txt = (h.get("text") or h.get("content") or "").strip()
        if txt:
            lines.append(f"  - {txt[:240]}")
    if not lines:
        return ""
    return (
        f"Verified stored memories ({len(hits)} found — "
        f"ground user-specific claims ONLY from these rows):\n"
        + "\n".join(lines)
    )
