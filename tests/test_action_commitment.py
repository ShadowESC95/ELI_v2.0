"""No fake actions: detect when ELI commits to / fakes an action."""
from eli.runtime.action_commitment import detect_action_commitment as d


def test_detects_commitments():
    for t in [
        "Let me check the latest news for you.",
        "I'll re-run that now.",
        "Let's fetch the headlines again.",
        "Give me a moment to verify that.",
        "One moment — pulling that up.",
        "Sure. Let me look up the weather.",
    ]:
        assert d(t) is not None, f"missed commitment: {t!r}"


def test_detects_fake_theatre():
    assert d("Checking... (fetching latest headlines) Here are the top stories: 1. [Story 1] 2. [Story 2]") is not None
    assert d("Here are the top stories:\n1. [Story 1]\n2. [Story 2]") is not None


def test_clause_carries_the_task_for_redispatch():
    out = d("Sure thing. Let me check the latest news for you. Hang tight.")
    assert out is not None
    assert "news" in out["clause"].lower()  # re-routing this yields NEWS_FETCH


def test_ignores_non_commitments():
    for t in [
        "Here are the latest headlines: a meteor exploded over Massachusetts.",
        "I'll get back to you if anything changes.",   # 'get back' is not an action verb
        "Let me know if you'd like more detail.",       # 'know' is not an action verb
        "That's an interesting question to think about.",
        "The news is fresh as of 14:23.",
    ]:
        assert d(t) is None, f"false positive: {t!r}"


def test_empty():
    assert d("") is None
    assert d(None) is None


from eli.runtime.action_commitment import is_redo_directive as redo


def test_redo_directives():
    for t in [
        "check it again",
        "do that again",
        "re-run it",
        "rerun that",
        "are you actually fetching the news?",
        "did you actually check?",
        "fetch it again please",
        "go on and check",
        "actually run it",
    ]:
        assert redo(t), f"missed redo: {t!r}"


def test_not_redo():
    for t in [
        "what is the latest news",      # fresh request, not a redo
        "check the news",               # fresh request
        "i'll check it myself later",   # user doing it
        "that's a good check",
        "thanks, that's great",
    ]:
        assert not redo(t), f"false redo: {t!r}"
