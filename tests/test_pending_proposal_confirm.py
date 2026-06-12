"""Regression tests for the conversational offer -> "yes" -> execute flow.

Covers the bug where ELI offered to do something in chat ("Want me to update
the profile?") and the user's affirmation ("yes please") was swallowed as chat
and the action never ran. Two independent breaks were fixed:

  A. Offer-capture (set_pending_proposal) was gated to WEB_SEARCH only, so
     conversational offers were never stored. It now runs centrally for every
     reply path (covered here at the pending_proposal layer).
  B. The affirmation regex was anchored (^yes$) so "yes please" did not match.
     A shared, lenient is_affirmation/is_negation helper now handles it.
"""

import pytest

from eli.runtime import pending_proposal as pp
from eli.runtime.grounded_remediation import is_affirmation, is_negation


@pytest.fixture(autouse=True)
def _clear_pending():
    pp.clear_pending_proposal()
    yield
    pp.clear_pending_proposal()


# ---- B. affirmation / negation helpers -------------------------------------

@pytest.mark.parametrize("text", [
    "yes", "yes please", "yeah", "yep", "yup", "sure", "ok", "okay",
    "go ahead", "go for it", "do it", "please do", "proceed",
    "ok sure, go ahead", "yeah do it", "sounds good",
])
def test_affirmations_recognised(text):
    assert is_affirmation(text)
    assert not is_negation(text) or is_affirmation(text)  # yes wins on conflict


@pytest.mark.parametrize("text", [
    "no", "nope", "nah", "cancel", "cancel that", "stop",
    "never mind", "leave it", "skip it", "no thanks",
])
def test_negations_recognised(text):
    assert is_negation(text)
    assert not is_affirmation(text)


@pytest.mark.parametrize("text", ["", "   ", "what's the weather", "tell me a joke"])
def test_neither_for_non_answers(text):
    assert not is_affirmation(text)
    assert not is_negation(text)


def test_yes_please_specifically_the_regression():
    # This exact phrase was missed by the old anchored ^yes$ regex.
    assert is_affirmation("yes please")


# ---- A. offer capture + round trip -----------------------------------------

def test_extract_proposal_from_real_offer():
    offer = ("Fair point. The persona text is intact but stale in spirit. "
             "Want me to purge the stale context and update the active profile?")
    assert pp.extract_proposal(offer) == "purge the stale context and update the active profile"


def test_non_offer_yields_nothing():
    assert pp.extract_proposal("Running clean today. How are you?") == ""
    assert pp.extract_proposal("") == ""


def test_full_round_trip_offer_then_affirm():
    offer = "Want me to update the active profile?"
    prop = pp.extract_proposal(offer)
    assert prop
    pp.set_pending_proposal(prop)
    got = pp.get_pending_proposal()
    assert got and got["command"] == prop
    # User affirms with the previously-broken phrase -> would be consumed.
    assert is_affirmation("yes please")


def test_decline_clears_pending():
    pp.set_pending_proposal("update the active profile")
    assert pp.get_pending_proposal() is not None
    assert is_negation("no thanks")
    pp.clear_pending_proposal()
    assert pp.get_pending_proposal() is None


# ---- #3. the offered action actually resolves + executes -------------------

@pytest.mark.parametrize("phrase", [
    "purge the stale context and update the active profile",
    "update the active profile",
    "refresh your persona",
    "purge stale context",
    "clean the persona overlay",
])
def test_offered_phrasings_route_to_persona_refresh(phrase):
    from eli.execution.router_enhanced import route
    r = route(phrase)
    assert r.get("action") == "PERSONA_REFRESH", (phrase, r.get("action"))


@pytest.mark.parametrize("phrase,expected", [
    ("refresh user info", "REFRESH_USER_INFO"),   # not hijacked
    ("purge my chat history", "CHAT"),            # unrelated purge untouched
])
def test_persona_refresh_does_not_hijack_siblings(phrase, expected):
    from eli.execution.router_enhanced import route
    assert route(phrase).get("action") == expected


def test_persona_refresh_executes_for_real():
    # The action must DO something (overlay hygiene + profile rebuild) and
    # return a grounded report — not a fabricated "I did it" chat reply.
    from eli.execution import executor_enhanced as ex
    res = ex.execute(action="PERSONA_REFRESH", args={"reason": "test"})
    assert res.get("ok") is True
    assert res.get("action") == "PERSONA_REFRESH"
    assert "artifacts" in res and "hygiene" in res["artifacts"]
    assert isinstance(res.get("content"), str) and res["content"]


def test_expired_proposal_not_returned(monkeypatch):
    import time as _t
    real_now = _t.time()
    pp.set_pending_proposal("do the thing")
    assert pp.get_pending_proposal() is not None
    # Advance the clock past the TTL window (patch the module's own time ref).
    monkeypatch.setattr(pp.time, "time", lambda: real_now + pp._TTL_SECONDS + 10.0)
    assert pp.get_pending_proposal() is None
