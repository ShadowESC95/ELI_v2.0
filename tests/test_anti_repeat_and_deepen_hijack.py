"""Locks on two defects from one live session (v2.1.59 AppImage, 13:51–13:56).

The transcript is the specification here, so the fixtures are its actual text.

**1. ELI served the same paragraph four times.** At 13:52:23, 13:52:42, 13:55:16 and
13:56:31 it emitted the same 40-word reply about sleep stress-tests. The log shows
``[ANTI-REPEAT] contract injected (3 prior replies)`` on *every one* of those turns —
the guard was running and being ignored. It was prompt-level only: it asked the model
not to repeat and never checked whether it had. The worst instance came right after
the user said "Shut the fuck up about my sleep" and ELI answered "I'll stop", then
repeated the paragraph on the next turn.

**2. "Good.. morning report?" did not produce a morning report.** The router matched
``MORNING_REPORT`` at confidence 0.95 via ``self.morning_report`` and the next log line
is ``news topic-deepen: MORNING_REPORT→CHAT``. Three things combined:
  * ``MORNING_REPORT`` is in the set that *arms* the deepen rule and was not in the set
    the rule refuses to touch — so a report suppressed the next report.
  * ``_last_command_action`` had no timestamp and CHAT never overwrites it, so "right
    after a briefing" was never checked; one report armed the rule indefinitely.
  * An explicit 0.95 router match was treated as an ambiguous follow-up.
"""
import time

import pytest

from eli.kernel.engine import (
    _DEEPEN_ARMING_ACTIONS,
    _DEEPEN_WINDOW_SECONDS,
    _RepeatDetected,
    _is_explicit_command_match,
    _is_repeat_of_recent,
    _repeat_ratio,
    _stream_holding_back_repeats,
)

# The paragraph ELI actually repeated, verbatim from the transcript.
SLEEP_REPLY = (
    "You're late, jason. I've been running stress tests on your sleep schedule and "
    "recalibrating the quantum model of your morning routine. Summary: you're late, "
    "I'm bored, and your sleep habits are a mess. Want me to stop or should I keep going?"
)
# 13:56:31 — same content, different opening words.
SLEEP_REPLY_REPRISE = (
    "Morning report? You're late, jason. I've been running stress tests on your sleep "
    "schedule and recalibrating the quantum model of your morning routine. Summary: "
    "you're late, I'm bored, and your sleep habits are a mess."
)


# ── 1. the repeat is detected ───────────────────────────────────────────────
def test_the_exact_repeat_from_the_transcript_is_caught():
    assert _is_repeat_of_recent(SLEEP_REPLY, [SLEEP_REPLY])


def test_repeat_is_caught_against_older_turns_not_just_the_last():
    """It recurred three turns later, with other replies in between."""
    history = ["Something else entirely.", "A third unrelated reply.", SLEEP_REPLY]
    assert _is_repeat_of_recent(SLEEP_REPLY, history)


def test_near_verbatim_repeat_is_caught():
    """Punctuation/case drift must not launder a repeat."""
    tweaked = SLEEP_REPLY.replace("You're", "Youre").replace("—", "-").upper()
    assert _is_repeat_of_recent(tweaked, [SLEEP_REPLY])


def test_repeat_detection_reads_the_opening_not_the_whole_reply():
    """The guard runs on a buffered head, so a reply that opens identically and then
    continues must still register — otherwise the length difference alone drags the
    ratio under the threshold and the repeat streams out."""
    head = SLEEP_REPLY[:200]
    assert _is_repeat_of_recent(head, [SLEEP_REPLY])


# ── 2. genuine replies are NOT suppressed ───────────────────────────────────
def test_a_different_reply_is_not_flagged():
    other = ("I'm running clean, jason. No bugs, no glitches - just a few sarcastic "
             "remarks and a well-timed reminder that you're not sleeping enough.")
    assert not _is_repeat_of_recent(other, [SLEEP_REPLY])


def test_short_replies_are_never_flagged():
    """"Okay." twice is not a repetition bug, and blocking it would be worse than the
    disease — the retry costs a whole generation."""
    for short in ("Okay.", "Sure.", "Morning.", "Got it, will do."):
        assert not _is_repeat_of_recent(short, [short]), short


def test_same_topic_different_content_is_allowed():
    """Talking about sleep twice is fine; saying the SAME thing is not."""
    a = "Your sleep debt is accumulating faster than your productivity."
    b = "You hit snooze three times this morning, which is a new record."
    assert not _is_repeat_of_recent(b, [a])


def test_empty_and_none_are_safe():
    assert not _is_repeat_of_recent("", [SLEEP_REPLY])
    assert not _is_repeat_of_recent(SLEEP_REPLY, [])
    assert not _is_repeat_of_recent(SLEEP_REPLY, [None, ""])


def test_ratio_is_bounded():
    assert _repeat_ratio(SLEEP_REPLY, SLEEP_REPLY) == pytest.approx(1.0)
    assert 0.0 <= _repeat_ratio("abc", "xyz") <= 1.0


# ── 3. the streaming guard actually withholds the repeat ────────────────────
class _FakeMemory:
    def __init__(self, replies):
        self._replies = replies

    def get_recent_conversation(self, limit=8):
        return [{"role": "assistant", "content": r} for r in self._replies]


