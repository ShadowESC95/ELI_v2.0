"""Onboarding multi-select resolution.

Regression: the character-scan branch read the CONNECTOR WORDS as picks —
"a, b, and c" matched the 'a' and 'd' inside "and", so option (d) the user never
chose was written into their profile. Connectors must never contribute a pick.
"""
import pytest

from eli.onboarding.interview import _resolve_mc_choice

OPTS = {"a": "Concise", "b": "Detailed", "c": "Playful", "d": "Formal"}


def _parts(result):
    return [p.strip() for p in result.split(";")]


def test_single_letter():
    assert _resolve_mc_choice("a", OPTS) == "Concise"


@pytest.mark.parametrize("answer,expected", [
    ("a, b, and c", ["Concise", "Detailed", "Playful"]),
    ("a and b",     ["Concise", "Detailed"]),
    ("c or d",      ["Playful", "Formal"]),
    ("b & d",       ["Detailed", "Formal"]),
    ("a, c",        ["Concise", "Playful"]),
    ("a/b",         ["Concise", "Detailed"]),
])
def test_multi_select(answer, expected):
    assert _parts(_resolve_mc_choice(answer, OPTS)) == expected


@pytest.mark.parametrize("answer", ["a, b, and c", "a and b", "a and c"])
def test_connector_never_injects_an_unpicked_option(answer):
    """The whole point: 'and' contains 'a' and 'd' — neither may become a pick."""
    got = _parts(_resolve_mc_choice(answer, OPTS))
    assert "Formal" not in got, f"option (d) leaked from a connector word: {got}"


def test_order_is_preserved():
    assert _parts(_resolve_mc_choice("c, a", OPTS)) == ["Playful", "Concise"]


def test_duplicates_collapse():
    assert _parts(_resolve_mc_choice("a, a, b", OPTS)) == ["Concise", "Detailed"]


def test_empty_answer_passes_through():
    assert _resolve_mc_choice("", OPTS) == ""


def test_unknown_letters_are_not_invented():
    """'z' is not an option — it must not resolve to anything."""
    assert "Concise" not in _resolve_mc_choice("z", OPTS)
