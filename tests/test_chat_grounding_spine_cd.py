"""Phase C/D: fail-closed gate and unified retrieval."""
from __future__ import annotations

from eli.cognition.chat_grounding_gate import (
    count_verified_memory_lines,
    evaluate_chat_grounding_gate,
    is_phatic_turn,
    requires_user_fact_grounding,
)
from eli.memory.unified_retrieval import split_verified_evidence_packet


def test_phatic_skips_fail_closed():
    assert is_phatic_turn("hey buddy")
    assert evaluate_chat_grounding_gate("hey buddy", query_class="PHATIC") is None


def test_personal_empty_memory_fails_closed():
    out = evaluate_chat_grounding_gate(
        "what do you know about me?",
        query_class="PERSONAL",
        memory_context="",
        bus_result=None,
    )
    assert out is not None
    assert "verified memory" in out.lower()


def test_personal_with_verified_lines_allows_generation():
    ctx = (
        "Verified stored memories (1 found — ground user-specific claims ONLY from these rows):\n"
        "  - [memory_id=1 status=verified prov=user_verbatim] User name is Jay"
    )
    assert count_verified_memory_lines(ctx) == 1
    out = evaluate_chat_grounding_gate(
        "what do you know about me?",
        query_class="PERSONAL",
        memory_context=ctx,
    )
    assert out is None


def test_requires_user_fact_grounding_personal():
    assert requires_user_fact_grounding("who am i", "PERSONAL")
    assert not requires_user_fact_grounding("what is python", "FACTUAL")


def test_split_verified_evidence_packet():
    ctx = (
        "Agents: memory\n\n"
        "Verified stored memories (1 found — ground user-specific claims ONLY from these rows):\n"
        "  - [memory_id=2 status=verified] dark mode\n\n"
        "[LOW GROUNDING this turn]"
    )
    verified, remainder = split_verified_evidence_packet(ctx)
    assert "Verified stored memories" in verified
    assert "memory_id=2" in verified
    assert "Verified stored memories" not in remainder
    assert "LOW GROUNDING" in remainder
