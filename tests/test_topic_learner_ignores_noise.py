"""Filler and non-committal answers are not learned as interests or goals."""
from eli.runtime.reflection import TOPIC_STOPWORDS, topic_words


def test_the_live_noise_words_are_not_topics():
    for w in ("well", "haha", "last", "high"):
        assert w in TOPIC_STOPWORDS
    assert topic_words("well haha that last one was high quality bergen") == {"bergen", "quality"}


def test_real_subjects_survive():
    assert {"bergen", "trondheim"} <= topic_words("driving from bergen to trondheim on saturday")


def test_the_non_committal_onboarding_answer_is_not_a_goal_to_support():
    from eli.onboarding.interview import NONCOMMITTAL_FOCUS
    assert NONCOMMITTAL_FOCUS == "Mix of everything"
