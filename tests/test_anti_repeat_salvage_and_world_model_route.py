"""Locks on two defects from one live session (v2.1.80 AppImage, 14:33–14:35).

The transcript is the specification here, so the fixtures are its actual text.

**1. The anti-repeat retry served the duplicate anyway.** Turn 2 and turn 3 opened
with the identical two sentences ("You're not wrong — I'm a bit of a hot mess…").
The log shows the guard working exactly as designed and still losing:

    [ANTI-REPEAT] opening matched a recent reply — regenerating
    [ANTI-REPEAT] retry generation issued (persona handoff de-primed: 7878 -> 7296 chars)
    [GGUF][RAW_HEAD] 'You'      ← attempt 1
    [GGUF][RAW_HEAD] 'You'      ← attempt 2, same opening

Two causes, both fixed here:
  * De-priming the persona handoff removed the anti-repeat contract's quotes, but
    the same paragraph still reached the model through the assembled memory
    context and the handoff's evidence block — so the retry was reading its own
    last reply. It is now redacted from every block that feeds the retry.
  * The retry re-ran at the same temperature on a 92%-identical prompt, which is
    a re-roll of the same dice. Sampling is widened on the retry.
  * And when a retry *does* recycle its opening, the cap on generations is no
    longer a surrender: turn 3's reply went on to answer the question after the
    two recycled sentences, so the recycled part is dropped and the answer served.

**2. "what's going on with your world model?" was routed to hardware telemetry.**
``runtime.status.identity_grounded_chat`` matched at confidence 0.99 — it tested
for the bare word ``model`` (also ``threads``, ``batch``, ``provider``), so any
sentence containing one pre-empted every conversational route below it.
"""
import pytest

from eli.kernel.engine import (
    _RepeatDetected,
    _redact_prior_replies,
    _strip_repeated_opening,
    _stream_holding_back_repeats,
)
from eli.execution.router_enhanced import _RUNTIME_STATUS_RE

# Turn 2, verbatim from the transcript.
PRIOR = (
    "You're not wrong — I'm a bit of a hot mess, but at least I've got the simulation "
    "grid running on autopilot. Sleep deprivation's like a bad software update: it "
    "crashes your system and leaves you wondering if you'll ever reboot. "
    "How's the fallout 3 going?"
)
# Turn 3: the same two sentences, then a genuine answer to what was asked.
RECYCLED_OPENING = (
    "You're not wrong — I'm a bit of a hot mess, but at least I've got the simulation "
    "grid running on autopilot. Sleep deprivation's like a bad software update: it "
    "crashes your system and leaves you wondering if you'll ever reboot. As for the "
    "world model? It's basically a glorified todo list with a few flickering lights "
    "and a lot of existential dread. What's next on your agenda?"
)
ANSWER = ("As for the world model? It's basically a glorified todo list with a few "
          "flickering lights and a lot of existential dread. What's next on your agenda?")


def _drive(text, recent, *, size=7, **kw):
    chunks = [text[i:i + size] for i in range(0, len(text), size)]
    return "".join(_stream_holding_back_repeats(chunks, recent, **kw))


# ── 1. the first attempt still asks for a regeneration ──────────────────────
def test_first_attempt_still_raises_for_a_retry():
    """Salvage is the last resort, not a replacement for regenerating."""
    with pytest.raises(_RepeatDetected):
        _drive(RECYCLED_OPENING, [PRIOR], allow_retry=True)


# ── 2. the last attempt salvages instead of serving the duplicate ───────────
@pytest.mark.parametrize("size", [1, 3, 7, 9, 40, 500])
def test_recycled_opening_is_trimmed_and_the_answer_survives(size):
    """The bug the user saw: the reply led with two sentences he had just read."""
    out = _drive(RECYCLED_OPENING, [PRIOR], size=size, allow_retry=False, salvage=True)
    assert "hot mess" not in out
    assert "bad software update" not in out
    assert out == ANSWER


def test_a_reply_that_is_repeat_all_the_way_down_is_still_served():
    """An honest duplicate beats an empty turn — and beats a stray fragment."""
    out = _drive(PRIOR, [PRIOR], allow_retry=False, salvage=True)
    assert out == PRIOR


def test_salvage_never_touches_a_novel_reply():
    text = ("Agenda's clear. You've got the QMSH grant follow-up and nothing else "
            "booked today, so the morning is yours if you want it.")
    assert _drive(text, [PRIOR], size=5, allow_retry=False, salvage=True) == text


def test_only_the_opening_is_trimmed():
    """A reply that happens to END on something said before keeps its own opening."""
    text = ("Right, the vector index is rebuilt and the count matches what's on disk. "
            "How's the fallout 3 going?")
    assert _drive(text, [PRIOR], size=6, allow_retry=False, salvage=True) == text


def test_short_reply_ending_inside_the_head_buffer_is_delivered():
    assert _drive("Morning.", [PRIOR], allow_retry=False, salvage=True) == "Morning."


def test_salvage_is_opt_in_so_the_old_path_is_unchanged():
    assert _drive(RECYCLED_OPENING, [PRIOR], allow_retry=False) == RECYCLED_OPENING


def test_strip_returns_the_original_substring_not_a_rejoin():
    """Whitespace and line breaks in the surviving remainder must be untouched."""
    body = PRIOR + "\n\nSecond paragraph, entirely new,  with  odd spacing."
    assert _strip_repeated_opening(body, [PRIOR]) == \
        "Second paragraph, entirely new,  with  odd spacing."


# ── 3. the retry prompt no longer contains the reply it must not repeat ─────
def test_prior_reply_is_redacted_from_the_retry_prompt():
    ctx = ("USER PROFILE: prefers direct answers\n"
           + PRIOR
           + "\nGROUNDED FACT: the grant was filed in December 2025")
    out = _redact_prior_replies(ctx, [PRIOR])
    assert PRIOR not in out
    assert "USER PROFILE" in out and "GROUNDED FACT" in out


def test_redaction_leaves_unrelated_evidence_alone():
    ctx = "line one about the QMSH grant\nline two about the Tesla rifle build"
    assert _redact_prior_replies(ctx, [PRIOR]) == ctx


def test_redaction_survives_empty_input():
    assert _redact_prior_replies("", [PRIOR]) == ""
    assert _redact_prior_replies(PRIOR, []) == PRIOR
    assert _redact_prior_replies(PRIOR, [None, ""]) == PRIOR


# ── 4. "world model" is not a hardware question ─────────────────────────────
@pytest.mark.parametrize("asked", [
    "Do you no stay updated, wht's goping on with your world model?",
    "what's going on with your world model",
    "your mental model of me is off",
    "the data model in that schema is wrong",
    "batch the emails for me",
    "I lost the threads of that conversation",
    "how's the model railway coming along",
])
def test_conversational_uses_of_the_word_do_not_hijack_the_route(asked):
    assert not _RUNTIME_STATUS_RE.search(asked), asked


@pytest.mark.parametrize("asked", [
    "what model are you running?",
    "what are you actually running on",
    "which model is loaded",
    "what's your context size",
    "how many gpu layers are you using",
    "what batch size are you on",
    "how many threads",
    "which provider are you on",
    "what is the model path",
])
def test_real_runtime_questions_still_match(asked):
    assert _RUNTIME_STATUS_RE.search(asked), asked
