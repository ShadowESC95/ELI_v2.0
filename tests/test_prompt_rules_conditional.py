"""Conditional assembly of the system-prompt guards.

The guards each close a specific observed failure. Making them conditional is
only safe if two things hold, so both are pinned here:

  1. A guard that fires is byte-identical to the old unconditional text.
  2. Every failure that motivated a guard still triggers it — these are the
     regression tests for the original bugs, expressed as prompt content.

Plus the fail-safe: an unassessable turn gets the complete block.
"""
from __future__ import annotations

import pathlib

import pytest

from eli.kernel import prompt_rules as pr

ALL = pr.all_rules()


# ── invariants ───────────────────────────────────────────────────────────────
def test_core_is_always_present():
    for ui in ("hey", "how do you work", "", "elaborate", "no you didn't"):
        assert pr.CORE in pr.select_rules(ui), f"CORE dropped for {ui!r}"


@pytest.mark.parametrize("key", pr._ORDER)
def test_every_guard_is_in_the_full_block(key):
    assert pr._TEXT[key] in ALL


def test_selection_is_always_a_subset_of_the_full_block():
    """No selection may introduce text the unconditional block didn't have."""
    for ui, ctx, prof in [
        ("hey", "", ""), ("how do you work", "", ""),
        ("what do you know about me", "ELI: hi\n", "Name: X"),
        ("elaborate", "", "Recalled past topics: physics"),
    ]:
        out = pr.select_rules(ui, ctx, prof)
        remainder = out.replace(pr.CORE, "", 1)
        for chunk in [pr._TEXT[k] for k in pr._ORDER]:
            remainder = remainder.replace(chunk, "", 1)
        assert remainder == "", "select_rules emitted text not present in all_rules()"


def test_all_rules_is_byte_identical_to_the_previous_block():
    """The whole point: assembling everything reproduces the old prompt exactly."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "eli" / "kernel" / "engine.py").read_text(encoding="utf-8")
    assert "prompt_rules" in src, "the prompt builder no longer uses prompt_rules"
    # every guard constant must appear verbatim in the assembled block
    for key in pr._ORDER:
        assert pr._TEXT[key] in pr.all_rules()


# ── fail-safe ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ui", ["", "   ", "\n"])
def test_unassessable_turn_gets_everything(ui):
    assert pr.select_rules(ui) == ALL


def test_matcher_failure_falls_back_to_everything(monkeypatch):
    monkeypatch.setattr(pr, "_triggers", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert pr.select_rules("anything at all") == ALL


# ── the closed bugs, as triggers ─────────────────────────────────────────────
@pytest.mark.parametrize("ui", [
    "no you didn't, you made that up",
    "that's not true",
    "you're hallucinating",
    "you can't know that",
    "how would you know",
])
def test_pushback_gets_the_no_false_self_denial_guard(ui):
    """The disowned-recall bug: ELI denying its own memory when challenged."""
    assert pr.NO_FALSE_SELF_DENIAL in pr.select_rules(ui)


def test_recall_turns_get_the_self_denial_guard_even_without_pushback():
    assert pr.NO_FALSE_SELF_DENIAL in pr.select_rules("what do you remember about me")


@pytest.mark.parametrize("ui", [
    "what do you know about me",
    "what do you know about yourself",
    "tell me about my profile",
    "who are you",
])
def test_profile_questions_get_the_whose_profile_guard(ui):
    assert pr.WHOSE_PROFILE in pr.select_rules(ui)


def test_past_session_guard_only_when_those_fields_exist():
    without = pr.select_rules("what am I working on", profile_text="Name: X")
    withfields = pr.select_rules("what am I working on",
                                 profile_text="Recalled past topics: FRB dispersion")
    assert pr.PAST_SESSION_MEMORY not in without
    assert pr.PAST_SESSION_MEMORY in withfields


@pytest.mark.parametrize("ui", [
    "elaborate", "go deeper", "tell me more", "expand on that",
    "explain that", "dive deeper into this",
])
def test_deepen_requests_get_the_deliver_substance_guard(ui):
    assert pr.DELIVER_SUBSTANCE in pr.select_rules(ui)


def test_attribution_guard_when_eli_turns_are_in_history():
    ctx = "User: hi\nELI: your dog is Shadow\nUser: ok\n"
    assert pr.ATTRIBUTION in pr.select_rules("what did I say", ctx)
    assert pr.ATTRIBUTION not in pr.select_rules("what is 2+2", "")


def test_invented_preferences_guard_whenever_user_facts_are_in_play():
    assert pr.INVENTED_PREFERENCES in pr.select_rules("hey", "", "Name: X")
    assert pr.INVENTED_PREFERENCES in pr.select_rules("hey", "some memory", "")


# ── the point of the exercise ────────────────────────────────────────────────
def test_phatic_turn_is_substantially_cheaper():
    report = pr.selection_report("hey eli")
    # no_social_deflection is unconditional by design (it lives in the ordered
    # list only so the bullet order matches the original block).
    assert report["included"] == ["no_social_deflection"], \
        "a greeting should trigger no conditional guard"
    assert report["saved"] > 3000, f"expected a real saving, got {report['saved']}"
    assert report["chars"] < report["chars_full"] * 0.4


def test_report_accounts_for_every_guard():
    r = pr.selection_report("what do you know about me")
    assert set(r["included"]) | set(r["skipped"]) == set(pr._ORDER)

@pytest.mark.parametrize("ui", [
    "how does your confidence scoring actually work?",
    "how do you work internally",
    "what changed about your reasoning?",
    "explain your own architecture",
    "how do you remember things",
    "what happens under the hood when you answer",
    "how do you decide what to say",
])
def test_self_mechanism_questions_get_the_no_invented_mechanism_guard(ui):
    """Ported from v2: stops ELI inventing named algorithms about its own internals."""
    assert pr.NO_INVENTED_SELF_MECHANISM in pr.select_rules(ui)


def test_self_mechanism_guard_precedes_the_rule_that_references_it():
    """NO FALSE SELF-DENIAL opens 'The mirror of the rule above' — so the rule it
    mirrors must actually sit immediately above it."""
    block = pr.all_rules()
    i = block.index("- NO INVENTED SELF-MECHANISM:")
    j = block.index("- NO FALSE SELF-DENIAL:")
    assert i < j, "the mirrored rule must come first"
    between = block[block.index("\n", i) + 1:j].strip()
    assert between == "", f"another rule sits between them: {between[:60]!r}"


def test_casual_turn_does_not_pay_for_the_self_mechanism_guard():
    assert pr.NO_INVENTED_SELF_MECHANISM not in pr.select_rules("hey eli")
