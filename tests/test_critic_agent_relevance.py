"""CriticAgent's corroboration score must not be fooled by two sources agreeing with
EACH OTHER while both being off-topic for what was actually asked."""
from eli.cognition.agent_bus import CriticAgent

ON_TOPIC_A = "The RAIMS ingestion pipeline stages data in SQLite before the retry queue processes it."
ON_TOPIC_B = "RAIMS uses a SQLite staging store, then a retry queue handles failed ingestion batches."
OFF_TOPIC_A = "The bakery on Fifth Street sells sourdough every Tuesday and Friday morning."
OFF_TOPIC_B = "Sourdough baked fresh every Tuesday and Friday is the bakery's best seller."
QUERY = "what's the status of the RAIMS ingestion pipeline"


def _intent(upstream: dict) -> dict:
    return {"_upstream": upstream}


def test_on_topic_corroboration_scores_higher_than_off_topic_corroboration():
    critic = CriticAgent()
    on = critic.run(QUERY, _intent({"memory": {"content": ON_TOPIC_A},
                                     "system": {"content": ON_TOPIC_B}}), "s", "u")
    off = critic.run(QUERY, _intent({"memory": {"content": OFF_TOPIC_A},
                                      "system": {"content": OFF_TOPIC_B}}), "s", "u")
    assert on.ok and off.ok
    assert not on.data.get("contradiction")
    assert not off.data.get("contradiction")
    # Both pairs agree with EACH OTHER (that's the whole point of this test), but only
    # one pair is actually about the query — its confidence must come out higher.
    assert on.confidence > off.confidence


def test_contradiction_branch_is_unaffected_by_relevance():
    # Genuinely disagreeing sources should stay low-confidence regardless of topic —
    # the relevance factor only applies inside the corroboration branch.
    critic = CriticAgent()
    r = critic.run(QUERY, _intent({"memory": {"content": ON_TOPIC_A},
                                    "system": {"content": "Completely unrelated text about tax law filings."}}),
                    "s", "u")
    assert r.ok
    if r.data.get("contradiction"):
        assert r.confidence == 0.25


def test_relevance_gate_disabled_falls_back_to_pure_agreement(monkeypatch):
    monkeypatch.setenv("ELI_AGENT_BUS_RELEVANCE_GATE", "0")
    critic = CriticAgent()
    off = critic.run(QUERY, _intent({"memory": {"content": OFF_TOPIC_A},
                                      "system": {"content": OFF_TOPIC_B}}), "s", "u")
    monkeypatch.setenv("ELI_AGENT_BUS_RELEVANCE_GATE", "1")
    assert off.ok and not off.data.get("contradiction")
    # ungated: confidence is purely agreement-derived, same formula as before this change
    assert off.confidence == round(min(0.9, 0.4 + off.data["agreement"]), 3)


def test_fewer_than_two_sources_still_self_gates():
    critic = CriticAgent()
    r = critic.run(QUERY, _intent({"memory": {"content": ON_TOPIC_A}}), "s", "u")
    assert r.ok and r.confidence == 0.0 and r.data.get("skipped")
