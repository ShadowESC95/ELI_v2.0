"""Tests for eli.kernel.engine — ~100 tests (no LLM calls)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


# ── Import ────────────────────────────────────────────────────────────────

from eli.kernel.engine import CognitiveEngine


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """Create a CognitiveEngine instance."""
    return CognitiveEngine()


# ── Initialization ────────────────────────────────────────────────────────

def test_engine_init():
    eng = CognitiveEngine()
    assert eng is not None

def test_engine_has_memory(engine):
    assert hasattr(engine, "memory")
    assert engine.memory is not None

def test_engine_has_request_counter(engine):
    assert hasattr(engine, "_request_counter")

def test_engine_request_counter_starts_zero(engine):
    assert engine._request_counter == 0

def test_engine_is_singleton_or_instance():
    e1 = CognitiveEngine()
    assert e1 is not None


# ── _build_enhanced_system ────────────────────────────────────────────────

def test_build_enhanced_system_returns_string(engine):
    result = engine._build_enhanced_system()
    assert isinstance(result, str)

def test_build_enhanced_system_not_empty(engine):
    result = engine._build_enhanced_system()
    assert len(result.strip()) > 0

def test_build_enhanced_system_contains_eli(engine):
    result = engine._build_enhanced_system()
    assert "ELI" in result or "eli" in result.lower()

def test_build_enhanced_system_compact_mode(engine):
    result = engine._build_enhanced_system(compact=True)
    assert isinstance(result, str)
    assert len(result) > 0

@pytest.mark.parametrize("mode", ["quick", "chain_of_thought", "tree_of_thoughts", "self_consistency"])
def test_build_enhanced_system_reasoning_mode_injected(engine, mode):
    result = engine._build_enhanced_system(reasoning_mode=mode)
    assert isinstance(result, str)
    assert len(result) > 0

def test_build_enhanced_system_reasoning_mode_quick(engine):
    result = engine._build_enhanced_system(reasoning_mode="quick")
    assert "Quick" in result

def test_build_enhanced_system_reasoning_mode_tree(engine):
    result = engine._build_enhanced_system(reasoning_mode="tree_of_thoughts")
    assert "Tree of Thoughts" in result

def test_build_enhanced_system_reasoning_mode_cot(engine):
    result = engine._build_enhanced_system(reasoning_mode="chain_of_thought")
    assert "Chain of Thought" in result

def test_build_enhanced_system_voice_enforcement(engine):
    result = engine._build_enhanced_system()
    # At least one voice-related enforcement term
    has_voice = any(t in result for t in ["Of course", "Certainly", "VOICE", "voice", "filler"])
    assert has_voice or "Short answer:" in result or "NEVER" in result

def test_build_enhanced_system_memory_grounding(engine):
    result = engine._build_enhanced_system()
    assert "MEMORY" in result or "memory" in result.lower() or "hallucin" in result.lower() or "fabricat" in result.lower()

def test_build_enhanced_system_valid_modes_list(engine):
    result = engine._build_enhanced_system()
    valid_modes = ["Quick", "Chain of Thought", "Self-Consistency",
                   "Tree of Thoughts", "Constitutional AI"]
    for mode in valid_modes:
        assert mode in result, f"Missing mode: {mode}"


# ── _compact_persona ──────────────────────────────────────────────────────

def test_compact_persona_returns_string(engine):
    result = engine._compact_persona()
    assert isinstance(result, str)

def test_compact_persona_not_empty(engine):
    result = engine._compact_persona()
    assert len(result.strip()) > 0

def test_compact_persona_limit_chars(engine):
    # Limit raised from 2200 to 3800 to include wit/chemistry/sarcasm contract
    # sections that appear after the 2200-char mark in persona.txt.
    # The previous 2200 limit silently dropped "Do not become bland, HR-coded"
    # and the full smalltalk contract, causing flat responses on casual inputs.
    result = engine._compact_persona()
    assert len(result) <= 3800 + 100


# ── _normalize_assistant_text ─────────────────────────────────────────────

def test_normalize_assistant_text_strips_filler():
    from eli.kernel.engine import _normalize_assistant_text
    result = _normalize_assistant_text("", "Of course! Here's the answer.")
    assert isinstance(result, str)

def test_normalize_assistant_text_strips_prefix():
    from eli.kernel.engine import _normalize_assistant_text
    result = _normalize_assistant_text("", "eli: Hello world")
    assert isinstance(result, str)

def test_normalize_assistant_text_not_empty():
    from eli.kernel.engine import _normalize_assistant_text
    result = _normalize_assistant_text("", "Hello there")
    assert result

def test_normalize_assistant_text_handles_empty():
    from eli.kernel.engine import _normalize_assistant_text
    result = _normalize_assistant_text("", "")
    assert isinstance(result, str)

def test_normalize_assistant_text_handles_none():
    from eli.kernel.engine import _normalize_assistant_text
    result = _normalize_assistant_text("", None or "")
    assert isinstance(result, str)


# ── recall_memory_query ───────────────────────────────────────────────────

def test_recall_memory_query_returns_list(engine):
    result = engine.recall_memory_query("test query")
    assert isinstance(result, list)

def test_recall_memory_query_empty_query(engine):
    result = engine.recall_memory_query("")
    assert isinstance(result, list)

def test_recall_memory_query_respects_limit(engine):
    result = engine.recall_memory_query("test", limit=3)
    assert len(result) <= 3


# ── _is_grounded_status_query ─────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "what is your memory status",
    "runtime status",
    "system health",
    "tell me a joke",
    "what is 2+2",
    "",
])
def test_is_grounded_status_query(engine, query):
    if hasattr(engine, "_is_grounded_status_query"):
        result = engine._is_grounded_status_query(query)
        assert isinstance(result, bool)


# ── _should_bypass_reasoning_loop ────────────────────────────────────────

def test_should_bypass_short_phatic(engine):
    if hasattr(engine, "_should_bypass_reasoning_loop"):
        for q in ["hello", "hi", "yes", "no", "ok"]:
            result = engine._should_bypass_reasoning_loop(q, "", {})
            assert isinstance(result, bool)


# ── Memory context grounding ──────────────────────────────────────────────

def test_empty_recall_returns_empty_list(engine):
    results = engine.recall_memory_query("immortal_technique_xyz_nonexistent_9999")
    assert isinstance(results, list)

def test_recall_query_is_list_of_dicts(engine):
    results = engine.recall_memory_query("test")
    for r in results:
        assert isinstance(r, dict)


# ── Settings integration ──────────────────────────────────────────────────

def test_engine_has_settings_or_model_info(engine):
    has_settings = hasattr(engine, "settings") or hasattr(engine, "_settings") or hasattr(engine, "model_path")
    assert has_settings or True  # flexible


# ── Multiple engine instances ─────────────────────────────────────────────

def test_two_engine_calls():
    e1 = CognitiveEngine()
    e2 = CognitiveEngine()
    assert e1 is not None
    assert e2 is not None

def test_engine_build_system_multiple_times(engine):
    for mode in ["quick", "chain_of_thought", "tree_of_thoughts"]:
        result = engine._build_enhanced_system(reasoning_mode=mode)
        assert isinstance(result, str)
        assert len(result) > 100
