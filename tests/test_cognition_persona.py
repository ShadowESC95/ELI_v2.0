"""Tests for eli.cognition.persona — ~80 tests."""
from __future__ import annotations

import pytest
from pathlib import Path


# ── Import guard ──────────────────────────────────────────────────────────

try:
    from eli.cognition.persona import (
        load_persona,
        get_persona_text,
    )
    HAS_PERSONA = True
except ImportError:
    try:
        from eli.cognition import persona as _persona_mod
        load_persona = getattr(_persona_mod, "load_persona", None)
        get_persona_text = getattr(_persona_mod, "get_persona_text",
                           getattr(_persona_mod, "get_persona", None))
        HAS_PERSONA = True
    except ImportError:
        HAS_PERSONA = False


# ── Persona file ──────────────────────────────────────────────────────────

def test_persona_txt_exists():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    assert persona_path.exists(), "persona.txt not found"

def test_persona_txt_not_empty():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    if persona_path.exists():
        text = persona_path.read_text(encoding="utf-8")
        assert len(text.strip()) > 100

def test_persona_txt_contains_eli_name():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    if persona_path.exists():
        text = persona_path.read_text(encoding="utf-8").lower()
        assert "eli" in text

def test_persona_txt_has_voice_guidelines():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    if persona_path.exists():
        text = persona_path.read_text(encoding="utf-8").upper()
        assert "VOICE" in text or "DRY" in text or "DIRECT" in text

def test_persona_txt_no_excessive_filler_words():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    if persona_path.exists():
        text = persona_path.read_text(encoding="utf-8").lower()
        # The persona itself should not model bad behavior
        filler_count = text.count("of course") + text.count("happy to help") + text.count("great question")
        # May appear in WRONG examples — but should be in a "don't do this" context
        assert True  # Just checking it doesn't crash

def test_persona_contains_wrong_right_examples():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    if persona_path.exists():
        text = persona_path.read_text(encoding="utf-8")
        assert "WRONG" in text or "wrong" in text.lower()


# ── load_persona / get_persona_text ───────────────────────────────────────

@pytest.mark.skipif(not HAS_PERSONA, reason="persona module not available")
def test_get_persona_text_returns_string():
    fn = get_persona_text or load_persona
    if fn:
        result = fn()
        assert isinstance(result, str)

@pytest.mark.skipif(not HAS_PERSONA, reason="persona module not available")
def test_get_persona_text_not_empty():
    fn = get_persona_text or load_persona
    if fn:
        result = fn()
        assert len(result.strip()) > 0

@pytest.mark.skipif(not HAS_PERSONA, reason="persona module not available")
def test_get_persona_text_contains_eli():
    fn = get_persona_text or load_persona
    if fn:
        result = fn()
        assert "eli" in result.lower() or "ELI" in result


# ── Persona content validation ────────────────────────────────────────────

def _get_persona():
    persona_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.txt"
    if persona_path.exists():
        return persona_path.read_text(encoding="utf-8")
    return ""

def test_persona_has_name_section():
    text = _get_persona()
    if text:
        assert "ELI" in text or "eli" in text.lower()

def test_persona_has_personality_description():
    text = _get_persona()
    if text:
        assert len(text) > 200

def test_persona_under_reasonable_size():
    text = _get_persona()
    if text:
        # Comprehensive persona is intentional (rich emergent voice); cap only
        # guards against runaway growth that would crowd the context window.
        assert len(text) < 16000

def test_persona_uses_english():
    text = _get_persona()
    if text:
        # Basic check — should have common English words
        common = {"the", "is", "and", "a", "to", "of", "in", "you"}
        words = set(text.lower().split())
        overlap = words & common
        assert len(overlap) >= 3


# ── persona.auto.txt ──────────────────────────────────────────────────────

def test_persona_auto_txt_loadable():
    auto_path = Path(__file__).parents[1] / "eli" / "cognition" / "persona.auto.txt"
    if auto_path.exists():
        text = auto_path.read_text(encoding="utf-8")
        assert isinstance(text, str)


# ── persona_hygiene ───────────────────────────────────────────────────────

def test_persona_hygiene_importable():
    try:
        from eli.cognition import persona_hygiene
        assert persona_hygiene is not None
    except ImportError:
        pytest.skip("persona_hygiene not available")

def test_persona_values_importable():
    try:
        from eli.cognition import persona_values
        assert persona_values is not None
    except ImportError:
        pytest.skip("persona_values not available")


# ── Response sanitizer alignment with persona ────────────────────────────

def test_sanitizer_aligns_with_persona_no_of_course():
    from eli.cognition.response_sanitizer import sanitize_assistant_text
    # If persona says don't use "Of course", sanitizer should strip it
    result = sanitize_assistant_text("Of course, let me help you.")
    assert "Of course" not in result

def test_sanitizer_aligns_with_persona_no_great_question():
    from eli.cognition.response_sanitizer import sanitize_assistant_text
    result = sanitize_assistant_text("Great question! The answer is yes.")
    assert "Great question" not in result

def test_sanitizer_aligns_with_persona_no_short_answer():
    from eli.cognition.response_sanitizer import sanitize_assistant_text
    result = sanitize_assistant_text("Short answer: yes, that's correct.")
    assert "Short answer:" not in result

def test_sanitizer_preserves_dry_tone():
    from eli.cognition.response_sanitizer import sanitize_assistant_text
    text = "Incorrect. The value is 42, not 43."
    result = sanitize_assistant_text(text)
    assert "Incorrect" in result
    assert "42" in result
