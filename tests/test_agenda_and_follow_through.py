"""ELI does what it is asked: a calendar and reminders that exist, and a "yes" that acts.

Live 2026-10-05, on a 7B model: the user mentioned a presentation at 7.30pm. ELI offered to
"check your calendar" (ADD_EVENT and LIST_EVENTS were stubs that answered "Calendar integration
is not configured" as a success), did nothing on "yes please", "I said yes already" or "YES! DO
1-3", ran ADD_EVENT on one of its own sentences, and reported the stub's reply as "No events are
scheduled according to your calendar".
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from eli.kernel import request_context as rc
from eli.runtime import agenda as ag
from eli.runtime import pending_proposal as pp

NOW = datetime(2026, 10, 5, 9, 5)  # the Monday morning of the session
SAID = "I thought i had a presentation at 10am for RAIMS, but it is not until 7.30pm haha"


@pytest.fixture()
def agenda(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_AGENDA_DB", str(tmp_path / "agenda.sqlite3"))
    monkeypatch.setenv("ELI_CALENDAR_FILE", str(tmp_path / "calendar.ics"))
    monkeypatch.setattr("eli.kernel.state.get_active_user_id", lambda *a, **k: "owner")
    delivered = []
    ag.set_delivery(lambda item, missed: delivered.append((item["title"], missed)))
    yield SimpleNamespace(delivered=delivered, ics=tmp_path / "calendar.ics")
    ag.set_delivery(None)


class _HeldClock:
    """`time` with the clock held at NOW."""

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return NOW.timestamp()


class _HeldDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(NOW.year, NOW.month, NOW.day, NOW.hour, NOW.minute)


@pytest.fixture()
def monday(agenda, monkeypatch):
    """The calendar's own clock held at NOW, for tests that pass now=NOW. The store asks the
    clock whether a reminder is still to come; on the real one these passed only on that
    Monday, before 19:00."""
    monkeypatch.setattr(ag, "time", _HeldClock())
    monkeypatch.setattr(ag, "datetime", _HeldDatetime)
    yield agenda


@pytest.fixture()
def proposals(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "_path", lambda: tmp_path / "pending_proposal.json")
    yield


# ── reading a day and a time out of ordinary words ───────────────────────────

@pytest.mark.parametrize("text,when,title", [
    (SAID, "today (Mon 5 Oct) at 19:30", "RAIMS presentation"),
    ("add an event tomorrow at 3pm", "tomorrow (Tue 6 Oct) at 15:00", ""),
    ("add dentist appointment on friday at 2:30pm to my calendar", "Fri 9 Oct at 14:30", "Dentist appointment"),
    ("put the RAIMS presentation in my calendar for 7.30pm today", "today (Mon 5 Oct) at 19:30", "RAIMS presentation"),
    ("remind me at 4pm to prepare for the presentation", "today (Mon 5 Oct) at 16:00", "Prepare for the presentation"),
    ("remind me in 20 minutes to check the oven", "today (Mon 5 Oct) at 09:25", "Check the oven"),
    ("remind me tomorrow morning to call mum", "tomorrow (Tue 6 Oct) at 09:00", "Call mum"),
    ("schedule a meeting with Dr Smith on 12 October at 11", "Mon 12 Oct at 11:00", "Meeting with Dr Smith"),
    ("lunch with Sarah next tuesday at half 1", "tomorrow (Tue 6 Oct) at 13:30", "Lunch with Sarah"),
    ("add my flight on 2026-11-03 at 06:45", "Tue 3 Nov at 06:45", "Flight"),
    ("remind me to take the bins out tonight", "today (Mon 5 Oct) at 20:00", "Take the bins out"),
    ("call the bank at 8", "today (Mon 5 Oct) at 20:00", "Call the bank"),
    ("add team stand-up every monday at 9", "Mon 12 Oct at 09:00", "Team stand-up"),
    ("book a table for dinner with Aoife on saturday at 8pm", "Sat 10 Oct at 20:00", "Dinner with Aoife"),
    ("add 'Board review' to my calendar for friday 3pm", "Fri 9 Oct at 15:00", "Board review"),
])
def test_a_day_a_time_and_a_title_are_read_from_the_sentence(text, when, title):
    parsed = ag.parse_when(text, NOW)
    assert parsed is not None
    assert ag.describe(parsed.start.timestamp(), NOW, has_time=parsed.has_time) == when
    assert ag.title_from(text, parsed) == title


def test_a_date_with_no_time_is_an_all_day_event():
    parsed = ag.parse_when("birthday party on the 14th of november", NOW)
    assert not parsed.has_time and ag.describe(parsed.start.timestamp(), NOW, has_time=False) == "Sat 14 Nov, all day"
    assert ag.title_from("birthday party on the 14th of november", parsed) == "Birthday party"


@pytest.mark.parametrize("text", ["add it to my calendar", "what version is 7.30 of the app", "how are you", "the score was 3.15"])
def test_a_sentence_that_names_no_time_gives_none(text):
    assert ag.parse_when(text, NOW) is None


# ── the calendar and reminders are real ──────────────────────────────────────

def test_an_event_is_added_listed_and_written_to_a_calendar_file(agenda, monday):
    out = ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    assert out["ok"] and out["content"] == ("Added to your calendar: RAIMS presentation, today (Mon 5 Oct) at 19:30. "
                                            "I'll remind you at 19:00 and 19:30.")
    listed = ag.do_list_events({"text": "what's on today"}, now=NOW)
    assert listed["content"] == "On your calendar today:\n- today (Mon 5 Oct) at 19:30: RAIMS presentation"
    ics = agenda.ics.read_text()
    assert "BEGIN:VEVENT" in ics and "SUMMARY:RAIMS presentation" in ics and "DTSTART:20261005T" in ics
    again = ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    assert again["content"].startswith("That is already on your calendar")


def test_an_empty_calendar_says_so_and_nothing_is_ever_not_configured(agenda, monday):
    assert ag.do_list_events({"text": "check my calendar"}, now=NOW)["content"] == "Nothing on your calendar in the next 7 days."
    from eli.execution import executor_enhanced as ex
    for action in ("LIST_EVENTS", "ADD_EVENT"):
        out = ex.execute(action, {"text": "dentist tomorrow at 3pm"})
        assert "not configured" not in out["content"].lower()


def test_add_it_takes_the_event_from_what_the_user_just_said(agenda, monday):
    out = ag.do_add_event({"text": "You add it!", "from_context": True}, earlier=["YES! DO 1-3", "yes please", SAID], now=NOW)
    assert out["ok"] and "RAIMS presentation, today (Mon 5 Oct) at 19:30" in out["content"]


def test_with_nothing_to_go_on_it_asks_when_and_does_not_invent(agenda, monday):
    out = ag.do_add_event({"text": "add it to my calendar"}, earlier=["how are you"], now=NOW)
    assert not out["ok"] and out["error"] == "need_time" and "When is it?" in out["content"]
    past = ag.do_add_event({"text": "add standup today at 8am to my calendar"}, now=NOW)
    assert not past["ok"] and past["error"] == "in_the_past"


def test_a_reminder_has_a_label_and_is_delivered_when_due(agenda):
    out = ag.do_remind({"text": "remind me in 20 minutes to check the oven"}, now=datetime.now())
    assert out["ok"] and out["content"].endswith(": Check the oven.")
    assert ag.fire_due() == []                                  # not yet
    fired = ag.fire_due(time.time() + 21 * 60)
    assert [f["title"] for f in fired] == ["Check the oven"] and agenda.delivered == [("Check the oven", False)]
    assert ag.fire_due(time.time() + 22 * 60) == []             # once


def test_a_reminder_that_came_due_while_eli_was_shut_is_still_delivered(agenda):
    ag.add_reminder("Take the bins out", time.time() - 3600)
    ag.add_reminder("Ancient", time.time() - 3 * 86400)
    ag.fire_due()
    assert agenda.delivered == [("Take the bins out", True)]    # late, and said to be; the 3-day-old one is dropped


def test_a_reminder_without_a_subject_takes_the_event_it_is_for(agenda, monday):
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    out = ag.do_remind({"text": "Set reminders for 4 PM today (5 hours before the presentation) to alert you about "
                                "the upcoming meeting"}, now=NOW)
    assert out["content"] == "Reminder set for today (Mon 5 Oct) at 16:00: RAIMS presentation at 19:30."
    ask = ag.do_remind({"text": "remind me to stretch"}, now=NOW)
    assert not ask["ok"] and "When should I remind you?" in ask["content"]


def test_an_alarm_is_kept_in_the_agenda_not_in_a_sleeping_thread(agenda):
    from eli.execution import executor_enhanced as ex
    out = ex.execute("SET_ALARM", {"time": "23:59"})
    assert out["ok"] and out["content"].startswith("Alarm set for 23:59")
    rows = ag.between(time.time(), time.time() + 2 * 86400, kinds=("reminder",))
    assert [r["title"] for r in rows] == ["Alarm (23:59)"]


def test_one_users_calendar_is_not_shown_to_another(agenda):
    ag.add_event("Board meeting", time.time() + 3600, user_id="owner")
    assert ag.between(time.time(), time.time() + 86400, user_id="owner")
    assert ag.between(time.time(), time.time() + 86400, user_id="guest") == []


def test_cancelling_an_event_takes_its_reminders_with_it(agenda):
    ev = ag.add_event("Dentist", time.time() + 7200)
    assert len(ag.between(time.time(), time.time() + 86400, own_reminders_only=False)) == 3
    assert [g["title"] for g in ag.cancel([ev["id"]])] == ["Dentist"]
    assert ag.between(time.time(), time.time() + 86400, own_reminders_only=False) == []
    assert "Dentist" not in agenda.ics.read_text()


# ── routing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,action", [
    ("add the RAIMS presentation at 7.30pm today to my calendar", "ADD_EVENT"),
    ("put dentist on friday at 2pm in my calendar", "ADD_EVENT"),
    ("schedule a call with Tom tomorrow at 10am", "ADD_EVENT"),
    ("You add it!", "ADD_EVENT"),
    ("add it to my calendar", "ADD_EVENT"),
    ("remind me at 4pm to prepare for the presentation", "SET_ALARM"),
    ("remind me in 20 minutes to check the oven", "SET_ALARM"),
    ("set a reminder for 4pm", "SET_ALARM"),
    ("what's on my calendar today", "LIST_EVENTS"),
    ("check my calendar", "LIST_EVENTS"),
    ("do i have anything on tomorrow", "LIST_EVENTS"),
    ("show my reminders", "LIST_EVENTS"),
    ("did you add it to my calendar?", "LIST_EVENTS"),
    ("what is my schedule tomorrow", "LIST_EVENTS"),
])
def test_calendar_and_reminder_requests_reach_the_right_action(text, action):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] == action


@pytest.mark.parametrize("text", [
    "what a boring meeting that was", "i missed my appointment", "what events led to the first world war",
    "what's on tv tonight", "remind me what we talked about yesterday", "add milk to my shopping list",
    "i have a meeting at 3pm tomorrow with the bank", "have you added anything to the report",
])
def test_a_sentence_that_only_mentions_a_meeting_is_not_a_calendar_command(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] not in ("ADD_EVENT", "LIST_EVENTS", "SET_ALARM")


def test_other_timed_requests_keep_their_own_actions():
    from eli.execution.router_enhanced import route
    assert route("research solar inverters overnight")["action"] == "SCHEDULE_TASK"
    assert route("open spotify at 8pm")["action"] == "SCHEDULE_TASK"
    assert route("set a timer for 10 minutes")["action"] == "SET_TIMER"
    assert route("set an alarm for 7am")["action"] == "SET_ALARM"


def test_elis_own_sentence_about_checking_the_calendar_is_a_read_not_an_add():
    """It contains "scheduled"; the old rule matched "schedule" and ran ADD_EVENT."""
    from eli.execution.router_enhanced import route
    got = route("Let's check your calendar for any scheduled events around 10 AM and 7:30 PM today")
    assert got["action"] == "LIST_EVENTS"


# ── "yes" acts on what was offered ───────────────────────────────────────────

REPLY_WITH_STEPS = (
    "Yes. Let's proceed.\n\n1. **Review and Prepare**:\n   - Ensure all materials for the presentation are complete.\n"
    "2. **Schedule Check**:\n   - Double-check your calendar to ensure no other meetings conflict with this new time slot.\n"
    "3. **Notifications**:\n   - Set reminders for 4 PM today (5 hours before the presentation) to alert you about the "
    "upcoming meeting.\n   - Consider setting another reminder at 6:00 PM as a final check-in point.\n\n"
    "Would you like me to help you set up these reminders or take any other actions?")


@pytest.mark.parametrize("text,consent", [
    ("yes please", True), ("I said yes already", True), ("YES! DO 1-3", True), ("do it", True), ("ok", True),
    ("go ahead with all of them", True), ("yes do 2 and 3", True), ("sure, the second one", True),
    ("yes please dig into the timestamps", False), ("no thanks", False), ("yes but not the reminders", False),
    ("ok what time is it", False), ("yes, 4pm works", False), ("You add it!", False),
])
def test_consent_is_agreement_with_nothing_new_asked(text, consent):
    assert pp.is_consent(text) is consent


def test_only_steps_eli_has_an_action_for_are_kept_each_with_its_number():
    items = pp.actionable_items(REPLY_WITH_STEPS)
    assert [(i["n"], i["action"]) for i in items] == [(2, "LIST_EVENTS"), (3, "SET_ALARM"), (3, "SET_ALARM")]
    assert pp.commands_for({"items": items}, "yes do 3") == [i["command"] for i in items[1:]]
    assert len(pp.commands_for({"items": items}, "YES! DO 1-3")) == 3
    assert pp.actionable_items("I can appreciate the absurdity of existence. It is 9:05. Let me know if you need anything.") == []
    assert pp.actionable_items("Would you like me to proceed with these checks now?") == []


def test_what_an_action_reports_is_not_an_offer():
    said = "Added to your calendar: RAIMS presentation, today at 19:30. I'll remind you at 19:00 and 19:30."
    assert pp.actionable_items(said, offers_only=True) == []


def test_yes_runs_the_offer_and_do_1_3_runs_the_listed_steps(proposals):
    from eli.execution.router_enhanced import route
    pp.set_pending_proposal("check your calendar for any recent updates", from_reply=True)
    got = route("yes please")
    assert got["action"] == "LIST_EVENTS" and got["meta"]["matched_by"] == "pending_proposal.confirm"
    assert pp.get_pending_proposal() is None

    items = pp.actionable_items(REPLY_WITH_STEPS)
    pp.set_pending_proposal(items[0]["command"], items=items, from_reply=True)
    got = route("YES! DO 1-3")
    assert got["action"] == "MULTI_COMMAND" and len(got["args"]["commands"]) == 3 and got["args"]["results_only"]

    pp.set_pending_proposal("check your calendar", from_reply=True)
    assert route("I said yes already")["action"] == "LIST_EVENTS"   # five words used to be "a new request"

    pp.set_pending_proposal("check your calendar", from_reply=True)
    assert route("yes please dig into the timestamps")["action"] != "LIST_EVENTS"   # a new request, not consent


def test_a_message_is_routed_once_a_turn_so_a_yes_is_not_spent_on_a_probe(proposals, monkeypatch):
    """A middleware check routed every message to ask "is this a runtime-status question?" and
    threw the answer away. That first call consumed the offer; the real one found nothing."""
    from eli.kernel import engine as E
    calls = []
    monkeypatch.setattr(E, "route_intent", lambda text: calls.append(text) or {"action": "LIST_EVENTS", "args": {}})
    token = rc.turn_facts_var.set({"user_input": "yes please"})
    try:
        first, second = E._route_once("yes please"), E._route_once("yes please")
    finally:
        rc.turn_facts_var.reset(token)
    assert calls == ["yes please"] and first == second and first is not second


def test_an_action_that_asks_for_confirmation_keeps_its_own_offer(proposals):
    token = rc.turn_facts_var.set({"user_input": "forget the harbour document"})
    try:
        pp.set_pending_proposal("confirm forget documents 3", summary="forget documents")
        assert rc.turn_facts_var.get()["proposal_set_by_action"] is True
    finally:
        rc.turn_facts_var.reset(token)


# ── ELI's own words are not commands ─────────────────────────────────────────

@pytest.mark.parametrize("action,user,clause,runs", [
    ("LIST_EVENTS", "YES! DO 1-3", "Let's check your calendar for any scheduled events", True),     # a read
    ("NEWS_FETCH", "anything happening?", "let me check the latest news", True),
    ("ADD_EVENT", "YES! DO 1-3", "Let's check your calendar for any scheduled events", False),      # a write nobody asked for
    ("PLAY_MEDIA", "can you put some jazz on", "Sure, let me play some jazz", True),                # asked for
    ("PLAY_MEDIA", "how was your day", "let me play some jazz", False),
    ("SHELL_EXEC", "run the cleanup command", "let me run the cleanup command", False),             # never from ELI's words
    ("CHAT", "anything", "let's delve into the details", False),
    ("", "anything", "let's delve into the details", False),
])
def test_follow_through_runs_reads_and_what_the_user_asked_for(action, user, clause, runs):
    from eli.kernel.engine import _followthrough_may_run
    assert _followthrough_may_run(action, user, clause) is runs


def test_a_sentence_with_no_action_behind_it_costs_no_second_generation(monkeypatch):
    from eli.kernel.engine import CognitiveEngine
    ran = []
    me = SimpleNamespace(_in_followthrough=False, process=lambda *a, **k: ran.append(a) or "x",
                         _agenda_offer=lambda *a, **k: "", _store_followthrough_reply=lambda *a, **k: None)
    monkeypatch.setattr("eli.kernel.engine.route_intent", lambda text: {"action": "CHAT"})
    out = list(CognitiveEngine._stream_with_followthrough(me, iter(["Yes, let's delve into the specifics. Let's verify the schedule."]),
                                                          "yes please"))
    assert ran == [] and me._in_followthrough is False and out[0].startswith("Yes")


def test_an_action_run_from_the_dag_pool_is_recorded_on_the_turn():
    """The pool's threads started with an empty context: what ran there was missing from the
    audit row and carried no user id."""
    from eli.core.dag import Orchestrator, Task
    facts = {"user_input": "x"}
    token = rc.turn_facts_var.set(facts)
    try:
        def step(ctx):
            rc.turn_facts_var.get().setdefault("executed_actions", []).append("ADD_EVENT")
            return 1
        Orchestrator(max_workers=2).run([Task(id="a", run=step, timeout=5), Task(id="b", run=step, timeout=5)], context={})
    finally:
        rc.turn_facts_var.reset(token)
    assert facts.get("executed_actions") == ["ADD_EVENT", "ADD_EVENT"]


# ── results are shown as they are ────────────────────────────────────────────

def test_calendar_and_timer_results_are_never_handed_to_the_model_to_reword():
    import inspect
    from eli.kernel import engine as E
    for action in ("ADD_EVENT", "LIST_EVENTS", "SET_ALARM", "SET_TIMER", "MULTI_COMMAND", "MEMORY_FORGET"):
        assert action in E._DIRECT_RESULT_ACTIONS
    src = inspect.getsource(E.CognitiveEngine._process_impl)
    assert src.count("_shown_as_is(action, reasoning_mode)") >= 2          # both paths that return an action's result
    assert "_deterministic_direct_payload_actions = _DIRECT_RESULT_ACTIONS" in src


def test_agreed_steps_report_their_outcomes_not_elis_sentences_back(agenda, monkeypatch):
    from eli.execution import executor_enhanced as ex
    monkeypatch.setattr("eli.execution.command_dependency_graph.infer_dependencies",
                        lambda *a, **k: pytest.fail("no model call to order steps the user agreed to"))
    out = ex.execute("MULTI_COMMAND", {"commands": ["check my calendar", "remind me in 30 minutes to stretch"],
                                       "raw": "x", "results_only": True})
    assert out["ok"] and out["content"].startswith("Nothing on your calendar in the next 7 days.\nReminder set for")
    assert "check my calendar" not in out["content"]


# ── noticing an event the user mentions ──────────────────────────────────────

def test_an_event_the_user_mentions_is_offered_once_and_yes_adds_it(agenda, monday):
    found = ag.mentioned_event([SAID], now=NOW)
    assert found["title"] == "RAIMS presentation"
    assert found["sentence"] == ("Want me to put RAIMS presentation in your calendar for today (Mon 5 Oct) at 19:30, "
                                 "and remind you before it?")
    from eli.execution.router_enhanced import route
    routed = route(found["command"])
    assert routed["action"] == "ADD_EVENT"
    added = ag.do_add_event(routed["args"], now=NOW)
    assert "RAIMS presentation, today (Mon 5 Oct) at 19:30" in added["content"]
    assert ag.mentioned_event([SAID], now=NOW) is None          # it is on the calendar now


@pytest.mark.parametrize("text", [
    "when is my presentation?", "that meeting yesterday was awful", "i love a good dinner",
    "the meeting is at 3", "how long is the flight at 6am?",
])
def test_talk_that_is_not_a_plan_gets_no_offer(agenda, monday, text):
    assert ag.mentioned_event([text], now=NOW) is None


def test_listing_an_empty_calendar_points_out_what_was_just_mentioned(agenda, monday):
    out = ag.do_list_events({"text": "check my calendar"}, earlier=[SAID], now=NOW)
    assert out["content"].startswith("Nothing on your calendar in the next 7 days.\n\nYou mentioned RAIMS presentation")
    assert out["offer"].startswith('add "RAIMS presentation" on 2026-10-05 at 19:30')


# ── clock arithmetic is done for the model ───────────────────────────────────

def test_times_the_user_names_are_worked_out_against_the_clock():
    """Live at 09:06: "The original meeting at 10 AM has passed." """
    from eli.cognition.evidence_format import time_facts
    now = datetime(2026, 10, 5, 9, 6).timestamp()
    assert time_facts(SAID, now) == ("TIME FACTS (worked out from the clock; use these, do not recompute): "
                                     "10am = 10:00 today, 54 min from now; 7.30pm = 19:30 today, 10 h 24 min from now. "
                                     "It is now 09:06.")
    assert "8am = 08:00 today, 1 h 6 min ago" in time_facts("the call was at 8am", now)
    assert time_facts("how are you", now) == ""
    from eli.kernel.engine import _date_facts_line
    assert "TIME FACTS" in _date_facts_line("earlier turns\n\nYou: is 7.30pm too late for dinner")


# ── changing and removing what is on the calendar ────────────────────────────

def test_i_meant_8pm_moves_the_event_just_added_and_its_reminders(agenda, monday):
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    out = ag.do_add_event({"text": "cancel that, i meant 8pm", "move": True}, now=NOW)
    assert out["content"] == "Moved RAIMS presentation to today (Mon 5 Oct) at 20:00. I'll remind you at 19:30 and 20:00."
    listed = ag.do_list_events({"text": "what's on today"}, now=NOW)["content"]
    assert listed == "On your calendar today:\n- today (Mon 5 Oct) at 20:00: RAIMS presentation"
    day_end = NOW.replace(hour=23, minute=59).timestamp()
    times = [datetime.fromtimestamp(r["start_ts"]).strftime("%H:%M")
             for r in ag.between(NOW.timestamp(), day_end, kinds=("reminder",), own_reminders_only=False)]
    assert times == ["19:30", "20:00"]                       # the 19:00 one went with the old time


def test_an_event_can_be_moved_by_name_to_another_day_keeping_its_time(agenda, monday):
    ag.do_add_event({"text": "add dentist appointment on friday at 2:30pm to my calendar"}, now=NOW)
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    out = ag.do_add_event({"text": "move the dentist to next monday", "move": True}, now=NOW)
    assert out["content"].startswith("Moved Dentist appointment to Mon 12 Oct at 14:30.")


def test_a_correction_with_nothing_to_move_is_read_as_a_new_event(agenda, monday):
    out = ag.do_add_event({"text": "i meant 8pm", "move": True}, earlier=[SAID], now=NOW)
    assert out["ok"] and out["content"].startswith("Added to your calendar: RAIMS presentation, today (Mon 5 Oct) at 20:00")


def test_an_entry_is_removed_by_name_and_an_unclear_request_asks_which(agenda, monday):
    ag.do_add_event({"text": "add dentist appointment on friday at 2:30pm to my calendar"}, now=NOW)
    ag.do_add_event({"text": "add dentist check-up on 20 October at 10am to my calendar"}, now=NOW)
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    unclear = ag.do_remove({"text": "cancel the dentist"}, now=NOW)
    assert not unclear["ok"] and unclear["error"] == "ambiguous"
    assert unclear["content"].splitlines()[1:] == ["1. Fri 9 Oct at 14:30: Dentist appointment",
                                                   "2. Tue 20 Oct at 10:00: Dentist check-up"]
    gone = ag.do_remove({"text": "cancel the RAIMS presentation"}, now=NOW)
    assert gone["ok"] and gone["content"] == "Removed from your calendar: RAIMS presentation, today (Mon 5 Oct) at 19:30."
    assert "RAIMS" not in ag.do_list_events({"text": "what's on this week"}, now=NOW)["content"]
    missing = ag.do_remove({"text": "cancel the yoga class"}, now=NOW)
    assert not missing["ok"] and missing["error"] == "not_found"


def test_clearing_reminders_leaves_events_alone(agenda, monday):
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    ag.do_remind({"text": "remind me at 4pm to go over my slides"}, now=NOW)
    ag.do_remind({"text": "remind me tomorrow morning to call mum"}, now=NOW)
    out = ag.do_remove({"text": "clear my reminders"}, now=NOW)
    assert out["ok"] and out["content"].startswith("Cleared 2:")
    assert "RAIMS presentation" in ag.do_list_events({"text": "what's on today"}, now=NOW)["content"]


@pytest.mark.parametrize("text,action,move", [
    ("cancel the dentist appointment", "REMOVE_EVENT", False),
    ("delete the RAIMS presentation from my calendar", "REMOVE_EVENT", False),
    ("clear my reminders", "REMOVE_EVENT", False),
    ("cancel that, i meant 8pm", "ADD_EVENT", True),
    ("move the dentist to friday at 3pm", "ADD_EVENT", True),
    ("actually, it's at 8", "ADD_EVENT", True),
])
def test_cancel_and_move_requests_are_routed(text, action, move):
    from eli.execution.router_enhanced import route
    got = route(text)
    assert got["action"] == action and bool(got["args"].get("move")) is move


@pytest.mark.parametrize("text", ["cancel that", "cancel my netflix subscription", "cancel the timer",
                                  "remove the meeting notes file", "i meant the other one", "delete the file report.txt"])
def test_other_things_to_cancel_are_left_alone(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] not in ("REMOVE_EVENT", "ADD_EVENT")


def test_removing_an_event_is_never_the_models_guess():
    from eli.cognition.llm_intent import _EXPLICIT_ONLY_ACTIONS, _catalogue
    assert "REMOVE_EVENT" in _EXPLICIT_ONLY_ACTIONS and "REMOVE_EVENT" not in _catalogue()


# ── the calendar is known on every turn, and never looked for on the web ─────

def test_what_is_coming_up_is_in_the_prompt_with_how_far_off_it_is(agenda, monday):
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    line = ag.prompt_line(now=NOW)
    assert line.startswith("ON THE USER'S CALENDAR") and "today (Mon 5 Oct) at 19:30: RAIMS presentation, in 10 h 25 min" in line
    assert ag.prompt_line(now=NOW + timedelta(days=3)) == ""


def test_a_question_about_the_clock_or_the_calendar_is_never_web_searched(agenda, monkeypatch):
    from eli.runtime import grounding_escalation as ge
    ag.add_event("RAIMS presentation", time.time() + 3600)
    ran = []
    monkeypatch.setattr("eli.core.config.network_allowed", lambda *a, **k: True)
    monkeypatch.setattr("eli.execution.executor_enhanced.execute", lambda action, *a, **k: ran.append(action) or {})
    bus = SimpleNamespace(grounding_confidence=0.1, aggregated_confidence=0.1)
    for text in ("what time is it and how long until the presentation?", "is my calendar free tomorrow afternoon",
                 "how long until the raims thing"):
        assert ge.escalate(SimpleNamespace(), text, {"action": "CHAT"}, bus, reasoning_mode="quick") is None
    assert ran == []


def test_a_compound_time_question_is_not_answered_with_the_clock_alone():
    from eli.execution.router_enhanced import route
    assert route("what time is it and how long until the presentation?")["action"] != "TIME"
    assert route("what time is it")["action"] == "TIME"


# ── results reach the user as they are ───────────────────────────────────────

@pytest.mark.parametrize("action,mode,as_is", [
    ("ADD_EVENT", "quick", True), ("ADD_EVENT", "chain_of_thought", True), ("SET_TIMER", "research", True),
    ("LIST_EVENTS", "expert", True), ("MEMORY_STATUS", "quick", True), ("MEMORY_STATUS", "chain_of_thought", False),
    ("WEB_SEARCH", "quick", False), ("CHAT", "quick", False),
])
def test_one_rule_decides_whether_a_result_is_shown_as_it_is(action, mode, as_is):
    from eli.kernel.engine import _shown_as_is
    assert _shown_as_is(action, mode) is as_is


# ── old talk is not this conversation ────────────────────────────────────────

def test_the_dialogue_block_is_this_conversation_not_the_last_argument():
    from eli.cognition.evidence_format import this_conversation
    now = time.time()
    turns = [{"role": "user", "content": "why are your dates all wrong", "ts": now - 2 * 86400},
             {"role": "assistant", "content": "the vector index drifted", "ts": now - 2 * 86400 + 60},
             {"role": "user", "content": "morning eli", "ts": now - 120},
             {"role": "assistant", "content": "Morning.", "ts": now - 110},
             {"role": "user", "content": "i have a presentation at 7.30pm", "ts": now - 5}]
    kept = this_conversation(turns, now)
    assert [t["content"] for t in kept] == ["morning eli", "Morning.", "i have a presentation at 7.30pm"]
    assert this_conversation([], now) == [] and len(this_conversation(turns[:2], now)) == 0


def test_profile_rows_about_eli_are_taken_out_and_the_users_own_facts_stay(tmp_path):
    import sqlite3
    from eli.runtime import profile_extractor as pe
    db = tmp_path / "user.sqlite3"
    pe.ensure_profile_tables(db)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS conversation_turns(id INTEGER PRIMARY KEY, session_id TEXT, user_id TEXT, "
                "role TEXT, content TEXT, ts REAL, timestamp REAL)")
    now = time.time()
    con.execute("INSERT INTO conversation_turns(role, content, ts) VALUES ('user', ?, ?)",
                ("you should have logs of every song played, and my name is not listed", now - 600))
    con.execute("INSERT INTO conversation_turns(role, content, ts) VALUES ('user', ?, ?)",
                ("i am building a simulation of tidal flow in a harbour for my course", now - 500))
    rows = [("project.current", "Resolving a conflict over missing Spotify logs and correcting the persistent storage "
                                "of the user's identity/name."),
            ("project.current", "Building a simulation of tidal flow in a harbour for a course."),
            ("identity.fact", "The user is currently in a period of high frustration with ELI's temporal awareness."),
            ("identity.location", "Lives in Springfield. Works in software. Currently frustrated with ELI's memory retrieval."),
            ("identity.role", "User's work/role: Software / tech")]
    for ptype, data in rows:
        con.execute("INSERT INTO user_patterns(pattern_type, pattern_data, ts) VALUES (?,?,?)", (ptype, data, now))
    con.commit()
    con.close()
    assert pe.purge_software_talk(db) == 3
    con = sqlite3.connect(db)
    left = sorted(r[0] for r in con.execute("SELECT pattern_data FROM user_patterns"))
    con.close()
    assert left == ["Building a simulation of tidal flow in a harbour for a course.",
                    "Lives in Springfield. Works in software.", "User's work/role: Software / tech"]
    assert pe.purge_software_talk(db) == 0


def test_an_event_the_user_moved_or_removed_is_not_offered_again_at_its_old_time(agenda, monday):
    ag.do_add_event({"text": "add the RAIMS presentation at 7.30pm today to my calendar"}, now=NOW)
    ag.do_add_event({"text": "i meant 8pm", "move": True}, now=NOW)
    assert ag.mentioned_event([SAID], now=NOW) is None
    assert "You mentioned" not in ag.do_list_events({"text": "what have i got on today"}, earlier=[SAID], now=NOW)["content"]
    ag.do_remove({"text": "cancel the RAIMS presentation"}, now=NOW)
    assert ag.mentioned_event([SAID], now=NOW) is None


def test_a_status_report_nobody_was_promised_is_not_run(monkeypatch):
    from eli.kernel.engine import CognitiveEngine
    ran = []
    me = SimpleNamespace(_in_followthrough=False, process=lambda *a, **k: ran.append(a) or {"action": "MEMORY_STATUS", "content": "x"},
                         _agenda_offer=lambda *a, **k: "", _store_followthrough_reply=lambda *a, **k: None,
                         _last_command_action=None)
    monkeypatch.setattr("eli.kernel.engine.route_intent", lambda text: {"action": "MEMORY_STATUS"})
    run = lambda reply: list(CognitiveEngine._stream_with_followthrough(me, iter([reply]), "how was your night"))
    run("Fine thanks. Let me check my memory status.")
    assert ran == []
    run("Let me check my memory status. I'll flag anything that looks off.")       # promised: it runs
    assert len(ran) == 1


class _Mem:
    """The least of the memory interface retrieve_for_turn touches."""
    def __init__(self, turns):
        self.turns = turns

    def get_recent_conversation(self, *a, **k):
        return list(self.turns)

    def recall_memory(self, *a, **k):
        return []

    def search_conversations(self, *a, **k):
        return []

    def get_session_summaries(self, *a, **k):
        return []


def test_earlier_sessions_stay_out_of_recent_turns_unless_the_question_is_about_the_past():
    from eli.memory.retrieval import retrieve_for_turn
    now = time.time()
    mem = _Mem([{"role": "user", "content": "i was working on the solar hydrogen model", "ts": now - 86400},
                {"role": "user", "content": "morning", "ts": now - 60}])
    said = lambda q: [t["content"] for t in retrieve_for_turn(mem, q, use_cache=False, rerank=False).recent_turns]
    assert said("i have a presentation at 7.30pm") == ["morning"]
    assert said("what did we talk about earlier?") == ["i was working on the solar hydrogen model", "morning"]


def test_the_calendar_plugin_uses_the_same_calendar(agenda):
    from eli.plugins.calendar.plugin import CalendarPlugin
    plugin = CalendarPlugin.__new__(CalendarPlugin)
    added = plugin.add_event({"text": "add dentist appointment on friday at 2:30pm to my calendar"})
    assert added["ok"] and "Dentist appointment" in ag.do_list_events({"text": "what's on this week"})["content"]
    assert "Dentist appointment" in plugin.list_events({"text": "what's on this week"})["content"]


def test_a_due_reminder_reaches_the_desktop_and_the_chat(monkeypatch):
    import queue
    seen, q = [], queue.Queue()
    monkeypatch.setenv("ELI_AGENDA_NOTIFY", "1")
    monkeypatch.setattr("eli.utils.platform_compat.notify", lambda title, body, *a, **k: seen.append(("notify", body)))
    monkeypatch.setattr("eli.utils.platform_compat.play_alarm_sound", lambda *a, **k: seen.append(("sound", "")))
    monkeypatch.setattr("eli.planning.proactive_daemon.get_daemon", lambda *a, **k: SimpleNamespace(suggestion_queue=q))
    at = datetime(2026, 10, 5, 19, 0).timestamp()
    ag._default_delivery({"title": "RAIMS presentation in 30 minutes", "start_ts": at}, missed=False)
    assert seen == [("notify", "RAIMS presentation in 30 minutes (19:00)"), ("sound", "")]
    kind, data = q.get_nowait()
    assert kind == "reminder" and data["suggestion"] == "Reminder: RAIMS presentation in 30 minutes (19:00)"
    seen.clear()
    ag._default_delivery({"title": "Call mum", "start_ts": at}, missed=True)      # came due while ELI was shut: no alarm
    assert seen == [("notify", "Call mum (was due at 19:00; ELI was not running)")]
    assert q.get_nowait()[1]["suggestion"].endswith("ELI was not running)")
