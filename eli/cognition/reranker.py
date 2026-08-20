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

# Reciprocal Rank Fusion constant. 60 is the value from the original Cormack et al.
# paper and the de-facto default in production hybrid search (Elasticsearch, Vespa,
# Weaviate) — large enough that the top few ranks are not winner-take-all, small
# enough that deep ranks stop mattering.
RRF_K = 60


def fuse_ranked_lists(lists: "dict[str, list]", *, k: int = RRF_K,
                      key=None) -> "list[dict]":
    """Merge several ranked candidate lists by RANK, not by score.

    Why rank fusion rather than blending the scores: the two retrievers produce
    numbers that are not comparable and, in ELI's case, barely discriminate. FAISS
    similarity here is `1/(1+L2)`, which compressed a real query to 0.559 and pure
    gibberish to 0.524 — 0.035 of separation, with no threshold that could
    separate them. FTS5 emits BM25, an unbounded negative. Any weighted sum of the
    two is arbitrary and needs retuning whenever either side changes.

    RRF sidesteps that entirely: a document scores `sum(1 / (k + rank))` over the
    lists it appears in. Only its POSITION in each list matters, so the scales never
    have to agree — and a document found by both channels naturally outranks one
    found by either alone, which is the property a hybrid retriever exists for.

    `lists` maps a channel name to its ranked candidates (best first). The channel
    each document came from is recorded on the result as `_channels`, so a caller
    can tell a both-channels agreement from a single-channel guess.
    """
    if key is None:
        def key(c):
            text = str((c or {}).get("text") or (c or {}).get("content") or "")
            return text[:220].strip().lower()

    fused: dict = {}
    for channel, items in (lists or {}).items():
        for rank, cand in enumerate(items or []):
            if not isinstance(cand, dict):
                continue
            ident = key(cand)
            if not ident:
                continue
            slot = fused.get(ident)
            if slot is None:
                slot = {"candidate": dict(cand), "rrf": 0.0, "channels": [],
                        "ranks": {}}
                fused[ident] = slot
            slot["rrf"] += 1.0 / (k + rank + 1)
            slot["channels"].append(channel)
            slot["ranks"][channel] = rank
            # Union the metadata when the same memory arrives from both channels.
            # A vector hit typically lacks the id/tags/kind the SQL row carries, and
            # comparing text length missed that entirely when both texts matched —
            # the field-poor record simply won on arrival order.
            for field, value in cand.items():
                if value in (None, "", []):
                    continue
                if slot["candidate"].get(field) in (None, "", []):
                    slot["candidate"][field] = value

    out = []
    for slot in fused.values():
        row = dict(slot["candidate"])
        # 9dp, not 6: at k=60 adjacent ranks differ in the 7th place, and
        # rounding to 6 collapsed distinct ranks into equal scores.
        row["rrf_score"] = round(slot["rrf"], 9)
        row["_channels"] = sorted(set(slot["channels"]))
        row["_channel_ranks"] = slot["ranks"]
        out.append(row)
    out.sort(key=lambda r: r.get("rrf_score", 0.0), reverse=True)
    return out


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

        # Retrieval agreement. When the candidate came through fuse_ranked_lists,
        # rrf_score already encodes "how highly did each retriever rank this, and
        # did more than one find it at all". Content signals above still decide
        # ordering; this tips ties toward documents both channels agreed on, which
        # is the signal a single retriever cannot produce.
        rrf = _as_float(c.get("rrf_score", 0.0), 0.0)
        if rrf:
            score += min(rrf, 0.05) * 2.0          # bounded: never dominates overlap
            if len(c.get("_channels") or []) > 1:
                score += 0.05                       # found by keyword AND vector

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
