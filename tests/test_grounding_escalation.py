"""Tiered grounding escalation: factual+low-grounding escalates/hedges; banter never does."""
import eli.runtime.grounding_escalation as G
import eli.core.config as C


class _FakeBus:
    def __init__(self, g):
        self.grounding_confidence = g

    def to_context_block(self):
        return "EVIDENCE: Marshall Bruce Mathers III"


class _FakeEngine:
    session_id = "s"
    user_id = "u"

    def _synthesize_answer(self, evidence, q, reasoning_mode=None, action=None):
        return f"Grounded answer from {action}."


def test_classify_factual_domains():
    assert G.classify_factual("what is eminems real name")[0] is True
    assert G.classify_factual("who is eminem") == (True, "external")
    assert G.classify_factual("what is the capital of france") == (True, "external")
    # identity / self → local, never external (never web-searched)
    assert G.classify_factual("who are you")[1] == "local"
    assert G.classify_factual("what model are you running")[1] == "local"
    # banter / opinion / command / chitchat → not factual
    for t in ("how are you", "fuck off", "i hate kendrick", "play the next song",
              "what do you think of claude", "love ya bud"):
        assert G.classify_factual(t) == (False, "none"), t


def test_external_online_escalates_to_web(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    import eli.execution.executor_enhanced as E
    monkeypatch.setattr(
        E, "execute",
        lambda a, args=None: ({"web_grounded": True, "results": [1],
                               "content": "Wiki: Marshall Bruce Mathers III"}
                              if a == "WEB_SEARCH" else {}))
    r = G.escalate(_FakeEngine(), "what is eminems real name",
                   {"action": "CHAT"}, _FakeBus(0.30))
    assert r is not None and r["meta"]["response_mode"] == "escalation_web"
    assert r["grounded"] is True


def test_external_offline_hedges(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: False)
    r = G.escalate(_FakeEngine(), "what is eminems real name",
                   {"action": "CHAT"}, _FakeBus(0.30))
    assert r is not None and r["meta"]["response_mode"] == "ungrounded_hedge"
    assert r["grounded"] is False
    assert "guess" in r["content"].lower() or "verify" in r["content"].lower()


def test_banter_never_escalates(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    assert G.escalate(_FakeEngine(), "how are you bud",
                      {"action": "CHAT"}, _FakeBus(0.20)) is None


def test_already_grounded_no_escalation(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    assert G.escalate(_FakeEngine(), "what is eminems real name",
                      {"action": "CHAT"}, _FakeBus(0.80)) is None


def test_self_action_state_claim_hedges_when_ungrounded(monkeypatch):
    # ELI must NOT confabulate a job status / saved-file path it has no grounding for.
    monkeypatch.setenv("ELI_GROUNDING_ESCALATION", "1")
    for q in ("did you not save your review/summary as a document?",
              "check job #4 please",
              "gone past the hour and a half mark on job #5, status report?",
              "where did you save it"):
        r = G.escalate(_FakeEngine(), q, {"action": "CHAT"}, _FakeBus(0.0),
                       reasoning_mode="quick", trace={})
        assert r is not None and not r.get("grounded"), q
        assert "invent" in (r.get("content") or "").lower(), q  # honest hedge, not a status


def test_self_action_claim_not_hedged_when_grounded(monkeypatch):
    # A real grounded answer (job data actually present) must pass through, not hedge.
    monkeypatch.setenv("ELI_GROUNDING_ESCALATION", "1")
    assert G.escalate(_FakeEngine(), "did you save the summary?", {"action": "CHAT"},
                      _FakeBus(0.85), reasoning_mode="quick", trace={}) is None


def test_self_action_regex_excludes_chitchat_and_capability():
    R = G._SELF_ACTION_STATE_RE
    for q in ("good morning eli", "thanks pal", "do you like coffee",
              "do you do that often", "play some music", "summarise that folder"):
        assert not R.search(q.lower()), q


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ELI_GROUNDING_ESCALATION", "0")
    assert G.escalate(_FakeEngine(), "what is eminems real name",
                      {"action": "CHAT"}, _FakeBus(0.10)) is None


def test_self_meta_questions_never_escalate(monkeypatch):
    # Regression: self-referential "what are you doing / how do you not know"
    # questions were classified external → web-searched → produced a degenerate
    # "-" answer. They must be non-factual (answered as conversational CHAT).
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    for t in [
        "what are you busy fixing",
        "you just mentioned above that you are fixing things how do you not know what you were doing",
        "what are you working on",
        "what do you mean",
        "why did you say that",
    ]:
        assert G.classify_factual(t) == (False, "none"), t
        assert G.escalate(_FakeEngine(), t, {"action": "CHAT"}, _FakeBus(0.20)) is None, t


def test_frustration_and_relational_vent_never_escalate(monkeypatch):
    # Regression (user-reported, 2026-06-06): a frustrated user got robotic grounding
    # hedges. Profanity injected mid-question ("what THE FUCK are you talking
    # about") broke the meta gate, and "what is going on with you" (vs the
    # contraction "what's") slipped through — both were classified factual and
    # routed to the web/hedge ladder. They must be non-factual conversational.
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    for t in [
        "What the fuck are you talking about?!",
        "Eli, what is going on with you?",
        "What the fuck is going on?!",
        "what is going on?!",
        "what's wrong with you",
        "what the hell is your problem",
        "what the fuck do you mean",
    ]:
        assert G.classify_factual(t) == (False, "none"), t
        assert G.escalate(_FakeEngine(), t, {"action": "CHAT"}, _FakeBus(0.20)) is None, t
    # Guard: a genuine current-events question must still escalate (not be eaten
    # by the relational-vent pattern).
    assert G.classify_factual("what is going on in ukraine") == (True, "external")


def test_degenerate_answer_falls_through_to_hedge(monkeypatch):
    # A model that synthesises a degenerate "-" must NOT surface it; the external
    # ladder falls through to the honest hedge instead.
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    import eli.execution.executor_enhanced as E
    monkeypatch.setattr(
        E, "execute",
        lambda a, args=None: ({"web_grounded": True, "results": [1], "content": "x"}
                              if a == "WEB_SEARCH" else {}))

    class _DashEngine(_FakeEngine):
        def _synthesize_answer(self, evidence, q, reasoning_mode=None, action=None):
            return "-"

    r = G.escalate(_DashEngine(), "what is eminems real name",
                   {"action": "CHAT"}, _FakeBus(0.30))
    assert r is not None and r["meta"]["response_mode"] == "ungrounded_hedge"
    assert G._is_degenerate("-") and G._is_degenerate(". . .") and not G._is_degenerate("Detroit")
