"""Thinking-block stripping must handle redacted_thinking tags (Ornith, Qwen3, etc.)."""
from eli.cognition.gguf_inference import _strip_think_text


def test_strip_redacted_thinking_tag():
    raw = (
        "<think>\nThe user is correcting time.\n</think>\n\n"
        "You're right — it's ten to ten, not afternoon."
    )
    out = _strip_think_text(raw)
    assert "ten to ten" in out
    assert "correcting time" not in out


def test_strip_unclosed_thinking_returns_empty_not_raw_cot():
    raw = "<think>\nThinking Process:\n\n1. Analyze the Request\n"
    out = _strip_think_text(raw)
    assert "Analyze the Request" not in out
    assert out.strip() == ""


def test_strip_think_alias_tag():
    raw = "<think>reasoning</think>\n\nFair enough — my mistake."
    out = _strip_think_text(raw)
    assert out.startswith("Fair enough")
