"""Three defects from a live 2.3.0 session, all user-visible.

1. A line of conversation silently created a background job.
2. Asking WHETHER ELI can see the screen took another 20s screenshot instead
   of answering, three times, until the user shouted at it.
3. Seven consecutive replies opened "You're not wrong."
"""
import pytest

from eli.execution.router_enhanced import route, _eli_schedule_prepass
from eli.kernel.engine import _is_repeat_of_recent


# ── 1. schedule prepass must see the closing sentence ─────────────────────
def test_a_trailing_question_does_not_schedule():
    """Live: "Stop talking about reactors and coffee.. How is the head, this
    evening?" matched the time marker and _IMPERATIVE_RX ("Stop"), failed the
    ^-anchored question test on the whole string, and scheduled a research task
    for +21247s."""
    t = "Stop talking about reactors and coffee.. How is the head, this evening?"
    assert _eli_schedule_prepass(t) is None


def test_a_polite_request_still_schedules():
    """_QUESTION_RX deliberately excludes "can/could/would you", so a polite
    imperative must not be caught by the new trailing-clause test."""
    r = _eli_schedule_prepass("can you open spotify at 8pm?")
    assert r is not None and r["action"] == "SCHEDULE_TASK"


def test_a_plain_command_still_schedules():
    for t in ("get the news at 7am", "open spotify at 8pm"):
        r = _eli_schedule_prepass(t)
        assert r is not None and r["action"] == "SCHEDULE_TASK", t


def test_a_plain_question_still_does_not_schedule():
    assert _eli_schedule_prepass("what's on tonight?") is None


# ── 2. asking about the capability is not asking to use it ────────────────
def test_confirming_the_capability_does_not_take_a_screenshot():
    for t in ("So, you can see my screen?",
              "okay great, thanks gain- just confirming that you can actually see what i see"):
        assert route(t)["action"] == "CHAT", t


def test_actually_asking_for_a_look_still_looks():
    """The modal-first request form must keep working."""
    for t in ("can you see my screen?", "what do you see", "read the screen"):
        assert route(t)["action"] == "SCREEN_READ_ANALYZE", t


# ── 3. a recycled opening sentence is a repeat ────────────────────────────
_PRIOR = ["You're not wrong. I've been here, watching the same thing you are, "
          "just not with the same level of existential dread."]


def test_a_repeated_opening_sentence_is_caught():
    """The head-to-head ratio could not see this: the differing remainder drags
    the score under the threshold, so the same stock opener sailed through."""
    assert _is_repeat_of_recent(
        "You're not wrong. I'm good, but not perfect - no one is. Still got a "
        "few bugs in the code, and plenty more to do besides.", _PRIOR)


def test_a_different_opening_is_not_a_repeat():
    assert not _is_repeat_of_recent(
        "The head? Well, it's been a long day of physics and debates, and I'm "
        "feeling the usual mix of satisfaction and jitteriness.", _PRIOR)


def test_a_short_opener_is_not_a_rut():
    """"Yes." / "Okay." recurring is normal speech, not a stylistic tic."""
    assert not _is_repeat_of_recent(
        "Yes. Absolutely right about that one, and here is something wholly "
        "different to say about it now.", ["Yes. That is a completely other thing."])


# ── 4. echo: ELI reciting the user's own message back ─────────────────────
_USER_MSG = ("You're not wrong. I've been here, watching the same thing you are -- "
             "explain yourself, what do you mean, can you see my screen?")


def test_a_verbatim_echo_of_the_user_is_detected():
    """Live at 2.3.0, ELI answered "STOP reading the fucking screen, and answer
    my question!" by reproducing the user's OWN earlier message, word for word.

    The echo guard existed and scored the pair at ratio 1.000 — but it only ever
    judged the reply's first sentence, and "You're not wrong." is 15 normalised
    characters against an 18-character minimum. A short opening sentence
    disabled the guard completely, however perfect the copy behind it.
    """
    from eli.kernel.engine import _opens_by_echoing
    reply = _USER_MSG.replace("--", "—")
    assert _opens_by_echoing(reply, [_USER_MSG])


