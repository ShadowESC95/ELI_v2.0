"""personal_memory_surface.is_personal_memory_query — routes "what do you know about
me" style asks to the grounded personal-memory answer (not a web/chat guess). Pure.
"""
from __future__ import annotations

from eli.runtime.personal_memory_surface import is_personal_memory_query


def test_personal_queries_match():
    assert is_personal_memory_query("what do you know about me?") is True
    assert is_personal_memory_query("what do you remember about me") is True


def test_non_personal_do_not_match():
    assert is_personal_memory_query("what's the weather in Dublin") is False
    assert is_personal_memory_query("") is False
    assert is_personal_memory_query(None) is False
