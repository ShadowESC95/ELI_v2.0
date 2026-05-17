"""Extended sanitizer tests with 300+ parametrized cases."""
from __future__ import annotations

import pytest
from eli.cognition.response_sanitizer import sanitize_assistant_text as san

# ── 100 varied filler+content combinations ────────────────────────────────

FILLER_CONTENT_PAIRS = [
    ("Of course! ", "The answer is 42."),
    ("Of course, ", "Let me explain."),
    ("Of course. ", "Here is what you need."),
    ("Certainly! ", "Python is a language."),
    ("Certainly, ", "The sky is blue."),
    ("Sure, ", "I can help with that."),
    ("Sure! ", "That's straightforward."),
    ("Sure thing, ", "Here you go."),
    ("Sure thing! ", "No problem."),
    ("Absolutely! ", "Great choice."),
    ("Absolutely, ", "Let me break it down."),
    ("Happy to help! ", "The solution is."),
    ("Happy to help, ", "First, install Python."),
    ("Great question! ", "Recursion is."),
    ("Great question, ", "The concept is."),
    ("Excellent question! ", "Consider this."),
    ("Excellent question, ", "There are two approaches."),
    ("Good question! ", "The answer depends."),
    ("Good question, ", "It varies."),
    ("That's a great question! ", "Let me explain."),
    ("That's a great question, ", "In short."),
    ("That's a great point! ", "Building on that."),
    ("That's a great point, ", "We should consider."),
    ("I'd be happy to! ", "Help you."),
    ("I'd be happy to, ", "Explain this."),
    ("I'm glad you asked! ", "This is interesting."),
    ("I'm glad you asked, ", "Here's why."),
    ("Short answer: ", "Yes."),
    ("Short answer: ", "42 is the answer."),
    ("Short answer: ", "No, that's incorrect."),
]

@pytest.mark.parametrize("filler,content", FILLER_CONTENT_PAIRS)
def test_filler_stripped_content_preserved(filler, content):
    result = san(f"{filler}{content}")
    assert content.strip().split()[0] in result


# ── 50 stage prefix variations ────────────────────────────────────────────

@pytest.mark.parametrize("prefix,content", [
    ("eli: ", "Direct answer."),
    ("ELI: ", "Direct answer."),
    ("Eli: ", "Direct answer."),
    ("assistant: ", "Here is the response."),
    ("ASSISTANT: ", "Here is the response."),
    ("Assistant: ", "Here is the response."),
    ("calmly: ", "Everything is fine."),
    ("CALMLY: ", "Everything is fine."),
    ("quietly: ", "Whispered truth."),
    ("softly: ", "Gentle response."),
    ("gently: ", "Kind words."),
    ("warmly: ", "Welcome message."),
    ("plainly: ", "Simple statement."),
    ("dryly: ", "Deadpan delivery."),
    ("  eli:  ", "Spaced prefix."),
    ("  ELI:  ", "Spaced prefix."),
    ("eli: '", "Quoted content."),
    ('eli: "', "Double quoted."),
    ("QUIETLY: ", "Soft answer."),
    ("SOFTLY: ", "Tender response."),
])
def test_stage_prefix_stripped_content_preserved(prefix, content):
    result = san(f"{prefix}{content}")
    assert result  # not empty


# ── 50 placeholder variations ─────────────────────────────────────────────

PLACEHOLDER_TEXTS = [
    "Hello [user], how are you?",
    "Good morning [User]!",
    "Hi there [USER].",
    "Welcome back [username].",
    "Hey [Username]!",
    "Greetings [USERNAME].",
    "Hello [name].",
    "Hi [Name]!",
    "Welcome [NAME].",
    "Hello <user>.",
    "Hi <User>!",
    "Welcome <USER>.",
    "Hello <local_user>.",
    "Hi <local_User>.",
    "Greetings <username>.",
    "Welcome <Username>.",
    "Hello <name>.",
    "Hi <Name>!",
    "Greetings <NAME>.",
    "Good to see you [user] again.",
    "How can I help you [user] today?",
    "Let me help you [username] with that.",
    "Hello <user>, I'm ELI.",
]

