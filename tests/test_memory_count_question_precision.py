"""Asking ELI's opinion on a pasted passage is not asking for a row count.

`_eli_mc_is_memory_count_question_v4` tested for its trigger words with plain
substring matching, and "count" lives inside "encountered" while "total" lives
inside "totally". So a paragraph containing both "memory" and "encountered" —
handed to ELI with "what do you think of this?" — was classified as "how many
memories do you have?" and answered with a database row count. It fired three
times on the same paste before the user gave up, and ELI then claimed it could
not see the text at all.

The trigger was unchanged since the initial import.
"""
from __future__ import annotations

import pytest

from eli.kernel.engine import _eli_mc_is_memory_count_question_v4 as is_count_q


PASTED = (
    "what do you think of this? Other local projects might have a few of these "
    "pieces, but nothing I've encountered integrates them into a cohesive, "
    "always-on personality like Eli does, or even my own memory features."
)


@pytest.mark.parametrize("q", [
    "how many memories do you have",
    "what is the total number of memories",
    "how many memory rows are there",
    "give me a count of your memories",
])
def test_real_count_questions_still_route(q):
    assert is_count_q(q) is True


@pytest.mark.parametrize("q", [
    PASTED,
    "i totally forgot what memory feels like",
    "nothing i have encountered stresses my memory like this",
    "your opinion on my memory system?",
    "what's your take on the memory design?",
    "thoughts on how memory should work?",
])
def test_these_are_not_count_questions(q):
    assert is_count_q(q) is False


def test_substring_collisions_specifically():
    """The two words that caused it. Keep them pinned."""
    assert is_count_q("i encountered a memory leak") is False
    assert is_count_q("memory is totally fine") is False


def test_asking_for_an_opinion_wins_over_the_keywords():
    """Even a sentence that genuinely contains both trigger words is a request
    for a view when it is framed as one."""
    assert is_count_q("what do you think of the total memory count") is False
