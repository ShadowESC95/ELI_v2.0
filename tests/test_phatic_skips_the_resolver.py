"""Locks on a greeting not paying for an intent-classification generation.

From a live 2.2.3 session on a 20.71GB model with 9 GPU layers:

    user> hey buddy, you better now?
    [GGUF][TIMING] prompt_tokens=1162  nonstream_call_total=45.898s
    llm_intent: grammar-constrained decode over manifest actions
    [COGNITIVE][TIMING] route=46.884s

Forty-six seconds of inference to conclude "CHAT". The deterministic router
answers the same question in 0.002s when a rule matches, and a phatic fast-path
already existed to skip the resolver entirely — it just did not recognise the
utterance. Two gaps:

  * the casual patterns matched "how'S the x" but not "how IS the x", although
    the normalisation step above them accepts both;
  * "you ok" was in the phrase set while "are you ok" and "you better now" were
    not, so the natural forms each cost a full generation.

The risk in widening this is swallowing a real request, so the state check is
anchored end to end as pronoun + state adjective + optional temporal tail. There
is no verb-plus-object slot for a command to hide in, and the existing technical
-subject guard ("how's the GPU" is a real question, "how's the head" is a hello)
is extended to the same forms rather than bypassed.
"""
import pytest

from eli.kernel.engine import _is_brief_phatic_prompt as phatic


# ── the utterances that were paying 46 seconds ─────────────────────────────
@pytest.mark.parametrize("text", [
    "hey buddy, you better now?",
    "are you ok?",
    "you better now?",
    "you alright now?",
    "r you good?",
    "hey buddy, how is the head?",
    "how is the head",
    "are you back to normal",
    "you any better?",
    "you any better",
    "you sorted yet?",
    "hey bud. good morning",
    "hey bud, good morning",
])
def test_conversational_check_ins_skip_the_resolver(text):
    assert phatic(text)


def test_the_forms_that_already_worked_still_do():
    for text in ("hey, what's up?", "hi", "how are you", "good morning", "thanks"):
        assert phatic(text), text


# ── and the ones that must still reach the router ──────────────────────────
@pytest.mark.parametrize("text", [
    "fix the router bug in engine.py",
    "open spotify",
    "you should fix the parser",
    "are you able to read this file",
    "show me the test results",
    "what did you find",
    "remember that I prefer thorough answers",
])
def test_real_requests_are_not_swallowed(text):
    assert not phatic(text)


@pytest.mark.parametrize("subject", [
    "gpu", "cpu", "memory", "database", "disk", "network", "tests", "model", "index",
])
def test_technical_subjects_stay_substantive(subject):
    """"How's the head" is a hello; "how's the GPU" is a real question that must
    keep its evidence gathering. The guard has to cover BOTH phrasings."""
    assert not phatic(f"how's the {subject}")
    assert not phatic(f"how is the {subject}")


def test_the_state_check_cannot_carry_an_object():
    """Anchored end-to-end: anything after the state word other than a temporal
    tail means it is not a bare check-in."""
    assert not phatic("you good to open the file")
    assert not phatic("are you ok with deleting that")
    assert not phatic("you better fix the parser")


# ── the fast-path has to actually be reachable ─────────────────────────────
def test_the_resolver_is_skipped_when_the_prompt_is_phatic():
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine)
    idx = src.index("phatic fast-path → CHAT (skipped LLM intent resolver)")
    window = src[max(0, idx - 600):idx]
    assert "_is_brief_phatic_prompt" in window, \
        "the fast-path no longer consults the detector"


def test_the_fast_path_can_be_disabled():
    """It is a routing short-circuit; an operator debugging routing needs it off."""
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine)
    assert "ELI_PHATIC_FASTPATH" in src


def test_phatic_query_class_skips_agent_bus_dispatch():
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine)
    assert '_qclass == "PHATIC"' in src
    assert "skipped_phatic" in src or "skipped (PHATIC" in src


def test_phatic_rapport_rule_demands_voice_not_telegraphic_echo():
    from eli.kernel.engine import _phatic_rapport_style_rule as rule

    text = rule()
    assert "2" in text and "4" in text  # 2–4 sentences
    assert "telegraphic" in text.lower() or "parrot" in text.lower()
    assert "functioning as intended" in text


def test_phatic_generation_budget_allows_personality():
    from eli.kernel.engine import _phatic_generation_budget

    assert _phatic_generation_budget() >= 128


def test_stream_chat_uses_brief_phatic_detector_not_exact_match_set():
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine.CognitiveEngine._stream_chat)
    assert "_is_brief_phatic_prompt" in src
    assert "_phatic_stream = _phatic_low in {" not in src
