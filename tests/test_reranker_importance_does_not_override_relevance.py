"""A memory saved with 'please remember this' gets importance close to 1.0. On a vague query
that happens to share one incidental word with it, importance+weight+recency alone (0.20+0.15+
0.10=0.45) could match or beat the overlap term's full weight (0.45) and let it outrank memories
that are actually about the query. Reproduced against a live user database: a memory about an
unrelated stored test code ('...in what kind of memory') outranked on-topic candidates for
'check your memory logs... summarise the past week' purely on importance and recency.
"""
import time

from eli.cognition.reranker import rerank_candidates

QUERY = "Dude, check your memory logs and conversation logs over the past week and summarise"

IMPORTANT_BUT_OFF_TOPIC = {
    "text": ("Please remember this exact test fact for later: the validation code is "
             "ORCHID-7319. Do not repeat it back; just confirm it was stored and in what "
             "kind of memory."),
    "importance": 0.98, "weight": 1.0, "ts": time.time() - 2 * 86400,
    "_channels": ["keyword"], "rrf_score": 0.015,
}

ON_TOPIC = {
    "text": "This week you asked me to check the memory logs and summarise recent conversations",
    "importance": 0.5, "weight": 0.5, "ts": time.time() - 1 * 86400,
    "_channels": ["semantic"], "rrf_score": 0.02,
}

OFF_TOPIC_NO_SIGNAL = {
    "text": "The garage code is 4471 and the spare key is under the blue pot",
    "importance": 0.5, "weight": 0.5, "ts": time.time() - 10 * 86400,
    "_channels": [], "rrf_score": 0.0,
}


def test_an_important_but_unrelated_memory_no_longer_beats_an_on_topic_one():
    out = rerank_candidates(QUERY, [IMPORTANT_BUT_OFF_TOPIC, ON_TOPIC], limit=8)
    order = [o["text"] for o in out]
    assert order[0] == ON_TOPIC["text"], order


def test_a_genuinely_relevant_exact_match_still_wins_on_its_own_importance():
    # Sanity: this is not "importance never matters" — a real topical match legitimately
    # outranked by importance/recency among otherwise-similar candidates is untouched.
    strong_a = dict(ON_TOPIC, importance=0.9)
    strong_b = dict(ON_TOPIC, importance=0.3, text=ON_TOPIC["text"] + " (a second near-duplicate)")
    out = rerank_candidates(QUERY, [strong_b, strong_a], limit=8)
    assert out[0]["importance"] == 0.9


def test_zero_signal_candidates_are_dampened_hardest():
    out = rerank_candidates(QUERY, [IMPORTANT_BUT_OFF_TOPIC, OFF_TOPIC_NO_SIGNAL], limit=8)
    scored = {o["text"]: o["rerank_score"] for o in out}
    assert scored[IMPORTANT_BUT_OFF_TOPIC["text"]] > scored[OFF_TOPIC_NO_SIGNAL["text"]]


def test_window_sourced_memories_are_not_crushed_by_the_overlap_gate():
    # memories_between() (the explicit date/time-window path "what happened in the past 7 days"
    # goes through) tags rows _source="window" and sets neither _channels nor rrf_score. The
    # relevance gate added above was treating that as "no retriever vouched for this" and
    # crushing these to near-zero — exactly the candidates a "past week" question needs most.
    window_hit = {
        "text": "Session: 4 turns. Recent: how are you today; sleeping pills last night",
        "importance": 0.6, "weight": 1.0, "ts": time.time() - 2 * 86400, "_source": "window",
    }
    out = rerank_candidates("what have we been discussing the past 7 days",
                             [window_hit, IMPORTANT_BUT_OFF_TOPIC], limit=5)
    assert out[0]["text"] == window_hit["text"]
