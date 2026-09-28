"""A heavily-retrieved turn (real memory found, big SITUATION BRIEF + CONVERSATION
HISTORY) could get its system prompt truncated to fit the model's context window —
and the truncation was a blind head/tail character slice, on the wrong assumption
(stated in its own old comment) that retrieved evidence sits at the tail. It doesn't:
_build_enhanced_system() puts it in the middle, between the persona head and the
closing RESPONSE DISCIPLINE boilerplate. On a big enough brief/history, the slice
could land past the evidence block on both ends and drop it entirely — the model then
truthfully (from what it was shown) denies having any relevant memory, even though
retrieval genuinely found some (11 in window, 36 turns, 4575 chars assembled, in the
incident that surfaced this).

Fix: keep the evidence block whole first; only shrink the persona/rules head and the
closing-rules tail around it, and only eat into the evidence itself as a last resort.
Wired into both _get_chat_response truncation sites (broker path and the no-broker
direct-GGUF path), which is the sole generation chokepoint for every non-quick
reasoning mode (chain_of_thought, tree_of_thoughts, constitutional_ai,
self_consistency) — quick mode uses a separate streaming path that was already
evidence-aware.
"""
from __future__ import annotations

from eli.kernel.engine import _truncate_system_prompt_preserving_evidence


def _make_enhanced_system(pre_brief_chars, brief_chars, evidence_chars, tail_chars):
    """Shaped like the real _build_enhanced_system() output: persona/rules head, then
    SITUATION BRIEF, then CONVERSATION HISTORY (the actual retrieved evidence), then
    closing RESPONSE DISCIPLINE boilerplate.
    """
    return (
        ("P" * pre_brief_chars)
        + "--- SITUATION BRIEF (synthesised from agents + memory) ---\n"
        + ("B" * brief_chars)
        + "\n--- END BRIEF ---\n\n"
        + "--- CONVERSATION HISTORY (use this to answer questions about past exchanges) ---\n"
        + "REAL_RETRIEVED_MEMORY_MARKER_" + ("M" * evidence_chars)
        + "\n--- END HISTORY ---\n\n"
        + ("T" * tail_chars)
    )


def test_truncation_never_drops_the_evidence_block_when_it_fits_the_budget():
    """The exact failure shape from the DeepSeek-R1 CoT log: a large SITUATION BRIEF
    (13080 chars) pushes the head far enough that a blind 50/50 head+tail char slice
    can land past the CONVERSATION HISTORY block entirely, dropping all retrieved
    memory while keeping only persona/rules boilerplate.
    """
    full = _make_enhanced_system(
        pre_brief_chars=3000, brief_chars=13080, evidence_chars=4575, tail_chars=9000,
    )
    budget = 25866  # the exact _max_prompt_chars value from the real incident's log

    old_head = int(budget * 0.5)
    old_tail = budget - old_head
    old_result = full[:old_head] + full[-old_tail:]
    assert "REAL_RETRIEVED_MEMORY_MARKER_" not in old_result, (
        "sanity check: this fixture shape is the one that reproduced the bug"
    )

    new_result = _truncate_system_prompt_preserving_evidence(full, budget)
    assert len(new_result) <= budget
    assert "REAL_RETRIEVED_MEMORY_MARKER_" in new_result


def test_truncation_falls_back_to_head_tail_when_no_evidence_markers_present():
    text = "X" * 50000
    out = _truncate_system_prompt_preserving_evidence(text, 1000)
    assert len(out) <= 1100
    assert out.startswith("X" * 100)
    assert out.endswith("X" * 100)


def test_truncation_is_a_noop_under_budget():
    text = "short prompt, well under budget"
    assert _truncate_system_prompt_preserving_evidence(text, 10000) == text


def test_evidence_itself_is_trimmed_head_tail_as_a_last_resort_not_dropped():
    """When even the evidence block alone can't fit, it's shrunk from within
    (keeping its own head+tail) rather than vanishing outright.
    """
    full = _make_enhanced_system(
        pre_brief_chars=500, brief_chars=500, evidence_chars=40000, tail_chars=500,
    )
    budget = 5000
    out = _truncate_system_prompt_preserving_evidence(full, budget)
    # The "…[trimmed]…" markers add a little on top of the char budget — same slop
    # the original head+tail cut always had; this is a soft, approximate budget.
    assert len(out) <= budget + 200
    assert "REAL_RETRIEVED_MEMORY_MARKER_" in out


def test_every_non_quick_reasoning_mode_generates_through_the_evidence_preserving_path():
    import inspect
    from eli.kernel.engine import CognitiveEngine

    for method_name in (
        "_run_chain_of_thought", "_run_tree_of_thoughts",
        "_run_constitutional_ai", "_run_self_consistency",
    ):
        src = inspect.getsource(getattr(CognitiveEngine, method_name))
        assert "_get_chat_response(" in src, f"{method_name} bypasses _get_chat_response"


def test_both_get_chat_response_truncation_sites_use_the_evidence_preserving_helper():
    import inspect
    from eli.kernel.engine import CognitiveEngine

    src = inspect.getsource(CognitiveEngine._get_chat_response)
    assert src.count("_truncate_system_prompt_preserving_evidence(") == 2, (
        "both the broker path and the no-broker direct-GGUF path must use the fix"
    )
