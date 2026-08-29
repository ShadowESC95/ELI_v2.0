"""Shared turn retrieval — single owner for semantic + conversation recall.

Both ``AgentBus`` (``BusMemoryAgent``) and ``AgentOrchestrator`` call here so
memory is not searched twice with divergent budgets on the same turn.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


@dataclass
class TurnRetrievalResult:
    semantic_hits: List[Dict[str, Any]] = field(default_factory=list)
    conv_hits: List[Dict[str, Any]] = field(default_factory=list)
    recent_turns: List[Dict[str, Any]] = field(default_factory=list)
    summaries: List[Dict[str, Any]] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0
    cache_key: str = ""

# Per-process turn cache: key → (monotonic_ts, result)
_TURN_CACHE: Dict[str, tuple[float, TurnRetrievalResult]] = {}
_CACHE_TTL_S = 8.0


def _cache_get(key: str) -> Optional[TurnRetrievalResult]:
    slot = _TURN_CACHE.get(key)
    if slot is None:
        return None
    ts, entry = slot
    if (time.monotonic() - ts) > _CACHE_TTL_S:
        _TURN_CACHE.pop(key, None)
        return None
    return entry


def invalidate_turn_cache(session_id: str = "") -> None:
    if not session_id:
        _TURN_CACHE.clear()
        return
    prefix = f"{session_id}:"
    for k in list(_TURN_CACHE):
        if k.startswith(prefix):
            _TURN_CACHE.pop(k, None)


def retrieve_for_turn(
    mem: Any,
    query: str,
    *,
    user_id: str = "",
    session_id: str = "",
    semantic_limit: int = 12,
    conv_limit: int = 8,
    recent_limit: int = 12,
    summary_limit: int = 4,
    hop2_limit: int = 6,
    merge_cap: int = 24,
    enable_hop2: bool = True,
    rerank: bool = True,
    use_cache: bool = True,
) -> TurnRetrievalResult:
    """Retrieve, optionally deepen, rerank, and dedupe memory evidence for one turn."""
    t0 = time.perf_counter()
    q = (query or "").strip()
    cache_key = f"{session_id}:{user_id}:{q.lower()[:240]}"
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    raw_hits: List[Dict[str, Any]] = []
    try:
        raw_hits = list(mem.recall_memory(q, limit=int(semantic_limit)) or [])
    except Exception as exc:
        log.debug(f"[RETRIEVAL] recall_memory failed: {exc}")

    conv_hits: List[Dict[str, Any]] = []
    try:
        conv_hits = list(
            mem.search_conversations(q, user_id=user_id, limit=int(conv_limit)) or []
        )
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    recent: List[Dict[str, Any]] = []
    try:
        recent = list(mem.get_recent_conversation(limit=int(recent_limit), user_id=user_id) or [])
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    summaries: List[Dict[str, Any]] = []
    try:
        summaries = list(mem.get_session_summaries(user_id=user_id, limit=int(summary_limit)) or [])
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    if enable_hop2 and 0 < len(raw_hits) < 5:
        try:
            from eli.cognition.agent_bus import _memory_seed_terms
            _seed = (raw_hits[0].get("text") or raw_hits[0].get("content") or "")
            _terms = _memory_seed_terms(_seed, k=5)
            if _terms:
                _seen_ids = {h.get("id") for h in raw_hits if h.get("id")}
                _seen_txt = {(h.get("text") or h.get("content") or "")[:80] for h in raw_hits}
                _hop2 = mem.recall_memory(" ".join(_terms), limit=int(hop2_limit)) or []
                for _h in _hop2:
                    _hid = _h.get("id")
                    _ht = (_h.get("text") or _h.get("content") or "")[:80]
                    if (_hid and _hid in _seen_ids) or _ht in _seen_txt:
                        continue
                    raw_hits.append(_h)
                    _seen_ids.add(_hid)
                    _seen_txt.add(_ht)
                    if len(raw_hits) >= int(merge_cap):
                        break
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    contradictions: List[Dict[str, Any]] = []
    if rerank and raw_hits:
        try:
            from eli.cognition.reranker import rerank_candidates
            raw_hits = rerank_candidates(q, raw_hits, limit=len(raw_hits))
        except Exception:
            log.debug("suppressed exception", exc_info=True)
    try:
        from eli.cognition.agent_bus import _detect_contradictions
        contradictions = _detect_contradictions(raw_hits)
    except Exception:
        contradictions = []

    elapsed = (time.perf_counter() - t0) * 1000
    result = TurnRetrievalResult(
        semantic_hits=raw_hits,
        conv_hits=conv_hits,
        recent_turns=recent,
        summaries=summaries,
        contradictions=contradictions,
        elapsed_ms=elapsed,
        cache_key=cache_key,
    )
    if use_cache and q:
        _TURN_CACHE[cache_key] = (time.monotonic(), result)
    return result
