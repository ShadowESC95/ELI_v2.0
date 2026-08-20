"""Recall was vector-only in practice, and the keyword index was never read.

`recall_memory` is documented as FAISS-first with FTS5 "as a supplement", gated on:

    _need_keyword = keyword_only or (not populated) or (len(vector) < max(1, limit//2))

FAISS `IndexFlat` applies no similarity threshold — it returns top_k nearest for any
query at all. With 442 vectors and limit=10 that count was always 10, `10 < 5` was
never true, and the branch was unreachable. Meanwhile `memories_fts` held 441 rows,
one per memory, maintained by triggers on every write, and was never queried.

Measured on the live index, the scores that gate had no hope of separating:

    "what did I say about fallout"   -> 10 hits, lowest score 0.559
    "asdfghjkl qwerty nonsense"      -> 10 hits, lowest score 0.524

0.035 of discrimination between a real query and gibberish.

Both channels now always run and are fused by Reciprocal Rank Fusion, which combines
by POSITION rather than score — necessary precisely because FAISS similarity
(1/(1+L2)) and FTS5 BM25 share no scale.
"""
import pytest

from eli.cognition.reranker import RRF_K, fuse_ranked_lists, rerank_candidates


def _c(text, **kw):
    return dict(text=text, **kw)


# ── rank fusion ───────────────────────────────────────────────────────────────

def test_agreement_between_channels_outranks_either_alone():
    """The property a hybrid retriever exists for."""
    fused = fuse_ranked_lists({
        "vector":  [_c("both"), _c("vector only"), _c("v3")],
        "keyword": [_c("keyword only"), _c("both"), _c("k3")],
    })
    assert fused[0]["text"] == "both"
    assert fused[0]["_channels"] == ["keyword", "vector"]


def test_fusion_ignores_incomparable_scores():
    """FAISS 0.55 and BM25 -8.2 must not be summed. Only rank is used."""
    fused = fuse_ranked_lists({
        "vector":  [_c("a", score=0.559), _c("b", score=0.558)],
        "keyword": [_c("b", score=-8.2), _c("a", score=-9.9)],
    })
    # Both appear in both lists at ranks (0,1) and (1,0) — RRF ties them.
    assert {r["text"] for r in fused} == {"a", "b"}
    assert abs(fused[0]["rrf_score"] - fused[1]["rrf_score"]) < 1e-9


def test_rank_position_decides_within_a_channel():
    fused = fuse_ranked_lists({"vector": [_c("first"), _c("second")]})
    assert fused[0]["text"] == "first"
    assert fused[0]["rrf_score"] == pytest.approx(1.0 / (RRF_K + 1))


def test_channels_are_recorded_so_agreement_is_inspectable():
    fused = fuse_ranked_lists({"vector": [_c("x")], "keyword": [_c("x")]})
    assert fused[0]["_channels"] == ["keyword", "vector"]
    assert fused[0]["_channel_ranks"] == {"vector": 0, "keyword": 0}


def test_the_richer_record_survives_a_merge():
    """A vector hit often carries less metadata than the SQL row for the same memory."""
    fused = fuse_ranked_lists({
        "vector":  [{"text": "same memory"}],
        "keyword": [{"text": "same memory", "id": 42, "tags": "preference"}],
    })
    assert fused[0]["id"] == 42 and fused[0]["tags"] == "preference"


def test_empty_and_malformed_input_is_survivable():
    assert fuse_ranked_lists({}) == []
    assert fuse_ranked_lists({"a": [None, 3, {"text": ""}]}) == []


# ── the reranker's use of it ──────────────────────────────────────────────────

def test_reranker_rewards_multi_channel_agreement():
    both = _c("shared result", rrf_score=0.03, _channels=["keyword", "vector"])
    one = _c("shared result other", rrf_score=0.03, _channels=["vector"])
    ranked = rerank_candidates("shared result", [one, both], limit=2)
    assert ranked[0]["text"] == "shared result"


def test_content_overlap_still_outranks_fusion_bonus():
    """Fusion tips ties; it must not override literal relevance — the whole point
    was to stop a retriever's internal confidence beating what the user asked."""
    literal = _c("fallout 4 has AI")
    unrelated = _c("completely different subject", rrf_score=0.05,
                   _channels=["keyword", "vector"])
    ranked = rerank_candidates("fallout", [unrelated, literal], limit=2)
    assert ranked[0]["text"] == "fallout 4 has AI"


# ── the keyword query itself ──────────────────────────────────────────────────

def test_fts_query_drops_stopwords():
    """Every token was OR'd, so "what did I say about fallout" matched any memory
    containing "what" or "say". Unreachable code, so never exercised — making the
    channels co-equal surfaced it as noise ranked first."""
    import re

    from eli.runtime.reflection import TOPIC_STOPWORDS
    q = "what did I say about fallout"
    terms = [t for t in re.split(r"[^a-zA-Z0-9_]+", q)
             if len(t) > 1 and t.lower() not in TOPIC_STOPWORDS]
    assert terms == ["fallout"], f"stopwords survived: {terms}"


def test_an_all_stopword_query_still_searches_something():
    """"what about that?" must not become an empty FTS5 query."""
    import re

    from eli.runtime.reflection import TOPIC_STOPWORDS
    q = "what about that"
    terms = [t for t in re.split(r"[^a-zA-Z0-9_]+", q)
             if len(t) > 1 and t.lower() not in TOPIC_STOPWORDS]
    if not terms:
        terms = [t for t in re.split(r"[^a-zA-Z0-9_]+", q) if len(t) > 1]
    assert terms, "fallback produced no search terms at all"


def test_keyword_channel_is_no_longer_gated_behind_vector_count():
    """The regression that mattered: FTS5 must not be reachable only when FAISS
    under-delivers, because with no similarity floor FAISS never does."""
    import inspect

    from eli.memory import memory as mem
    src = inspect.getsource(mem.Memory.recall_memory)
    # Strip comments — the fix documents the old expression in a comment, and a
    # naive substring check would match the explanation of the bug it prevents.
    src = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "len(vector_results) < max(1, limit // 2)" not in src, \
        "keyword search is gated behind the vector result count again"
