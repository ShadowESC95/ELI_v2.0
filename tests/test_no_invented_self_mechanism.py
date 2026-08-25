"""ELI must not invent accounts of its own internals.

Routing happens before the model is called and no record of the decision reaches
the prompt, so ELI has no introspective access to why a guard fired. Asked at
2.3.26 why a guard had not caught a data dump, it answered:

    "I didn't have a chance to activate the guard - and honestly, I'm still
     figuring out why it's not triggering"

The mechanism is real; the account of it is invented. That is the most
convincing kind of confabulation and the hardest for the user to check --
it sounds like privileged self-knowledge.

Grounded turns are exempt: EXPLAIN_COGNITION_RUNTIME and the introspection
agent read the live pipeline and may describe it freely.
"""
import pytest

from eli.cognition.output_governor import (
    claims_unverified_self_status,
    drop_unverified_self_status,
)

_BAD = ("You're not getting data dumps because I didn't have a chance to activate "
        "the guard - and honestly, I'm still figuring out why it's not triggering "
        "when you're clearly trying to push me. But let's cut through the noise: "
        "if you're tired of the dump, just tell me what you need.")


def test_the_observed_confabulation_is_detected():
    assert claims_unverified_self_status(_BAD)


def test_invented_mechanism_talk_is_dropped_but_the_offer_survives():
    out = drop_unverified_self_status(_BAD, is_grounded=False)
    assert "activate the guard" not in out
    assert "still figuring out why" not in out
    assert "tell me what you need" in out, "it removed the genuine part too"


def test_a_grounded_turn_may_describe_the_pipeline():
    assert drop_unverified_self_status(_BAD, is_grounded=True) == _BAD


@pytest.mark.parametrize("text", [
    "My long question guard didn't fire on that one.",
    "The router never kicked in for that phrasing.",
    "I didn't activate the filter in time.",
])
def test_variants_are_caught(text):
    assert claims_unverified_self_status(text), text


@pytest.mark.parametrize("keep", [
    "I can run a runtime audit if you want the real numbers.",
    "Your firewall rule did not trigger because the port was wrong.",
    "The smoke alarm didn't go off, which is worrying.",
])
def test_talk_that_is_not_about_elis_internals_survives(keep):
    assert drop_unverified_self_status(keep, is_grounded=False) == keep


def test_it_never_empties_a_reply():
    only = "My guard didn't fire."
    assert drop_unverified_self_status(only, is_grounded=False) == only
