"""Tiered grounding escalation: factual+low-grounding escalates/hedges; banter never does."""
import eli.runtime.grounding_escalation as G
import eli.core.config as C


class _FakeBus:
    def __init__(self, g):
        self.grounding_confidence = g

    def to_context_block(self):
        return "EVIDENCE: Paul David Hewson"


class _FakeEngine:
    session_id = "s"
    user_id = "u"

    def _synthesize_answer(self, evidence, q, reasoning_mode=None, action=None):
        return f"Grounded answer from {action}."


def test_classify_factual_domains():
    assert G.classify_factual("what is bonos real name")[0] is True
    assert G.classify_factual("who is bono") == (True, "external")
    assert G.classify_factual("what is the capital of france") == (True, "external")
    # identity / self → local, never external (never web-searched)
    assert G.classify_factual("who are you")[1] == "local"
    assert G.classify_factual("what model are you running")[1] == "local"
    # banter / opinion / command / chitchat → not factual
    for t in ("how are you", "fuck off", "i hate kendrick", "play the next song",
              "what do you think of jazz", "love ya bud"):
        assert G.classify_factual(t) == (False, "none"), t


def test_advice_questions_are_not_checkable_facts():
    """Advice/how-to questions must never be classed external — else an offline turn
    refuses with 'net's off, can't verify' and an online turn web-searches them
    (user-reported: 'what is the best way to eat breakfast' was refused, then a junk
    web snippet 'Best Buy doesn't offer breakfast recommendations' was surfaced)."""
    for t in ("What is the best way to eat breakfast!",
              "what is the best way to eat lunch?",
              "what's the best way to learn guitar",
              "how should I structure my morning",
              "best way to cook rice",
              "how do I get better at chess",
              "how to make coffee",
              "what should I have for dinner",
              "tips for better sleep",
              "should I use tabs or spaces",
              "help me understand recursion"):
        assert G.classify_factual(t) == (False, "none"), t


def test_real_facts_still_external_despite_advice_gate():
    """The advice gate must not swallow genuine third-party facts."""
    for t in ("who is the president of France",
              "when was the Eiffel tower built",
              "what is the capital of Japan",
              "how old is Tom Hanks",
              "how many moons does Mars have",
              "who won the best actor oscar in 2020",
              "what is the population of Tokyo"):
        assert G.classify_factual(t) == (True, "external"), t


