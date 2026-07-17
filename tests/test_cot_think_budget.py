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


def test_force_no_think_is_a_noop_for_non_reasoning_models(monkeypatch):
    monkeypatch.setattr(ggi, "_is_thinking_model", lambda: False)
    with ggi.force_no_think():
        assert ggi._no_think_prefill(structured=False, max_tokens=4096) == ""


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