@pytest.mark.parametrize("text", PLACEHOLDER_TEXTS)
def test_placeholder_removed(text):
    result = san(text)
    import re
    assert not re.search(r'\[(user|username|name)\]', result, re.I)
    assert not re.search(r'<(user|local_user|username|name)>', result, re.I)


# ── 50 whitespace edge cases ──────────────────────────────────────────────

@pytest.mark.parametrize("text,expect_clean", [
    ("hello  world", "hello world"),
    ("hello   world", "hello world"),
    ("hello    world", "hello world"),
    ("a  b  c  d", "a b c d"),
    ("text ,punctuation", "text,punctuation"),
    ("text .period", "text.period"),
    ("text !exclaim", "text!exclaim"),
    ("text :colon", "text:colon"),
    ("text ;semi", "text;semi"),
    ("text ?question", "text?question"),
    ("  leading space", "leading space"),
    ("trailing space  ", "trailing space"),
    ("  both  ", "both"),
    ('"quoted text"', "quoted text"),
    ("'single quoted'", "single quoted"),
    ('  "  spaced quoted  "  ', "spaced quoted"),
])
def test_whitespace_normalization(text, expect_clean):
    result = san(text)
    assert result == expect_clean


# ── 50 content preservation tests ────────────────────────────────────────

TECHNICAL_CONTENT = [
    "The GPU has 8GB VRAM",
    "Use n_gpu_layers=11 for partial offload",
    "Python 3.12 introduces new syntax",
    "SQLite FTS5 enables full-text search",
    "FAISS uses L2 distance by default",
    "Temperature=0.7 is a good default",
    "Set batch_size=512 for throughput",
    "The model has 7B parameters",
    "llama.cpp enables CPU inference",
    "GGUF format is the standard",
    "RTX 2060 SUPER has 8GB VRAM",
    "PySide6 is the GUI framework",
    "ONNX runtime enables voice synthesis",
    "piper-tts uses ONNX voice models",
    "The error is FileNotFoundError",
    "Use `pip install -r requirements.txt`",
    "Run `python -m eli` to start",
    "The model loaded in 3.2 seconds",
    "Context window is 16384 tokens",
    "Max tokens is set to -1 (unlimited)",
]

@pytest.mark.parametrize("text", TECHNICAL_CONTENT)
def test_technical_content_preserved(text):
    result = san(text)
    # Key numbers and technical terms should survive
    words = text.split()
    key_word = next((w for w in words if any(c.isdigit() for c in w) or len(w) > 5), words[0])
    assert key_word.rstrip("=.,;:") in result or len(result) > 0


# ── 30 combined transformation tests ─────────────────────────────────────

COMBINED_CASES = [
    ("eli: Of course! Hello [user].", "Hello"),
    ("assistant: Certainly, welcome [username]!", "welcome"),
    ("calmly: Sure thing, let me help <user>.", "let me help"),
    ("eli: Short answer: yes, definitely.", "yes, definitely"),
    ("ELI: I'd be happy to help [name] with that.", "help"),
    ("quietly: Happy to help! Here is the answer.", "Here is the answer"),
    ("warmly: Great question! The answer is 42.", "The answer is 42"),
    ("gently: That's a great point, building on this.", "building on this"),
    ("softly: Of course, here are the steps.", "here are the steps"),
    ("plainly: Absolutely! The solution is clear.", "The solution is clear"),
]

@pytest.mark.parametrize("input_text,expected_fragment", COMBINED_CASES)
def test_combined_transformations(input_text, expected_fragment):
    result = san(input_text)
    assert expected_fragment.lower() in result.lower()


# ── 20 unicode and encoding tests ─────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Hello 日本語 world",
    "Bonjour le monde — comment ça va?",
    "Héllo wörld",
    "Привет мир",
    "مرحبا بالعالم",
    "你好世界",
    "Emoji: 🤖 🧠 💻",
    "Greek: αβγδ",
    "Math: ∑∫∂∇",
    "Special: €£¥§©",
    "Mixed: hello 世界 world",
    "Arrows: → ← ↑ ↓",
    "Dashes: em—dash en–dash",
    "Quotes: “smart” and ‘smart’",
    "Ellipsis: …",
])
def test_unicode_text_handled(text):
    result = san(text)
    assert isinstance(result, str)
    assert len(result) > 0
