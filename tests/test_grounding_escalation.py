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


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ELI_GROUNDING_ESCALATION", "0")
    assert G.escalate(_FakeEngine(), "what is eminems real name",
                      {"action": "CHAT"}, _FakeBus(0.10)) is None
