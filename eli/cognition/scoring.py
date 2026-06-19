"""Canonical scoring + confidence primitives for ELI.

ONE owner for the small numeric helpers that were copy-pasted across retrieval, ranking,
reflection, and the agent bus: text tokenisation + stopwords, time-recency decay, term
overlap, and the agent evidence→confidence mappings. Pure, dependency-free, deterministic.

Import from here instead of re-deriving the same maths inline:

    from eli.cognition.scoring import (
        tokenize, STOPWORDS, term_overlap, recency_score,
        conf_from_flag, conf_from_count,
    )
"""
from __future__ import annotations

import re
import time
from typing import Optional

# General-purpose retrieval stopwords (seeded from the reranker's set — its behaviour is the
# reference). Topic-detection code that needs a HEAVIER list (reflection/proactive) keeps its
# own; this is the canonical base for relevance scoring.
STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "to", "of", "in", "on", "at",
    "for", "with", "from", "by", "is", "are", "was", "were", "be", "been", "being",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "do", "does", "did", "can", "could", "should", "would", "will", "may", "might",
    "about", "into", "over", "under", "again", "more", "most", "some", "any", "all",
    "your", "you", "me", "my", "i", "we", "our", "they", "them", "their",
})

_WORD_RE = re.compile(r"[^a-zA-Z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Lowercase content tokens with stopwords + 1-char noise removed."""
    return [t for t in _WORD_RE.split((text or "").lower())
            if t and t not in STOPWORDS and len(t) > 1]


def term_overlap(query: str, text: str) -> float:
    """Fraction of query content-terms present in `text` (0..1)."""
    q = set(tokenize(query))
    if not q:
        return 0.0
    return len(q & set(tokenize(text))) / len(q)


def recency_score(ts: float, now: Optional[float] = None,
                  window_days: float = 30.0) -> float:
    """Linear-decay recency in 0..1 over `window_days` (1.0 = now, 0.0 = at/past the window).
    0.0 for a missing/invalid timestamp."""
    try:
        ts = float(ts or 0)
    except Exception:
        return 0.0
    if ts <= 0:
        return 0.0
    now = now or time.time()
    age_days = (now - ts) / 86400.0
    return max(0.0, 1.0 - age_days / max(1e-6, window_days))


# Canonical memory-ranking fusion weights. ONE source of truth so the recall
# rerank (and any future ranker) share a single, tunable scheme instead of the
# weights drifting across call sites. (The SQL `ORDER BY` in memory.py is a
# deliberately coarse, index-friendly *pre-order* — the real fusion is here.)
MEM_FUSION_W_IMPORTANCE = 0.5
MEM_FUSION_W_WEIGHT = 0.3
MEM_FUSION_W_RECENCY = 0.2

# Overlap-aware recall reranker weights (the later stage that also has query-text
# overlap + source bonus available — see reranker.py). Kept here so all three
# ranking schemes (SQL pre-order, mem fusion, reranker) are tunable in one file.
RERANK_W_OVERLAP = 0.45
RERANK_W_IMPORTANCE = 0.20
RERANK_W_WEIGHT = 0.15
RERANK_W_RECENCY = 0.10


def fuse_memory_score(importance: float, weight: float, recency: float,
                      pref_boost: float = 0.0) -> float:
    """Blend a memory row's importance, decay-weight and recency (each ~0..1)
    into one ranking score, plus an optional preference/identity boost. The
    canonical recall-rerank fusion — see the MEM_FUSION_W_* weights above."""
    try:
        return (
            float(importance or 0.0) * MEM_FUSION_W_IMPORTANCE
            + float(weight or 0.0) * MEM_FUSION_W_WEIGHT
            + float(recency or 0.0) * MEM_FUSION_W_RECENCY
            + float(pref_boost or 0.0)
        )
    except Exception:
        return 0.0


def conf_from_flag(ok: bool, *, hi: float = 0.9, lo: float = 0.2) -> float:
    """Binary evidence → confidence (the 'did the action succeed' agent pattern)."""
    return hi if ok else lo


def conf_from_count(n: int, *, base: float = 0.3, step: float = 0.04,
                    cap: float = 0.9) -> float:
    """Evidence-count → confidence, saturating at `cap` (the 'how many hits' agent pattern)."""
    try:
        n = max(0, int(n))
    except Exception:
        n = 0
    return min(cap, base + n * step)


__all__ = [
    "STOPWORDS", "tokenize", "term_overlap", "recency_score",
    "conf_from_flag", "conf_from_count",
    "fuse_memory_score", "MEM_FUSION_W_IMPORTANCE", "MEM_FUSION_W_WEIGHT",
    "MEM_FUSION_W_RECENCY",
]
