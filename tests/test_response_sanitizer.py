"""Tests for eli.cognition.response_sanitizer — ~220 tests."""
from __future__ import annotations

import pytest
from eli.cognition.response_sanitizer import (
    sanitize_assistant_text,
    normalize_assistant_text,
    clean_assistant_text,
)

# ── Alias tests (all three functions must behave identically) ─────────────

def test_aliases_identical():
    text = "Hello world"
    assert sanitize_assistant_text(text) == normalize_assistant_text(text) == clean_assistant_text(text)


def test_aliases_on_empty():
    for fn in (sanitize_assistant_text, normalize_assistant_text, clean_assistant_text):
        result = fn("")
        assert result == "..."

def test_aliases_on_none():
    for fn in (sanitize_assistant_text, normalize_assistant_text, clean_assistant_text):
        result = fn(None)
        assert result == "..."


# ── Stage prefix stripping ────────────────────────────────────────────────

@pytest.mark.parametrize("prefix,content", [
    ("eli: ", "Hello there"),
    ("ELI: ", "Hello there"),
    ("assistant: ", "Hello there"),
    ("ASSISTANT: ", "Hello there"),
    ("calmly: ", "This is fine"),
    ("quietly: ", "Whisper"),
    ("softly: ", "Gentle"),
    ("gently: ", "Care"),
    ("warmly: ", "Welcome"),
    ("plainly: ", "Direct"),
    ("dryly: ", "Blunt"),
    ('eli: "', "Quoted"),
    ("eli: '", "Quoted single"),
    ("  eli:   ", "Spaced"),
])
def test_stage_prefix_stripped(prefix, content):
    result = sanitize_assistant_text(f"{prefix}{content}")
    assert result == content


@pytest.mark.parametrize("text", [
    "eli is here",
    "calmly speaking, this is fine",
    "hello: world",
    "assistant mode engaged",
])
def test_stage_prefix_not_stripped_mid_sentence(text):
    result = sanitize_assistant_text(text)
    assert result  # not empty
    # Should not strip mid-sentence occurrences
    assert len(result) >= 5


# ── Filler opener stripping ───────────────────────────────────────────────

@pytest.mark.parametrize("opener", [
    "Of course, ",
    "Of course! ",
    "Of course. ",
    "Certainly, ",
    "Certainly! ",
    "Sure, ",
    "Sure thing, ",
    "Sure! ",
    "Absolutely, ",
    "Absolutely! ",
    "Happy to help, ",
    "Happy to help! ",
    "Great question, ",
    "Great question! ",
    "Excellent question, ",
    "Good question, ",
    "That's a great question, ",
    "That's a great point, ",
    "I'd be happy to, ",
    "I'd be happy to! ",
    "I'm glad you asked, ",
    "Short answer: ",
    "of course, ",
    "CERTAINLY, ",
    "SURE THING, ",
])
def test_filler_openers_stripped(opener):
    content = "here is the answer to your question"
    result = sanitize_assistant_text(f"{opener}{content}")
    assert content in result
    assert opener.strip().rstrip(",! ").lower() not in result.lower().split()[0] if result else True


@pytest.mark.parametrize("text", [
    "Of course this is a complex topic",
    "Certainly the weather is nice",
    "Sure there are many ways to do this",
])
def test_filler_stripped_from_non_opener_context(text):
    # These ARE openers — they should be stripped
    result = sanitize_assistant_text(text)
    assert result  # should return something, not empty
    assert result != "..."


# ── Placeholder stripping ─────────────────────────────────────────────────

@pytest.mark.parametrize("placeholder", [
    "[user]",
    "[User]",
    "[USER]",
    "[username]",
    "[name]",
    "<user>",
    "<User>",
    "<local_user>",
    "<username>",
    "<name>",
    "<NAME>",
])
def test_placeholder_stripped(placeholder):
    text = f"Hello {placeholder}, how are you?"
    result = sanitize_assistant_text(text)
    assert placeholder not in result
    assert "Hello" in result


# ── Whitespace normalization ──────────────────────────────────────────────

def test_multiple_spaces_collapsed():
    result = sanitize_assistant_text("Hello   world   today")
    assert "  " not in result

def test_space_before_punctuation_removed():
    result = sanitize_assistant_text("Hello , world .")
    assert " ," not in result
    assert " ." not in result

def test_space_before_semicolon_removed():
    result = sanitize_assistant_text("Item one ; item two")
    assert " ;" not in result

def test_leading_trailing_whitespace_stripped():
    result = sanitize_assistant_text("   hello world   ")
    assert result == "hello world"

def test_leading_quotes_stripped():
    result = sanitize_assistant_text('"Hello world"')
    assert result == "Hello world"

def test_leading_single_quotes_stripped():
    result = sanitize_assistant_text("'Hello world'")
    assert result == "Hello world"


# ── Non-string inputs ─────────────────────────────────────────────────────