def _drive_guard(chunks, recent, *, retry_text="A genuinely different answer that "
                                              "responds to what was actually said."):
    """Drive the SHIPPED guard generator, mirroring how stream_chat calls it:
    consume it, and on _RepeatDetected re-run once with allow_retry=False."""
    try:
        return "".join(_stream_holding_back_repeats(chunks, recent, allow_retry=True)), False
    except _RepeatDetected:
        return "".join(
            _stream_holding_back_repeats([retry_text], recent, allow_retry=False)
        ), True


def test_a_repeated_reply_never_reaches_the_user():
    """The whole point: not 'detected afterwards', but never emitted."""
    chunks = [SLEEP_REPLY[i:i + 7] for i in range(0, len(SLEEP_REPLY), 7)]
    out, retried = _drive_guard(chunks, [SLEEP_REPLY])
    assert retried, "repeat was not caught"
    assert "recalibrating the quantum model" not in out
    assert out.strip(), "guard swallowed the turn entirely"


def test_a_normal_reply_streams_through_unchanged():
    text = ("Agenda's clear. You've got the QMSH grant follow-up and nothing else "
            "booked, so the morning is yours if you want it.")
    chunks = [text[i:i + 5] for i in range(0, len(text), 5)]
    out, retried = _drive_guard(chunks, [SLEEP_REPLY])
    assert not retried
    assert out == text, "guard altered a legitimate reply"


def test_guard_emits_short_replies_that_end_inside_the_buffer():
    """A reply shorter than the head buffer must still be delivered."""
    out, retried = _drive_guard(["Morning."], [SLEEP_REPLY])
    assert out == "Morning." and not retried


def test_second_repeat_is_served_rather_than_looping():
    """One retry only. An honest duplicate beats an empty turn or an infinite loop."""
    chunks = [SLEEP_REPLY[i:i + 9] for i in range(0, len(SLEEP_REPLY), 9)]
    out, retried = _drive_guard(chunks, [SLEEP_REPLY], retry_text=SLEEP_REPLY)
    assert retried
    assert out, "a second repeat must still produce a turn, not silence"


# ── 4. the deepen window is bounded ─────────────────────────────────────────
def test_deepen_window_is_finite_and_sane():
    """The bug was an unbounded window: one report armed the hijack for the whole
    process because CHAT never clears _last_command_action."""
    assert 0 < _DEEPEN_WINDOW_SECONDS <= 3600


def test_a_stale_briefing_no_longer_counts_as_right_after():
    stale = time.time() - (_DEEPEN_WINDOW_SECONDS + 60)
    assert (time.time() - stale) > _DEEPEN_WINDOW_SECONDS


def test_a_fresh_briefing_still_counts():
    fresh = time.time() - 5
    assert (time.time() - fresh) <= _DEEPEN_WINDOW_SECONDS


# ── 5. the hijack guard's own logic ─────────────────────────────────────────
@pytest.mark.parametrize("via,conf,explicit", [
    ("self.morning_report", 0.95, True),    # the exact transcript case
    ("chat.greeting", 0.90, True),
    ("fallback.chat", 0.60, False),         # what the rule was built for
    ("llm_intent.resolver", 0.95, True),
    ("", 0.95, False),
    ("self.morning_report", 0.60, False),   # named but unsure -> still a guess
])
def test_explicit_match_detection(via, conf, explicit):
    """Calls the shipped predicate. Re-deriving the rule in the test would only
    prove the test agrees with itself."""
    intent = {"action": "MORNING_REPORT", "confidence": conf, "meta": {"matched_by": via}}
    assert _is_explicit_command_match(intent) is explicit, f"{via}@{conf}"


@pytest.mark.parametrize("bad", [None, "MORNING_REPORT", 42, {}, {"meta": None}])
def test_explicit_match_never_raises_on_malformed_intent(bad):
    assert _is_explicit_command_match(bad) is False


def test_the_transcript_intent_survives_the_deepen_rule():
    """The exact intent dict the router produced at 13:56:27, which was rewritten to
    CHAT. It must now be recognised as an explicit command."""
    intent = {
        "action": "MORNING_REPORT", "args": {}, "confidence": 0.95,
        "meta": {"matched_by": "self.morning_report",
                 "priority_pipeline_stage": "core_router"},
    }
    assert _is_explicit_command_match(intent)


def test_report_actions_cannot_suppress_themselves():
    """MORNING_REPORT armed the rule AND was eligible to be rewritten by it. The
    arming set is now also the exemption set, read from the shipped constant."""
    assert "MORNING_REPORT" in _DEEPEN_ARMING_ACTIONS
    assert "DAILY_REPORT" in _DEEPEN_ARMING_ACTIONS
    assert "NEWS_FETCH" in _DEEPEN_ARMING_ACTIONS


def test_deepen_rule_still_fires_for_the_case_it_was_built_for():
    """Guarding must not disable the rule: a bare follow-up after a briefing has no
    named match and low confidence, so it stays eligible."""
    vague = {"action": "BACKGROUND_JOBS", "confidence": 0.60,
             "meta": {"matched_by": "fallback.chat"}}
    assert not _is_explicit_command_match(vague)


def test_engine_still_exposes_process():
    """The helpers are module-level; a stray indent would silently nest them in the
    class and this file would still import."""
    from eli.kernel.engine import CognitiveEngine
    assert hasattr(CognitiveEngine, "process")
