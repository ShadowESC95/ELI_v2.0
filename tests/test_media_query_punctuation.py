"""Punctuation between words is not part of the song.

Live: "play evil; by eminem on spotify" searched "evil; eminem".
"""
import pytest

from eli.execution.router_enhanced import _eli_mqc_clean_query as clean


@pytest.mark.parametrize("said,query", [
    ("evil; by eminem", "evil by eminem"),
    ('"lose yourself" by eminem', "lose yourself by eminem"),
    ("hey, soul sister by train", "hey soul sister by train"),
    ("evil... by eminem", "evil by eminem"),
    ("stan?", "stan"),
])
def test_separating_punctuation_goes(said, query):
    assert clean(said) == query


@pytest.mark.parametrize("name", ["so what by p!nk", "AC/DC back in black", "mr. brightside by the killers",
                                  "the notorious b.i.g. juicy", "what's my age again by blink-182"])
def test_punctuation_inside_a_name_stays(name):
    assert clean(name) == name