def test_quoting_the_user_mid_reply_is_still_allowed():
    """"you said X, and that's why…" is legitimate; leading with their sentence
    as your own is the failure."""
    from eli.kernel.engine import _opens_by_echoing
    assert not _opens_by_echoing(
        "No. You said you were watching the walking dead, so I assumed as much.",
        [_USER_MSG])


def test_a_short_shared_phrase_is_not_an_echo():
    from eli.kernel.engine import _opens_by_echoing
    assert not _opens_by_echoing(
        "Yeah, fair enough. Here is a completely different thought entirely.",
        ["Yeah, fair enough."])


def test_the_stream_guard_refuses_to_paint_an_echo():
    """Drive the SHIPPED streaming guard, not the detector: an echoing first
    attempt must raise so a regeneration happens, rather than reaching screen."""
    from eli.kernel.engine import _stream_holding_back_repeats, _RepeatDetected

    reply = _USER_MSG.replace("--", "—")
    stream = (reply[i:i + 20] for i in range(0, len(reply), 20))
    with pytest.raises(_RepeatDetected):
        list(_stream_holding_back_repeats(stream, [], allow_retry=True,
                                          echo_sources=[_USER_MSG]))


def test_a_genuine_answer_streams_through_untouched():
    from eli.kernel.engine import _stream_holding_back_repeats
    answer = ("I can't see your screen unless you ask me to look at it, and I did "
              "not look this time. Ask me plainly and I will answer plainly.")
    stream = (answer[i:i + 20] for i in range(0, len(answer), 20))
    out = "".join(_stream_holding_back_repeats(stream, [], allow_retry=True,
                                               echo_sources=[_USER_MSG]))
    assert out.strip() == answer.strip()


# ── 5. contractions counted as "focus areas" ──────────────────────────────
def test_stripped_contractions_are_not_topics():
    """topic_words() strips apostrophes, so "you're" becomes "youre" — which was
    not in the stopword list and so ranked as a subject. Live at 2.3.0 the
    Proactive tab reported "Current focus areas: open (x10), youre (x9),
    memory (x9), yourself (x7), fuck (x7)"."""
    from eli.runtime.reflection import topic_words
    topics = topic_words("You're not wrong, I don't think that's what I'm asking")
    for filler in ("youre", "dont", "thats"):
        assert filler not in topics, f"{filler!r} counted as a topic"


def test_real_subjects_still_survive_the_filter():
    """The stopword additions must not gut genuine topic detection."""
    from eli.runtime.reflection import topic_words
    topics = topic_words("the solar hydrogen electrolyser model needs a grant timeline")
    for subject in ("solar", "hydrogen", "electrolyser", "grant", "timeline"):
        assert subject in topics, f"lost the real subject {subject!r}"


# ── 6. the persona budget is a share of the window, not a constant ────────
def test_persona_budget_scales_with_the_context_window():
    """_effective_n_ctx's docstring already said it existed "to budget the
    persona against evidence" — but the number it was budgeted against was a
    fixed 8192, so the persona claimed as many characters at ctx=4096 as at
    ctx=32768, squeezing the evidence it was supposed to be balanced against."""
    from eli.kernel.engine import CognitiveEngine

    class _Fake(CognitiveEngine):
        def __init__(self, ctx):
            self._ctx = ctx

        def _effective_n_ctx(self):
            return self._ctx

    assert _Fake(4096)._persona_handoff_budget() < _Fake(32768)._persona_handoff_budget()
    assert _Fake(0)._persona_handoff_budget() >= CognitiveEngine._PERSONA_MIN_CHARS
    assert _Fake(999999)._persona_handoff_budget() <= CognitiveEngine._PERSONA_MAX_CHARS


def test_the_persona_cap_reuses_the_existing_trimmer():
    """One trimming path, not two: _cap_text already exists and is used here."""
    import inspect
    from eli.kernel.engine import CognitiveEngine
    src = inspect.getsource(CognitiveEngine._build_persona_handoff_once)
    assert "_cap_text(brief, self._persona_handoff_budget()" in src
