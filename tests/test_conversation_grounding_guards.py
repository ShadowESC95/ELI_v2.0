"""Locks on four guards that let a conversational turn get hijacked or parroted.

All four were diagnosed from one live 2.1.95 transcript, and three of them share
a single root cause: a bare `in` / regex-stem test asserting intent that one more
line of checking refutes.

  user> Still on loop, seson 3 now. How is your memory after all the codebse changes?
  ELI > I'm still on loop, season 3 now. Your memory's a bit fuzzy…      <- echo

  user> Still going, taking over the world one LOC at a time.
        My memory is fine, it is yours that we are concerned about
  ELI > Personal memory evidence report / Durable rows: 431 / User DB: …  <- hijack

and, invisibly, `[PENDING_PROPOSAL] stored: 'keep a deeper'` — a fragment of
ELI's own prose armed as a command for the next "yes".
"""
import pytest

from eli.execution.router_enhanced import _pm_asks_something, route
from eli.kernel.engine import (
    _RepeatDetected, _opens_by_echoing, _stream_holding_back_repeats,
)
from eli.runtime.pending_proposal import extract_proposal

USER_TURN = "Still on loop, seson 3 now. How is your memory after all the codebse changes?"


def _stream(text, size=20):
    for i in range(0, len(text), size):
        yield text[i:i + size]


# ── 1. the router must not answer a remark with a database report ───────────
@pytest.mark.parametrize("text", [
    "Still going, taking over the world one LOC at a time. "
    "My memory is fine, it is yours that we are cincerned about",
    "my memory is fine",
    "my memory is great these days",
    "haha my memory is personal business",
])
def test_statements_mentioning_memory_are_not_hijacked(text):
    assert (route(text) or {}).get("action") != "PERSONAL_MEMORY_DEEP_EXPLAIN"


@pytest.mark.parametrize("text", [
    "what is in your personal memory?",
    "show me your personal memory",
    "which db holds my memory",
    "explain your personalised memory",
])
def test_genuine_memory_requests_still_route(text):
    assert (route(text) or {}).get("action") == "PERSONAL_MEMORY_DEEP_EXPLAIN"


def test_asking_test_is_word_boundary_anchored():
    """"it is yourS" contains the substring "is your" — the un-anchored version
    passed the exact sentence it was written to reject."""
    assert not _pm_asks_something("it is yours that we are concerned about")
    assert _pm_asks_something("is your memory ok")


# ── 2. ELI must not open with the user's own sentence ───────────────────────
def test_the_live_echo_is_detected():
    echo = ("I'm still on loop, season 3 now. Your memory's a bit fuzzy—"
            "last time you asked about it.")
    assert _opens_by_echoing(echo, [USER_TURN])


@pytest.mark.parametrize("reply", [
    "My memory is holding up fine after all those changes — 431 durable rows.",
    "Season 3 is where it gets good. Memory-wise I'm steady.",
    "Sure.",
])
def test_genuine_replies_are_not_flagged(reply):
    assert not _opens_by_echoing(reply, [USER_TURN])


def test_quoting_the_user_later_in_the_reply_is_fine():
    """Only the OPENING is judged: referring back mid-answer is legitimate."""
    reply = ("Memory's fine. You said 'Still on loop, seson 3 now' — "
             "that's still in the log.")
    assert not _opens_by_echoing(reply, [USER_TURN])


def test_short_echo_is_caught_even_though_it_never_fills_the_buffer():
    """An echoed opening is usually short, so it is the end-of-stream flush that
    has to catch it, not the 200-char head check."""
    echo = "I'm still on loop, season 3 now. Your memory's a bit fuzzy."
    with pytest.raises(_RepeatDetected):
        list(_stream_holding_back_repeats(
            _stream(echo), [], allow_retry=True, echo_sources=[USER_TURN]))


def test_a_genuine_reply_streams_through_untouched():
    good = "My memory is holding up fine after all those changes, thanks for asking."
    out = "".join(_stream_holding_back_repeats(
        _stream(good), [], allow_retry=True, echo_sources=[USER_TURN]))
    assert out == good


def test_final_attempt_salvages_rather_than_serving_the_echo():
    """No retry left: drop the echoed sentence, serve the rest. An empty turn
    would be worse than the echo."""
    echo = "I'm still on loop, season 3 now. Your memory's a bit fuzzy."
    out = "".join(_stream_holding_back_repeats(
        _stream(echo), [], allow_retry=False, salvage=True, echo_sources=[USER_TURN]))
    assert out.strip(), "salvage produced an empty turn"
    assert "still on loop" not in out.lower()


def test_guard_is_inert_without_echo_sources():
    """Existing callers pass no echo_sources and must be unaffected."""
    echo = "I'm still on loop, season 3 now. Your memory's a bit fuzzy."
    out = "".join(_stream_holding_back_repeats(_stream(echo), [], allow_retry=True))
    assert out == echo


# ── 3. only a question can be a queued offer ───────────────────────────────
def test_declarative_about_the_user_is_not_an_offer():
    """The live case: this armed 'keep a deeper' for 300 seconds, so the next
    'yes' would have routed that fragment as a command."""
    said = ("You want me to keep a deeper, more characterful persona "
            "while staying technically grounded.")
    assert extract_proposal(said) == ""


@pytest.mark.parametrize("reply,expected", [
    ("Want me to update the profile?", "update the profile"),
    ("Here is the summary. Want me to save it?", "save it"),
    ("Do you want me to run the backup?", "run the backup"),
    ("Shall I restart the server?", "restart the server"),
    ("I can run that for you?", "run that for you"),
])
def test_real_offers_still_queue(reply, expected):
    assert extract_proposal(reply) == expected


@pytest.mark.parametrize("reply", [
    "I'll be waiting here.",
    "You said you want me to challenge assumptions.",
    "I can appreciate the absurdity of it.",
])
def test_narrative_never_queues(reply):
    assert extract_proposal(reply) == ""


# ── 4. the startup ALSA storm ──────────────────────────────────────────────
def test_mic_dropdown_enumerates_under_the_stderr_guard():
    """`list_microphone_names()` builds a PyAudio instance and PortAudio prints
    ~28 lines of ALSA/JACK probe noise from C. This populates a Settings combo
    during GUI construction, so it was the first thing a user saw on a healthy
    launch — and it was the only remaining unguarded caller."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py"
    text = src.read_text(encoding="utf-8")

    # Match the CALL, not prose about it — the explanatory comment above the fix
    # mentions list_microphone_names() too, and anchoring on the first textual
    # occurrence would have this test pass by reading a comment.
    call = "_sr.Microphone.list_microphone_names()"
    assert call in text, "the mic enumeration call moved; update this test"
    window = text[max(0, text.index(call) - 200):text.index(call)]
    assert "quiet_native_stderr" in window, \
        "the mic dropdown enumerates devices without silencing PortAudio"
