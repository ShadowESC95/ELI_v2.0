"""An intensifier is not a subject.

Live at 2.3.9 the Proactive tab reported:

    Current focus areas: fuck (×8), memory (×8), world (×7), self (×5), screen (×5)

`topic_focus` answers "what subjects does this person care about", and its answer
feeds persona updates and proactive suggestions. So ELI had begun modelling
profanity as an interest and offering to help with it.

This is the third instance of one bug, and the file's own comments record the
other two:

    2.3.0    open (×10), youre (×9), memory (×9)        ← "youre" as a topic
    overnight afternoon (×11), doing (×10), today (×10) ← from "afternoon, Eli"

Every one of them cleared the ≥4-character bar while carrying no subject matter.

This is NOT a content filter, and the distinction is the point:

  * `tone_analyzer._FRUSTRATION` matches "what the f[a-z]*" deliberately — that is
    how ELI knows the operator is annoyed, and it reads the raw text. Untouched.
  * ELI's own replies are unaffected; the emergent voice can swear back.
  * Only the question "what is this person interested in" stops counting emphasis
    as an answer.
"""
import pytest

from eli.cognition.tone_analyzer import analyze_turns
from eli.runtime.reflection import TOPIC_STOPWORDS, topic_words


ANGRY = "this fucking memory system is broken again, the world model is shit"


def test_the_reported_case_no_longer_yields_profanity_as_a_topic():
    assert "fuck" not in topic_words(ANGRY)
    assert "fucking" not in topic_words(ANGRY)
    assert "shit" not in topic_words(ANGRY)


def test_the_real_subjects_survive():
    """Dropping the wrong words must not drop the right ones."""
    topics = topic_words(ANGRY)
    for subject in ("memory", "system", "world", "model", "broken"):
        assert subject in topics, f"{subject!r} is a genuine subject and was lost"


@pytest.mark.parametrize("word", [
    "fuck", "fucking", "shit", "crap", "damn", "bloody", "bollocks",
    "wtf", "goddamn", "pissed",
])
def test_expletives_are_topic_noise(word):
    assert word in TOPIC_STOPWORDS


@pytest.mark.parametrize("word", [
    "literally", "totally", "seriously", "honestly", "basically", "obviously",
])
def test_non_expletive_intensifiers_are_topic_noise_too(word):
    """The category is 'emphasis', not 'rude'. Filtering only swearing would leave
    the same bug wearing a politer word."""
    assert word in TOPIC_STOPWORDS


def test_frustration_detection_is_untouched():
    """The emotional signal has its own path that reads the raw text and matches
    expletives on purpose. Removing them from TOPIC extraction must not blind it."""
    result = analyze_turns([
        "what the fuck is wrong with the memory system",
        "this is broken again, seriously",
        "come on, still wrong",
    ])
    assert result["frustration_rate"] == 1.0


def test_the_earlier_two_instances_stay_fixed():
    """Regression guard for the cases already recorded in the source comments."""
    assert "youre" in TOPIC_STOPWORDS       # 2.3.0
    assert "afternoon" in TOPIC_STOPWORDS   # overnight run
    assert "doing" in TOPIC_STOPWORDS


def test_a_word_that_is_genuinely_about_swearing_is_still_reachable():
    """Someone discussing profanity as a subject says "profanity" or "language",
    not the word itself — those must not be filtered."""
    topics = topic_words("can you tone down the profanity in your language")
    assert "profanity" in topics and "language" in topics


def test_stopwords_stay_lowercase_and_apostrophe_free():
    """topic_words() lowercases and strips apostrophes before the lookup, so an
    entry carrying either would never match — the exact reason "youre" had to be
    listed without one."""
    for word in TOPIC_STOPWORDS:
        assert word == word.lower(), f"{word!r} would never match"
        assert "'" not in word, f"{word!r} would never match"
