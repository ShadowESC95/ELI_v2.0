"""Behaviour lock: the two-stage CoT must not waste a reasoning model's budget.

On Qwen3.6-35B (a reasoning model) each CoT pass opened its own <think>…</think>
block. When it hit max_tokens before closing the tag, _strip_think_text dropped
the whole output to empty, stage 2 received an empty scratchpad and re-thought
from scratch — a real session burned 170-230s per pass, then a full retry.

The fix wraps both passes in force_no_think(): the closed-think prefill suppresses
the redundant wrapper, so stage 1 writes its numbered-step reasoning directly (the
prose stage 2 is designed to consume) and stage 2 synthesises without re-thinking.
The large-budget MAIN answer call (outside CoT) is unaffected and still thinks.
"""

import eli.cognition.gguf_inference as ggi
from eli.kernel import engine as eng


def test_force_no_think_forces_closed_think_on_a_reasoning_model(monkeypatch):
    monkeypatch.setattr(ggi, "_is_thinking_model", lambda: True)
    with ggi.force_no_think():
        assert ggi._no_think_prefill(structured=False, max_tokens=4096) == "<think>\n\n</think>\n\n"
    # Outside the scope, a large-budget chat call still thinks (no prefill).
    monkeypatch.delenv("ELI_MODEL_THINK", raising=False)
    monkeypatch.setenv("ELI_CURRENT_REASONING_MODE", "chain_of_thought")
    assert ggi._no_think_prefill(structured=False, max_tokens=4096) == ""


def test_force_no_think_applies_prefill_even_on_unknown_reasoning_models(monkeypatch):
    monkeypatch.setattr(ggi, "_is_thinking_model", lambda: False)
    with ggi.force_no_think():
        assert ggi._no_think_prefill(structured=False, max_tokens=512) == "<think>\n\n</think>\n\n"


class _StubEngine:
    """Minimal stand-in that records the force-no-think state of each CoT pass."""
    _run_chain_of_thought = eng.CognitiveEngine._run_chain_of_thought

    def __init__(self):
        self.pass_states = []

    def _mode_profile(self, mode):
        return {"max_tokens": 1200, "temperature": 0.5}

    def _get_chat_response(self, prompt, working_context, **kwargs):
        self.pass_states.append(ggi._force_no_think_active())
        return "step reasoning" if "scratchpad" in prompt.lower() else "the final answer"


def test_both_cot_passes_run_inside_force_no_think():
    stub = _StubEngine()
    out = _StubEngine._run_chain_of_thought(stub, "explain how X works", "", {}, "")
    assert stub.pass_states == [True, True], (
        f"a CoT pass ran without force_no_think: {stub.pass_states}"
    )
    assert out == "the final answer"


def test_cot_final_answer_is_not_empty_when_model_would_have_thought():
    """Regression: the truncated-<think>-to-empty path no longer swallows the answer."""
    stub = _StubEngine()
    out = _StubEngine._run_chain_of_thought(stub, "why is the sky blue", "", {}, "")
    assert out.strip(), "CoT produced an empty final answer"


# ── every pass of a turn shares one system prompt ────────────────────────────
#
# Built per call, the second pass's system prompt came out different (the persona was cut to fit
# that pass's longer message), so a 35B model read all 7k tokens again: 62 s per pass. Shared, the
# model state at its end is kept (gguf_inference) and the second pass reads only its own message.

import pytest
from eli.kernel import request_context as rc


class _Broker:
    gguf_ready = True

    def __init__(self):
        self.systems, self.prompts = [], []

    def infer(self, prompt, system=None, **kw):
        self.systems.append(system)
        self.prompts.append(prompt)
        return "an answer"


@pytest.fixture()
def passes(monkeypatch):
    broker = _Broker()
    monkeypatch.setattr(eng, "_get_inference_broker", lambda: broker)
    me = eng.CognitiveEngine.__new__(eng.CognitiveEngine)
    me._gguf_available = True
    me.built = 0

    def build(memory_context="", compact=False, user_input="", reasoning_mode=None, situation_brief=""):
        me.built += 1
        return "PERSONA AND RULES. " + memory_context + " BRIEF: " + situation_brief + f" built from {len(user_input)}"
    for name, fn in {"_build_enhanced_system": build, "_prepend_recent_exchange": lambda p: p,
                     "_current_provider": lambda: "gguf", "_generation_settings": lambda: {"max_tokens": 512, "temperature": 0.5},
                     "_runtime_n_ctx": lambda: 16128, "_use_compact_system": lambda *a, **k: False,
                     "_maybe_apply_mode_runtime_adaptation": lambda *a, **k: None,
                     "_note_memory_trim": lambda *a, **k: None}.items():
        monkeypatch.setattr(me, name, fn, raising=False)
    token = rc.turn_facts_var.set({"user_input": "doing well, good redemption bud"})
    yield me, broker
    rc.turn_facts_var.reset(token)


def test_both_passes_of_a_turn_are_given_the_same_system_prompt(passes):
    me, broker = passes
    me._get_chat_response("Think through the following request step by step. REQUEST: doing well",
                          "the evidence", reasoning_mode="chain_of_thought", situation_brief="the brief")
    me._get_chat_response("Using your internal reasoning below, write ONLY the final answer. " + "step. " * 300,
                          "the evidence", reasoning_mode="chain_of_thought", situation_brief="the brief")
    assert me.built == 1 and broker.systems[0] == broker.systems[1]
    me._get_chat_response("a pass over other evidence", "other evidence", reasoning_mode="chain_of_thought",
                          situation_brief="the brief")
    assert me.built == 2 and broker.systems[2] != broker.systems[0]


def test_outside_a_turn_each_call_builds_its_own(passes):
    me, broker = passes
    rc.turn_facts_var.set(None)
    me._get_chat_response("one", "the evidence", reasoning_mode="chain_of_thought")
    me._get_chat_response("two", "the evidence", reasoning_mode="chain_of_thought")
    assert me.built == 2


def test_a_mode_of_several_passes_leaves_room_for_the_longest_message_from_the_first(passes, monkeypatch):
    me, broker = passes
    monkeypatch.setenv("ELI_SYNTH_MAX_PROMPT_CHARS", "8000")
    evidence = "== SITUATION BRIEF ==\n" + "a fact about the week. " * 1000
    me._get_chat_response("short first pass", evidence, reasoning_mode="chain_of_thought", situation_brief="b")
    me._get_chat_response("long second pass " + "reasoning. " * 600, evidence, reasoning_mode="chain_of_thought",
                          situation_brief="b")
    # three quarters of the cap, give or take the trimming's own "[...trimmed...]" markers
    assert broker.systems[0] == broker.systems[1] and len(broker.systems[0]) <= 6000 + 100
    assert len(broker.systems[1]) + len(broker.prompts[1]) <= 8000


def test_the_tone_and_the_emotion_timeline_take_the_users_words_not_elis_instructions(passes, monkeypatch):
    from eli.cognition import emotion_timeline, tone_adaptor
    heard, recorded = [], []
    monkeypatch.setattr(tone_adaptor, "enabled", lambda: True)
    monkeypatch.setattr(tone_adaptor, "note_user_text", heard.append)
    monkeypatch.setattr(emotion_timeline, "record", lambda *a, **k: recorded.append(k.get("user_text")) or True)
    me, _ = passes
    assert eng._users_own_words("...\n\nYou: Think through the following request step by step.") == \
        "doing well, good redemption bud"
    rc.turn_facts_var.set(None)
    assert eng._users_own_words("earlier talk\n\nYou: hello there") == "hello there"
