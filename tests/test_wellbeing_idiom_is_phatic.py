""""How's the head?" is a hello, not a question about a component.

The classifier already had a `^how's the \\w+$` casual pattern, but it was gated at
five words and the real message was "Hey buddy, how's the ould head doing, now?" —
seven words after the greeting strip, because a LEADING direct-address ("buddy") was
never stripped the way a trailing one was, and the trailing filler ("doing, now")
counted as content.

Consequence beyond routing: reflection mines topics from non-phatic turns, so this
greeting donated "head" to the daily report's "Top topics" line twice over.

The risk in widening this is the opposite error — "how's the GPU doing" is a real
question that must keep its evidence gathering — so the idiom explicitly does not
apply when the subject is something ELI runs on.
"""
import pytest

from eli.kernel.engine import _is_brief_phatic_prompt as phatic


@pytest.mark.parametrize("asked", [
    "Hey buddy, how's the ould head doing, now?",   # the live message
    "how's the head",
    "how's the head doing",
    "how's the head today",
    "buddy how's the form",
    "hey pal, how's the craic",
    "how's your day going",
    "how are you",
    "what's the story",
    "hows things",
])
def test_wellbeing_check_ins_are_phatic(asked):
    assert phatic(asked.lower()), asked


@pytest.mark.parametrize("asked", [
    "how's the GPU doing",
    "how's the gpu",
    "how's the server holding up",
    "how's the build going",
    "how's the test suite",
    "how's the model doing",
    "how's the database",
    "how's the memory usage looking",
    "how's the index",
])
def test_technical_subjects_keep_their_evidence(asked):
    """These must not be swallowed as small talk — they are status questions."""
    assert not phatic(asked.lower()), asked


@pytest.mark.parametrize("asked", [
    "how do I fix the parser",
    "what does this mean about embeddings",
    "why did the build fail",
    "can you look at the vector store",
    "what have you been doing to the code",
])
def test_substantive_requests_are_untouched(asked):
    assert not phatic(asked.lower()), asked


def test_the_leading_address_strip_does_not_eat_a_request():
    """Stripping "buddy" must not turn a real ask into a greeting."""
    assert not phatic("buddy can you rebuild the vector index please")
    assert not phatic("mate the parser is broken again")