def test_external_online_escalates_to_web(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    import eli.execution.executor_enhanced as E
    # A realistic result snippet echoes the query terms (that's what the engine
    # matched on), so it clears the relevance floor and is synthesised.
    monkeypatch.setattr(
        E, "execute",
        lambda a, args=None: ({"web_grounded": True,
                               "results": [{"title": "Bono - Wikipedia",
                                            "body": "Paul David Hewson is the "
                                                    "real name of the singer bono."}],
                               "content": "Wiki: Bono's real name is Paul David Hewson"}
                              if a == "WEB_SEARCH" else {}))
    r = G.escalate(_FakeEngine(), "what is bonos real name",
                   {"action": "CHAT"}, _FakeBus(0.30))
    assert r is not None and r["meta"]["response_mode"] == "escalation_web"
    assert r["grounded"] is True


def test_offtopic_web_results_hedge_instead_of_confabulating(monkeypatch):
    """DuckDuckGo returning unrelated pages must NOT be synthesised into a confident
    non-answer — the 'Best Buy doesn't offer breakfast recommendations' failure.
    The turn hedges honestly, and says it searched (never 'want me to search?')."""
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    import eli.execution.executor_enhanced as E
    monkeypatch.setattr(
        E, "execute",
        lambda a, args=None: ({"web_grounded": True,
                               "results": [{"title": "Best Buy Official Online Store",
                                            "body": "Shop electronics, laptops and deals."}],
                               "content": "1. Best Buy Official Online Store — Shop electronics"}
                              if a == "WEB_SEARCH" else {}))
    r = G.escalate(_FakeEngine(), "who is the founder of Acme Dynamics Ltd",
                   {"action": "CHAT"}, _FakeBus(0.20))
    assert r is not None and r["meta"]["response_mode"] == "ungrounded_hedge"
    assert r["grounded"] is False
    assert "searched" in r["content"].lower()
    assert "want me to try a web search" not in r["content"].lower()


def test_web_relevance_floor_separates_junk_from_real():
    q = "who is the founder of Acme Dynamics"
    junk = [{"title": "Best Buy", "body": "Shop electronics and appliances today"}]
    real = [{"title": "Acme Dynamics", "body": "Acme Dynamics was founded by Jane Roe"}]
    assert G.web_evidence_relevance(q, junk) < G._web_relevance_floor()
    assert G.web_evidence_relevance(q, real) >= G._web_relevance_floor()
    # one on-topic result among junk is enough (max over results)
    assert G.web_evidence_relevance(q, junk + real) >= G._web_relevance_floor()
    # fails open: no query terms, or non-dict results, never wrongly block
    assert G.web_evidence_relevance("", junk) == 1.0
    assert G.web_evidence_relevance(q, [1, None, "x"]) == 0.0


def test_external_offline_hedges(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: False)
    r = G.escalate(_FakeEngine(), "what is bonos real name",
                   {"action": "CHAT"}, _FakeBus(0.30))
    assert r is not None and r["meta"]["response_mode"] == "ungrounded_hedge"
    assert r["grounded"] is False
    assert "guess" in r["content"].lower() or "verify" in r["content"].lower()


def test_banter_never_escalates(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    assert G.escalate(_FakeEngine(), "how are you bud",
                      {"action": "CHAT"}, _FakeBus(0.20)) is None


def test_a_greeting_phrased_as_a_question_never_escalates(monkeypatch):
    """"Evening Eli, what is the story?" (an idiom for "how are things") was classed as an outside fact and
    searched on the web, while the engine had already classed the turn as a greeting."""
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    import eli.execution.executor_enhanced as E
    searched = []
    monkeypatch.setattr(E, "execute", lambda a, args=None: searched.append(a) or {"ok": True, "results": []})
    for q in ("Evening Eli, what is the story?", "hey, how are you?"):
        assert G.escalate(_FakeEngine(), q, {"action": "CHAT"}, _FakeBus(0.0), reasoning_mode="quick") is None, q
    assert not searched
    assert G.escalate(_FakeEngine(), "Hey Eli, what is the capital of France?", {"action": "CHAT"},
                      _FakeBus(0.0), reasoning_mode="quick") is not None
    assert searched == ["WEB_SEARCH"]


def test_already_grounded_no_escalation(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    assert G.escalate(_FakeEngine(), "what is bonos real name",
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
    assert G.escalate(_FakeEngine(), "what is bonos real name",
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

    r = G.escalate(_DashEngine(), "what is bonos real name",
                   {"action": "CHAT"}, _FakeBus(0.30))
    assert r is not None and r["meta"]["response_mode"] == "ungrounded_hedge"
    assert G._is_degenerate("-") and G._is_degenerate(". . .") and not G._is_degenerate("Detroit")


def test_web_candidate_classic_question():
    assert G.classify_web_candidate("is it a classic ? it is barely out a month...")
    assert G.classify_web_candidate("when did paddington in peru come out?")


def test_web_candidate_escalates_on_very_low_grounding(monkeypatch):
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    import eli.execution.executor_enhanced as E
    monkeypatch.setattr(
        E, "execute",
        lambda a, args=None: ({"web_grounded": True,
                               "results": [{"title": "Paddington in Peru - Wikipedia",
                                            "body": "Released July 31, 2026 in the United States."}],
                               "content": "Wikipedia: released July 31, 2026"}
                              if a == "WEB_SEARCH" else {}))
    r = G.escalate(
        _FakeEngine(),
        "is paddington in peru a classic yet?",
        {"action": "CHAT"},
        _FakeBus(0.18),
        reasoning_mode="quick",
    )
    assert r is not None and r["meta"]["response_mode"] == "escalation_web"


def test_orchestrator_has_pre_generation_escalation():
    import inspect
    from eli.cognition.orchestrator import AgentOrchestrator
    src = inspect.getsource(AgentOrchestrator.run)
    assert "_maybe_grounding_escalate" in src


def test_correction_turn_with_pop_culture_does_not_web_escalate(monkeypatch):
    """User correcting ELI's recency must not trigger Paddington web lookup."""
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    q = "paddington was today, can you not read a fucking timestamp?!"
    assert G.classify_web_candidate(q) is False
    assert G.classify_factual(q) == (False, "none")
    assert G.escalate(_FakeEngine(), q, {"action": "CHAT"}, _FakeBus(0.18)) is None


def test_rapport_and_watch_progress_not_web_candidate(monkeypatch):
    """Compliment + 'feeling fresh? season 3 episode 6 now' is chat, not a web lookup."""
    monkeypatch.setattr(C, "network_allowed", lambda: True)
    q = ("Well, didn't see that coming, fair play, you have a seriously good memory "
         "pal. So you're feeling sharp then? Chapter 4 of the book now")
    assert G.classify_web_candidate(q) is False
    assert G.escalate(_FakeEngine(), q, {"action": "CHAT"}, _FakeBus(0.26)) is None


def test_episode_recap_still_web_candidate():
    q = "what happened in season 3 episode 6 of blue harbor?"
    assert G.classify_web_candidate(q) is True


def test_a_question_about_this_conversation_is_never_an_outside_fact():
    """Live 2026-10-09: "can you tell me when that was?" about "that conversation" was classed an
    outside fact and sent to a web search."""
    for t in ("Looks like i was cross in that chat, can you tell me when that was? "
              "or is there a timestamp?",
              "Check the long reply further up and tell me what date it came from, a timestamp please?",
              "That is not the reply of yours that i meant!"):
        assert G.classify_factual(t) == (False, "none"), t
        assert G.classify_web_candidate(t) is False, t
    assert G.classify_factual("what was the government response to the floods")[1] == "external"


def test_a_question_about_eli_is_never_a_web_lookup():
    """"show me what you are really like ... give it everything" was web-searched and answered with
    "I searched the web but couldn't find anything"."""
    from eli.runtime.grounding_escalation import classify_factual
    assert classify_factual("That is a feeble answer Eli, show me what you are really like when someone pushes "
                            "back. Go on, give it everything, finish it off") == (False, "none")
    assert classify_factual("i wonder what your favourite film is") == (False, "none")
    assert classify_factual("who is the president of france") == (True, "external")
    assert classify_factual("tell me who won the match last night") == (True, "external")
