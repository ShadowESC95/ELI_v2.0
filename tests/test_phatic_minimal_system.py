"""Phatic greetings must not ship the full ~11k persona system on CPU."""
from __future__ import annotations

from eli.kernel.engine import CognitiveEngine, _load_persona_text


def test_phatic_minimal_system_is_small():
    ce = CognitiveEngine.__new__(CognitiveEngine)
    full_persona_len = len(_load_persona_text())
    sys_prompt = ce._build_phatic_minimal_system(
        "hi eli, how are you?",
        situation_brief="USER (verified name): Jess",
    )
    assert len(sys_prompt) < 2500, f"phatic system too large: {len(sys_prompt)} chars"
    assert len(sys_prompt) < full_persona_len // 2


def test_build_enhanced_system_routes_phatic_to_minimal():
    ce = CognitiveEngine.__new__(CognitiveEngine)
    enhanced = ce._build_enhanced_system(
        memory_context="X" * 5000,
        compact=False,
        user_input="hello eli",
        situation_brief="brief",
    )
    assert len(enhanced) < 2500
    assert "5000" not in enhanced  # memory_context not injected for phatic
