"""Compound greetings with a real request must not take the phatic fast-path."""
from eli.kernel.engine import _is_brief_phatic_prompt


def test_greeting_plus_lowdown_is_not_phatic():
    assert not _is_brief_phatic_prompt(
        "hey pal, how are you? gimme the full lowdown and stats"
    )


def test_pure_greeting_still_phatic():
    assert _is_brief_phatic_prompt("hey pal, how are you?")


def test_memory_meta_question_not_phatic():
    assert not _is_brief_phatic_prompt(
        "are you just referring to hardcoded stubs? what about dynamic understanding of me?"
    )
