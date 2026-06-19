from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List

# Canonical text + recency primitives (one owner — no bespoke stopwords/tokeniser here).
from eli.cognition.scoring import (
    tokenize as _tok, recency_score as _recency_score,
    RERANK_W_OVERLAP as _W_OVERLAP, RERANK_W_IMPORTANCE as _W_IMPORTANCE,
    RERANK_W_WEIGHT as _W_WEIGHT, RERANK_W_RECENCY as _W_RECENCY,
)


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)

def rerank_candidates(query: str, candidates: Iterable[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    """
    Dependency-free fallback reranker.
    This is not a true cross-encoder yet, but it gives Stage 9 a real owner and
    a clean upgrade point later.
    """
    q_toks = set(_tok(query))
    now = time.time()
    out: list[dict] = []
    seen: set[str] = set()

    for idx, c in enumerate(candidates or []):
        if not isinstance(c, dict):
            continue

        text = str(c.get("text") or c.get("content") or "").strip()
        if not text:
            continue

        dedupe_key = text[:220].lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        t_toks = set(_tok(text))
        overlap = (len(q_toks & t_toks) / max(1, len(q_toks))) if q_toks else 0.0

        importance = _as_float(c.get("importance", 0.5), 0.5)
        weight = _as_float(c.get("weight", 0.5), 0.5)
        ts = _as_float(c.get("ts", c.get("timestamp", 0)), 0.0)
        recency = _recency_score(ts, now=now, window_days=30.0)

        source = str(c.get("source") or c.get("_source") or c.get("kind") or "").lower()
        source_bonus = 0.0
        if source in ("semantic", "knowledge_graph", "kg"):
            source_bonus += 0.15
        if source in ("vector", "fts", "like"):
            source_bonus += 0.05

        score = (
            overlap * _W_OVERLAP
            + importance * _W_IMPORTANCE
            + min(weight, 2.0) / 2.0 * _W_WEIGHT
            + recency * _W_RECENCY
            + source_bonus
        )

        row = dict(c)
        row["rerank_score"] = round(score, 6)
        row["rerank_rank"] = idx
        out.append(row)

    out.sort(key=lambda x: (
        _as_float(x.get("rerank_score", 0.0), 0.0),
        _as_float(x.get("importance", 0.0), 0.0),
        _as_float(x.get("weight", 0.0), 0.0),
        _as_float(x.get("ts", x.get("timestamp", 0.0)), 0.0),
    ), reverse=True)

    return out[: int(limit or 8)]