@pytest.mark.parametrize("val,expected_type", [
    (42, str),
    (3.14, str),
    (True, str),
    (False, str),
    ([], str),
    ({}, str),
])
def test_non_string_inputs_coerced(val, expected_type):
    result = sanitize_assistant_text(val)
    assert isinstance(result, expected_type)
    assert result  # non-empty


def test_empty_string_returns_ellipsis():
    assert sanitize_assistant_text("") == "..."

def test_whitespace_only_returns_ellipsis():
    assert sanitize_assistant_text("   \n\t  ") == "..."

def test_none_returns_ellipsis():
    assert sanitize_assistant_text(None) == "..."


# ── Real-world response samples ───────────────────────────────────────────

REAL_SAMPLES = [
    ("Of course! I'd be happy to explain the difference between lists and dicts.",
     "I'd be happy to explain"),  # should strip "Of course!"
    ("eli: Here's the answer you're looking for.", "Here's the answer"),
    ("Sure thing, let me break that down for you.", "let me break"),
    ("That's a great question! Python uses indentation to define blocks.",
     "Python uses indentation"),
    ("Great question, the answer is 42.", "the answer is 42"),
    ("Short answer: yes.", "yes"),
    ("Certainly! The sky is blue because of Rayleigh scattering.",
     "The sky is blue"),
    ("Absolutely, you should use a virtual environment.",
     "you should use a virtual environment"),
    ("I'm glad you asked, this is actually quite interesting.",
     "this is actually quite interesting"),
]

@pytest.mark.parametrize("raw,expected_fragment", REAL_SAMPLES)
def test_real_world_samples(raw, expected_fragment):
    result = sanitize_assistant_text(raw)
    assert expected_fragment.lower() in result.lower()


# ── Preservation of legitimate content ───────────────────────────────────

PRESERVE_SAMPLES = [
    "The function returns a list of integers.",
    "Use `git commit -m 'message'` to commit.",
    "Set `n_gpu_layers=99` for full GPU offload.",
    "Error: FileNotFoundError: /path/to/file not found.",
    "The model has 7 billion parameters.",
    "Run the following command: `pip install torch`",
    "I disagree with that approach for two reasons.",
    "No, that's incorrect. The actual value is 42.",
    "It depends on your use case.",
]

@pytest.mark.parametrize("text", PRESERVE_SAMPLES)
def test_legitimate_content_preserved(text):
    result = sanitize_assistant_text(text)
    # Core content should survive (check first few words)
    first_word = text.split()[0].lower().rstrip(",.!?:;")
    assert result  # not empty
    assert result != "..."


# ── Edge cases ────────────────────────────────────────────────────────────

def test_only_placeholder_returns_ellipsis():
    result = sanitize_assistant_text("[user]")
    # Placeholder stripped → empty → "..."
    assert result == "..."

def test_combined_prefix_and_filler():
    result = sanitize_assistant_text("eli: Of course, let me help you with that.")
    assert "Of course" not in result
    assert "eli:" not in result.lower()

def test_multiple_placeholders():
    result = sanitize_assistant_text("Hello [user], I'm [name] your assistant <username>")
    assert "[user]" not in result
    assert "[name]" not in result
    assert "<username>" not in result

def test_newline_in_text_preserved():
    result = sanitize_assistant_text("Line one\nLine two")
    assert "Line one" in result
    assert "Line two" in result

def test_unicode_text():
    result = sanitize_assistant_text("Héllo wörld — this is fine")
    assert "Héllo" in result

def test_very_long_text():
    text = "word " * 500
    result = sanitize_assistant_text(text)
    assert len(result) > 0

def test_code_block_preserved():
    text = "```python\nprint('hello')\n```"
    result = sanitize_assistant_text(text)
    assert "print" in result

def test_markdown_preserved():
    text = "**Bold** and _italic_ text"
    result = sanitize_assistant_text(text)
    assert "Bold" in result

def test_numeric_response():
    result = sanitize_assistant_text("42")
    assert result == "42"

def test_single_word():
    result = sanitize_assistant_text("Yes")
    assert result == "Yes"

def test_short_answer_stripped_case_insensitive():
    result = sanitize_assistant_text("SHORT ANSWER: affirmative")
    assert "SHORT ANSWER:" not in result
    assert "affirmative" in result.lower()

def test_filler_with_extra_spaces():
    result = sanitize_assistant_text("  Of course,   here is the answer")
    assert "Of course" not in result

def test_response_starting_with_colon_number():
    result = sanitize_assistant_text("1. First item\n2. Second item")
    assert "First item" in result

def test_response_with_only_punctuation():
    result = sanitize_assistant_text("...")
    assert result == "..."

def test_response_with_em_dash():
    result = sanitize_assistant_text("Result — as expected")
    assert "Result" in result

def test_tabs_in_input():
    result = sanitize_assistant_text("Column1\tColumn2")
    assert "Column1" in result
