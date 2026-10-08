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


from eli.runtime.action_commitment import extract_deepen_topic as deepen


def test_extract_deepen_topic():
    # "look closer into Hubble" must yield the topic, not the whole briefing,
    # so a news deepen re-fetches that subject (user-reported: topic-deepen bug).
    cases = {
        "look closer into Hubble": "Hubble",
        "look into Hubble": "Hubble",
        "tell me more about Hubble": "Hubble",
        "look closer into the Hubble story": "Hubble",
        "can you look deeper into the Hubble news": "Hubble",
        "more on Hubble": "Hubble",
        "dig into Hubble": "Hubble",
        "go deeper on the Gaza ceasefire": "Gaza ceasefire",
    }
    for text, want in cases.items():
        assert deepen(text) == want, f"{text!r} -> {deepen(text)!r}, want {want!r}"


def test_deepen_topic_ignores_non_deepen():
    for t in ["what is the latest news", "play hubble by someone", "hello there", ""]:
        assert deepen(t) == "", f"false deepen topic on {t!r}: {deepen(t)!r}"


from eli.runtime.action_commitment import REDO_MAX_AGE_S, redo_applies
import time
from eli.cognition.self_claims import complains_about_eli


def test_redo_only_reruns_a_recent_action_it_is_about():
    """Live (2026-10-02): "did you actually read the files" re-ran a Spotify
    pause from seven minutes earlier. A redo needs the last action to be recent
    and, when the directive names a verb, to be that action."""
    now = 1_000_000.0
    pause = {"action": "PAUSE_MEDIA", "args": {}, "ts": now - 30}
    news = {"action": "NEWS_FETCH", "args": {}, "ts": now - 30}
    live = "Are you just saying that, or did you actually read the files.orchestrator etc.?"
    assert not redo_applies(live, pause, now=now)
    assert not redo_applies(live, dict(pause, ts=now - 420), now=now)
    assert not redo_applies("did you actually play it?", pause, now=now)
    assert redo_applies("did you actually pause it?", pause, now=now)
    assert redo_applies("did you really set the timer?", {"action": "SET_TIMER", "ts": now - 5}, now=now)
    # Generic directives still re-run whatever just ran.
    for t in ("did you actually check?", "are you actually fetching the news?", "do it again"):
        assert redo_applies(t, news, now=now), t


def test_redo_never_reruns_a_stale_or_missing_action():
    now = 1_000_000.0
    stale = {"action": "NEWS_FETCH", "ts": now - REDO_MAX_AGE_S - 1}
    assert not redo_applies("do it again", stale, now=now)
    assert not redo_applies("do it again", {"action": "NEWS_FETCH"}, now=now)  # no timestamp
    assert not redo_applies("do it again", None, now=now)


# "You did not open spotify" re-runs the open, when that is what ELI just did.
#
# Live: "open spotify" -> "Opened app: Spotify" (it had died at once), then "You did not open spotify
# again!!!" went to chat and ELI wrote that it had reviewed the logs, and a pretend ```bash open
# spotify``` block. Nothing was opened.
NOW = time.time()
OPENED = {"action": "OPEN_APP", "args": {"name": "spotify"}, "input": "open spotify", "ts": NOW - 20}
PLAYED = {"action": "PLAY_MEDIA", "args": {"target": "spotify", "query": "trouble by eminem"},
          "input": "play trouble by eminem", "ts": NOW - 20}


def test_saying_it_did_not_happen_redoes_it():
    for text in ("You did not open spotify again!!!", "spotify didn't open", "nothing happened",
                 "it didn't work", "you never opened it", "spotify still hasn't opened"):
        assert redo_applies(text, OPENED, now=NOW), text
    for text in ("it didn't play", "you didn't play it", "the song didn't play", "nothing is playing",
                 "spotify didn't play the song"):
        assert redo_applies(text, PLAYED, now=NOW), text


def test_only_when_it_is_about_what_eli_just_did():
    assert not redo_applies("you did not open firefox", OPENED, now=NOW)
    assert not redo_applies("you did not play the song", OPENED, now=NOW)
    assert not redo_applies("the printer didn't work", OPENED, now=NOW)
    assert not redo_applies("spotify didn't open", dict(OPENED, ts=NOW - 3600), now=NOW)


def test_the_user_talking_about_themselves_is_not_a_redo():
    for text in ("I did not open it", "we didn't open it yet", "You didn't, i am asking you why you feel"):
        assert not redo_applies(text, OPENED, now=NOW), text


def test_saying_it_did_not_happen_is_a_complaint_about_eli():
    assert complains_about_eli("You did not open spotify again!!!")
    assert complains_about_eli("you haven't played anything")
    assert not complains_about_eli("you never know, it might rain")
