"""context_builder.build_context — assembles a retrieval/context string; degrades
gracefully to a string in all cases (never crashes the turn).
"""
from __future__ import annotations

from eli.cognition.context_builder import build_context


def test_returns_string():
    assert isinstance(build_context("what's the weather"), str)


def test_empty_input_is_safe():
    assert isinstance(build_context(""), str)


def test_query_param_is_safe():
    assert isinstance(build_context(user_message="hi", query="solar"), str)
