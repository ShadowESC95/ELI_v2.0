import pytest

from eli.cognition.reasoning_modes import (
    apply_final_reasoning_contract,
    canonical_mode,
    gui_prompt_prefix_for_mode,
    is_private_reasoning_mode,
    mode_display,
    system_instruction_for_mode,
)
from eli.cognition.response_sanitizer import sanitize_assistant_text
from eli.cognition.output_governor import govern_output, normalize_assistant_text

PRIVATE_MODES = ["chain_of_thought", "self_consistency", "tree_of_thoughts", "constitutional_ai"]

@pytest.mark.parametrize("mode", PRIVATE_MODES)
def test_private_modes_have_hidden_final_only_contract(mode):
    instruction = system_instruction_for_mode(mode)
    assert "PRIVATE REASONING STRATEGY" in instruction
    assert "Never reveal" in instruction
    assert "Output only the final answer" in instruction
    assert "Show explicit step-by-step reasoning" not in instruction
    assert "Show your reasoning chain" not in instruction

@pytest.mark.parametrize("mode", PRIVATE_MODES)
def test_gui_prefix_does_not_request_visible_reasoning(mode):
    prefix = gui_prompt_prefix_for_mode(mode)
    assert "final answer only" in prefix.lower()
    assert "show your reasoning" not in prefix.lower()
    assert "show your reasoning chain" not in prefix.lower()
    assert "generate 3 independent" not in prefix.lower()

@pytest.mark.parametrize("alias, canonical, display", [
    ("CoT", "chain_of_thought", "Chain of Thought"),
    ("self consistency", "self_consistency", "Self-Consistency"),
    ("ToT", "tree_of_thoughts", "Tree of Thoughts"),
    ("constitutional ai", "constitutional_ai", "Constitutional AI"),
])
def test_reasoning_mode_aliases(alias, canonical, display):
    assert canonical_mode(alias) == canonical
    assert mode_display(alias) == display
    assert is_private_reasoning_mode(alias)

@pytest.mark.parametrize("raw", [
    "[REASONING MODE: Chain of Thought]\nThink step-by-step. Show your reasoning chain explicitly before giving the final answer.\nFinal answer: Patch engine.py.",
    "CHAIN OF THOUGHT:\n1. Hidden step\n2. Hidden step\n\nFinal answer: Patch engine.py.",
    "SELF-CONSISTENCY SAMPLES:\nSample 1: hidden\nSample 2: hidden\nAnswer: Patch engine.py.",
    "TREE OF THOUGHTS:\nBranch 1: hidden\nBranch 2: hidden\nResult: Patch engine.py.",
    "CONSTITUTIONAL CRITIQUE:\nThe draft fails X.\nFinal: Patch engine.py.",
])
def test_final_contract_strips_private_reasoning(raw):
    out = apply_final_reasoning_contract(raw)
    low = out.lower()
    assert "hidden" not in low
    assert "chain of thought" not in low
    assert "self-consistency" not in low
    assert "tree of thoughts" not in low
    assert "constitutional critique" not in low
    assert "patch engine.py" in low


def test_output_governor_and_sanitizer_apply_contract():
    raw = "CHAIN OF THOUGHT:\nsecret\nFinal answer: Visible final."
    assert govern_output(raw) == "Visible final."
    assert sanitize_assistant_text(raw) == "Visible final."
    assert normalize_assistant_text("question", raw) == "Visible final."
