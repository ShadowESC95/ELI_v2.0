"""Wiring lock: the anti-confabulation self-mechanism guard is in the system prompt.

A real session asked ELI "how were the improvements and recalibration function?"
and it invented an entire architecture — "Entropy Normalization, P(x)=Softmax(...),
Context Window Pruning, Confidence Thresholding, Verification Loop" — none of which
exist. This can't be unit-tested at the model level (behaviour), but the guard that
steers the model toward grounded-or-admit MUST be present in every synthesis prompt.
"""

from eli.kernel.engine import CognitiveEngine


def _system(**kw) -> str:
    return CognitiveEngine()._build_enhanced_system(**kw)


def test_self_mechanism_guard_present_in_default_prompt():
    text = _system()
    assert "NO INVENTED SELF-MECHANISM" in text


def test_guard_forbids_fabricated_algorithms():
    text = _system().lower()
    assert "fabricate" in text and "algorithm" in text
    # The exact failure mode is named so the steer is concrete, not abstract.
    assert "entropy normalization" in text


def test_guard_directs_to_honest_admission():
    text = _system()
    assert "I don't have that level of detail on my own runtime" in text


def test_guard_is_not_a_blanket_refusal():
    """It must still explain the architecture when evidence describes it."""
    text = _system()
    assert "when the evidence DOES describe your architecture, explain it fully" in text


def test_guard_present_across_reasoning_modes():
    # The confabulation was observed in chain_of_thought; the guard rides the shared
    # base_rules, so it must appear in every non-quick mode.
    for mode in ("chain_of_thought", "tree_of_thoughts", "self_consistency"):
        assert "NO INVENTED SELF-MECHANISM" in _system(reasoning_mode=mode), mode
