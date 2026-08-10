"""Locks on the long-question guard measuring the wrong unit, and on the schedule
prepass not recognising yes/no questions.

**1. A request in the final clause was thrown away.** From a live session:

    "Nope, i don't want to be stuck in that loop anymore than you do, broken now
     anyway. What's the morning report?"

20 words, so ``chat.long_question_guard`` fired and returned CHAT at 0.85 — the user
asked for a report and got small-talk. The guard sits above ~300 deterministic keyword
routes and shadows all of them, so its exemption list had been growing one bug at a
time: wallclock questions were carved out earlier for exactly this reason, and the
comment there states the principle generally ("asking completely must not be answered
worse than asking tersely") while the code applied it to one case.

Deferring the guard until after the keyword routes was tried and rejected — the length
heuristic genuinely earns its keep against loose routes. The real error is the unit of
measurement: the guard measures the utterance, but the request lives in a clause. A
long preamble followed by a crisp question now routes on the crisp question, and only
when that clause is short AND yields a confident non-CHAT action.

**2. Yes/no questions were being scheduled.** `_QUESTION_RX` guarded the schedule
prepass against wh-questions only, so "Do you ever get tired of me asking you the same
kinds of questions over and over again every day?" had no wh-word, "every day"
satisfied the future-time pattern, and it became SCHEDULE_TASK at 0.9. The prepass
docstring claimed questions were excluded; for yes/no questions it was not true.
"""
import pytest

from eli.execution.router_enhanced import (
    _QUESTION_RX,
    _trailing_request_clause,
    route,
)


def _action(text):
    return str((route(text) or {}).get("action") or "").upper()


def _via(text):
    return str(((route(text) or {}).get("meta") or {}).get("matched_by") or "")


# ── 1. the trailing clause carries the request ──────────────────────────────
LIVE_CASE = ("Nope, i don't want to be stuck in that loop anymore than you do, "
             "broken now anyway. What's the morning report?")


def test_the_live_case_reaches_the_report_route():
    assert _action(LIVE_CASE) == "MORNING_REPORT"


def test_the_clause_route_is_labelled_so_it_is_traceable_in_logs():
    """A silent rewrite is how the original bug stayed invisible."""
    assert "long_question_clause" in _via(LIVE_CASE)


def test_a_trailing_news_request_also_survives():
    text = "So anyway that whole thing was a mess and I gave up on it. What's the news?"
    assert _action(text) == "NEWS_FETCH"


def test_short_forms_are_unchanged():
    assert _action("morning report") == "MORNING_REPORT"
    assert _action("what's the morning report?") == "MORNING_REPORT"


# ── 2. the guard still does its job ─────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "I was thinking about what you said earlier and I wonder whether you actually enjoy any of this or not?",
    "I've been up since five and my head is pounding and everything hurts. How are you?",
    "Honestly after everything that happened today I am not sure I even want to keep going with this, you know?",
])
def test_long_conversational_questions_still_route_to_chat(text):
    """The guard exists to keep these away from the LLM intent resolver. Losing that
    would trade one misroute class for a worse one."""
    assert _action(text) == "CHAT"


def test_guard_confidence_still_blocks_the_llm_resolver():
    """0.85 is what stops the engine handing it to llm_intent; 0.6 would not."""
    r = route("I was thinking about what you said earlier and I wonder whether you "
              "actually enjoy any of this or not?")
    assert r["confidence"] >= 0.85


def test_wallclock_exemption_still_works():
    """The hand-carved case that motivated the general fix must not regress."""
    assert _action("Eli, what is the date, the day, and what is the time right now please?") == "TIME"


# ── 3. clause extraction is conservative ────────────────────────────────────
def test_single_sentence_has_no_trailing_clause():
    """Nothing to narrow to — the guard must handle it as before."""
    assert _trailing_request_clause("why do you keep doing that to me every single day") == ""


def test_a_rambling_final_clause_is_not_treated_as_a_request():
    text = ("I gave up on it. I really do not understand why any of this keeps "
            "happening to me over and over again?")
    assert _trailing_request_clause(text) == ""


def test_a_short_final_clause_is_extracted():
    assert _trailing_request_clause("Long preamble here. What's the news?") == "What's the news?"


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_clause_extraction_never_raises(bad):
    assert _trailing_request_clause(bad) == ""


def test_clause_routing_does_not_recurse_indefinitely():
    """The guard re-enters route() on the clause; depth must be capped."""
    assert _action("A. " * 30 + "What's the morning report?") in ("MORNING_REPORT", "CHAT")


# ── 4. yes/no questions are not scheduled ───────────────────────────────────
@pytest.mark.parametrize("text", [
    "Do you ever get tired of me asking you the same kinds of questions over and over again every day?",
    "Are you doing anything in the background every day?",
    "Did you run the backup last night?",
    "Have you been checking that every morning?",
])
def test_questions_about_eli_are_not_scheduled(text):
    assert _action(text) != "SCHEDULE_TASK", text


@pytest.mark.parametrize("text", [
    "can you open spotify at 8pm?",
    "could you get the news at 7am?",
    "would you run the backup tonight?",
])
def test_polite_requests_still_schedule(text):
    """"can/could/would you" is a request, not a question about ELI. Rejecting these
    would break scheduling for anyone who asks politely."""
    assert _action(text) == "SCHEDULE_TASK", text


@pytest.mark.parametrize("text", [
    "get a morning report ready for tomorrow",
    "open spotify at 8pm",
    "get the news at 7am",
])
def test_plain_imperatives_still_schedule(text):
    """The three examples the prepass docstring promises."""
    assert _action(text) == "SCHEDULE_TASK", text


def test_question_rx_distinguishes_asking_from_requesting():
    assert _QUESTION_RX.search("Do you ever get tired of this every day?")
    assert _QUESTION_RX.search("what is on tonight?")
    assert not _QUESTION_RX.search("can you open spotify at 8pm?")
    assert not _QUESTION_RX.search("could you get the news at 7am?")
