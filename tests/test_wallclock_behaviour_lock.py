"""Behaviour lock: ELI can always read its own clock, and never fakes a place.

Every case here is taken from a real session in which ELI told the user it had
"no access to your system clock" moments after printing the time, and answered
"what time is it in Shimla?" with the Irish local time.

Two defects produced that. Both are locked shut here:

* ``chat.long_question_guard`` diverted any 12+ word question to CHAT before the
  TIME/DATE routes ran. In CHAT the model has no clock in context, so it
  truthfully denied having one — asking completely got a worse answer than
  asking tersely.
* The TIME effector never received the phrasing, so it could not tell "the time"
  from "the day and the time" and could not see a named place at all.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from eli.core.worldclock import describe, parse_request, resolve_zone
from eli.execution import router_enhanced as router
from eli.execution.executor_enhanced import _execute_impl


def _answer(text: str) -> tuple[str, str]:
    """Route ``text`` and, for clock actions, execute it. Returns (action, reply)."""
    out = router.route(text)
    action = str(out.get("action") or "")
    if action not in {"TIME", "DATE", "GET_TIME", "GET_DATE"}:
        return action, ""
    result = _execute_impl(action, out.get("args") or {})
    return action, str(result.get("response") or "")


# --------------------------------------------------------------------------
# The clock is always readable, at any question length
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "what is the time",
    "what time is it?",
    "what is the date",
    "and what is the day?",
    "day and time?",
    "i said the day AND time",
    # 12+ words: these are the ones that used to be refused outright.
    "Eli, what is the date, the day, and what is the time?",
    "i want to know what the fucking time is, and what day it is?!",
    "what do you mean 00:00 ? do you know what time it is?",
    "please could you kindly tell me what the time is right now because I need to know?",
])
def test_clock_questions_reach_the_clock_at_any_length(text):
    action, reply = _answer(text)
    assert action in {"TIME", "DATE"}, f"{text!r} escaped the clock routes -> {action}"
    assert reply.strip(), f"{text!r} produced an empty clock answer"


def test_long_clock_question_is_not_diverted_to_chat():
    """The exact question that drew 'I cannot provide the current date … or time'."""
    text = "Eli, what is the date, the day, and what is the time?"
    assert len(text.lower().split()) >= 12, "case must stay above the guard threshold"
    action, reply = _answer(text)
    assert action == "TIME"
    now = datetime.now().astimezone()
    assert now.strftime("%A") in reply and now.strftime("%H:%M") in reply


# --------------------------------------------------------------------------
# The answer matches what was actually asked
# --------------------------------------------------------------------------

def test_time_only_question_gets_time_only():
    _, reply = _answer("what is the time")
    assert datetime.now().astimezone().strftime("%H:%M") in reply
    assert datetime.now().astimezone().strftime("%B") not in reply, (
        "a bare time question must not dump the full date"
    )


def test_date_only_question_gets_date_only():
    _, reply = _answer("what is the date")
    now = datetime.now().astimezone()
    assert now.strftime("%A") in reply and str(now.day) in reply


def test_compound_question_gets_both_day_and_time():
    _, reply = _answer("day and time?")
    now = datetime.now().astimezone()
    assert now.strftime("%A") in reply and now.strftime("%H:%M") in reply


# --------------------------------------------------------------------------
# A named place is honoured, or declined — never silently ignored
# --------------------------------------------------------------------------

def test_named_place_is_answered_in_that_places_timezone():
    _, reply = _answer("what time is it now in Shimla?")
    expected = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M")
    assert expected in reply, f"Shimla should read {expected}, got {reply!r}"
    assert "Asia/Kolkata" in reply


def test_named_place_does_not_fall_back_to_local_time():
    """The original bug: 'in Shimla' answered with the Irish wall clock."""
    _, reply = _answer("what time is it now in Shimla?")
    local = datetime.now().astimezone()
    shimla = datetime.now(ZoneInfo("Asia/Kolkata"))
    if local.utcoffset() != shimla.utcoffset():
        assert local.strftime("%H:%M") not in reply


@pytest.mark.parametrize("text,zone", [
    ("What is the time in shimla, india?", "Asia/Kolkata"),
    ("what time is it now in Wexford?", "Europe/Dublin"),
    ("what is the current day/date, and current time in ireland?", "Europe/Dublin"),
    ("what time is it in Tokyo?", "Asia/Tokyo"),
    ("what time is it in New York?", "America/New_York"),
])
def test_places_resolve_to_the_right_zone(text, zone):
    _, reply = _answer(text)
    assert zone in reply, f"{text!r} -> {reply!r}"
    assert datetime.now(ZoneInfo(zone)).strftime("%H:%M") in reply


def test_unknown_place_is_declined_not_guessed():
    reply = describe("what time is it in Blahvillebergen?")
    assert "Blahvillebergen" in reply
    assert datetime.now().astimezone().strftime("%H:%M") not in reply


def test_multi_zone_region_asks_which_city():
    reply = describe("what time is it in the USA?")
    assert "several time zones" in reply


def test_non_places_are_not_treated_as_places():
    assert parse_request("what time is it in the morning",
                         default_date=False, default_time=True).place is None
    assert resolve_zone("the morning") is None


# --------------------------------------------------------------------------
# Guards that must survive the above
# --------------------------------------------------------------------------

def test_remark_about_having_asked_is_not_a_clock_request():
    action, _ = _answer(
        "yeah that's fair enough i have asked you what the date and time is quite a bit lately"
    )
    assert action == "CHAT"


def test_best_time_to_call_is_not_a_clock_request():
    action, _ = _answer("what is the best time to call you?")
    assert action == "CHAT"


def test_file_command_containing_todays_date_is_not_a_clock_request():
    action, _ = _answer("create a file called ~/notes.txt containing today's date")
    assert action not in {"TIME", "DATE"}


# --------------------------------------------------------------------------
# Wellbeing / behaviour questions are conversation, not a database dump
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "but you do not seem to be processing the questions properly without hand-holding, "
    "you sure you are okay?",
    "why are you processing that so slowly",
    "are you processing this correctly?",
    "you keep processing my request wrong",
    "i just want to know what is going on with you because the conversation is not "
    "completely coherent",
])
def test_behaviour_complaints_do_not_trigger_a_memory_inventory(text):
    """'processing' sat in both halves of a two-signal AND, collapsing the gate."""
    assert str(router.route(text).get("action")) == "CHAT", f"{text!r} dumped memory stats"


@pytest.mark.parametrize("text", [
    "what memories have you been processing",
    "what have you been remembering lately",
    "show me recent memories",
])
def test_real_memory_questions_still_reach_the_grounded_report(text):
    assert str(router.route(text).get("action")) == "MEMORY_STATUS"
