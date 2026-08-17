"""A correction repair must be given the answer it is repairing.

From the same live 2.2.4 session. The user asked:

    what are you talking about, now?

and got back:

    I'm sorry for the confusion. Could you please clarify what you're asking about?

Their next message was "what the fuck are you talking about?".

The turn was classified CORRECTION, which takes a shortcut around the pipeline —
no persona, no memory, no stages. The log shows what reached the model:

    [PIPELINE] Stage 1: Intent -> CHAT (conf=0.95 via=identity.chat_classified)
    [GGUF][TIMING] prompt_tokens=111 prompt_chars=454 max_tokens=160

111 tokens. The call passed the user's own words and a system instruction, and
nothing else — so a question that is ONLY answerable by reference to what ELI
had just said was handed to a model that could not see it. The single reply it
can produce from that input is a request for clarification, which is what it
produced.

Two fixes, both mechanical:

  * include the exchange being corrected in the prompt. The scope guard ("do not
    introduce diagnostics, runtime, files…") is still correct — a repair should
    not wander — but scope is not amnesia;
  * the budget comes from the operator's own mode preset instead of a fixed 160.
    -1 ("no cap") passes through untouched, because several presets ship as -1
    and a `<= 0` fallback would silently convert unlimited into a number.
"""
from __future__ import annotations

import inspect

import pytest

from eli.kernel import engine


@pytest.fixture(scope="module")
def source():
    return inspect.getsource(engine.CognitiveEngine._correction_repair)


# ── it must see the exchange ───────────────────────────────────────────────
def test_the_repair_prompt_includes_the_prior_exchange(source):
    assert "get_recent_conversation" in source, \
        "the correction path cannot see the answer it is repairing"
    assert "The exchange you are correcting" in source


def test_the_prior_turn_is_prepended_to_the_system_prompt(source):
    code = "\n".join(l for l in source.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_corr_system = _prior + _corr_system" in code


def test_it_is_told_not_to_bounce_the_question_back(source):
    """The observed failure was an infinite clarification loop."""
    assert "do not ask them to clarify a question about your own previous answer" \
        in source.lower()


def test_the_scope_guard_survives(source):
    """A repair still must not wander into diagnostics — that part was right."""
    low = source.lower()
    assert "do not introduce memory, runtime, files, diagnostics" in low


# ── the budget must follow the operator's settings ─────────────────────────
def test_no_hardcoded_output_cap_remains(source):
    assert "max_tokens=160" not in source, \
        "the fixed 160-token cap is back on the correction path"
    assert "max_tokens=_corr_max" in source


def test_the_budget_is_read_from_the_mode_preset(source):
    assert "_mode_profile" in source


def test_unlimited_is_not_converted_into_a_number(source):
    """-1 means 'fill the context'. A `<= 0` fallback would cap it."""
    code = "\n".join(l for l in source.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_corr_max <= 0" not in code, \
        "a <= 0 fallback turns the operator's unlimited setting into a cap"
    assert "_corr_max == 0" in code


def test_quick_mode_budget_beats_the_old_fixed_cap():
    """Sanity: the preset path yields a real answer budget, not 160."""
    eng = engine.CognitiveEngine(auto_init_gguf=False)
    try:
        profile = eng._mode_profile("quick") or {}
        mt = profile.get("max_tokens")
        assert mt is not None
        assert mt == -1 or mt > 160
    finally:
        try:
            eng.shutdown()
        except Exception:
            pass
