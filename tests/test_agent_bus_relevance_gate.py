"""_aggregate_confidence must discount a result's contribution by whether its text is
actually about the query — a maximally confident, evidence-dense but off-topic result
should not score as highly as an on-topic one. The reranker.py-level gap, one layer up."""
import pytest

from eli.cognition.agent_bus import AgentResult, _aggregate_confidence


def _result(agent: str, text: str, confidence: float = 0.9) -> AgentResult:
    return AgentResult(agent=agent, ok=True, confidence=confidence,
                        data={"content": text}, elapsed_ms=1.0)


ON_TOPIC = "The RAIMS ingestion pipeline uses SQLite for the staging store and needs retry backoff."
OFF_TOPIC = "Yesterday's weather in Chicago was unusually warm for late September, near seventy degrees."
QUERY = "what's the status of the RAIMS ingestion pipeline"


def test_off_topic_evidence_scores_lower_than_on_topic_evidence():
    on_score, on_ground = _aggregate_confidence(0.5, [_result("a", ON_TOPIC)], "CHAT", QUERY)
    off_score, off_ground = _aggregate_confidence(0.5, [_result("a", OFF_TOPIC)], "CHAT", QUERY)
    assert on_ground > off_ground
    assert on_score > off_score


def test_short_representative_text_is_not_gated():
    # Below _RELEVANCE_MIN_TEXT_CHARS (40): too little text for term_overlap to mean
    # anything, so it must NOT be penalised just for being short. Equal-length strings
    # isolate relevance from _evidence_density's own length sensitivity.
    short_on_topic, _ = _aggregate_confidence(0.5, [_result("a", "the RAIMS status ok")], "CHAT", QUERY)
    short_off_topic, _ = _aggregate_confidence(0.5, [_result("a", "the weather is nice")], "CHAT", QUERY)
    assert short_on_topic == short_off_topic


def test_empty_user_input_disables_gating_entirely():
    # Callers that don't pass user_input (back-compat with the pre-gate 3-arg signature)
    # must see unchanged behaviour — relevance defaults to 1.0 across the board.
    with_query, _ = _aggregate_confidence(0.5, [_result("a", OFF_TOPIC)], "CHAT", QUERY)
    no_query, _ = _aggregate_confidence(0.5, [_result("a", OFF_TOPIC)], "CHAT")
    assert no_query > with_query


def test_env_var_disables_the_gate(monkeypatch):
    monkeypatch.setenv("ELI_AGENT_BUS_RELEVANCE_GATE", "0")
    gated_off, _ = _aggregate_confidence(0.5, [_result("a", OFF_TOPIC)], "CHAT", QUERY)
    monkeypatch.setenv("ELI_AGENT_BUS_RELEVANCE_GATE", "1")
    gated_on, _ = _aggregate_confidence(0.5, [_result("a", OFF_TOPIC)], "CHAT", QUERY)
    assert gated_off > gated_on


def test_three_arg_call_still_works():
    # The pre-existing call shape (no user_input) must not raise.
    score, ground = _aggregate_confidence(0.5, [_result("a", ON_TOPIC)], "CHAT")
    assert 0.0 <= score <= 1.0 and 0.0 <= ground <= 1.0
