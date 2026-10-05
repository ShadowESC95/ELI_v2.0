"""Whatever ELI offers, asks or proposes, the user's reply is read against it.

The first version of this only kept an offer when the router had an action for it. An offer
ELI would carry out by writing ("Want me to walk you through it?", a plan followed by "shall I
go ahead with any of these?") left nothing behind, so "yes please" reached the model as two
bare words. Now every reply leaves a record of what it left open: the steps it offered
(actions, and tasks ELI does by writing), the question it ended on, and any detail an action
asked for. "yes", "do 2", "the second one", "the abstract one", "no thanks" and a plain answer
are each read against that record, in code, whatever the conversation is about.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from eli.kernel import request_context as rc
from eli.runtime import agenda as ag
from eli.runtime import pending_proposal as pp

WRITING = ("A vector index stores each piece of text as a list of numbers. "
           "Want me to walk you through how the search actually works, step by step?")
PLAN = ("I can help with the write-up in three ways:\n\n1. Draft an outline for the report.\n2. Write the abstract.\n"
        "3. List the open questions for the discussion section.\n\nWould you like me to go ahead with any of these?")
EITHER = ("There are two ways. Option A re-embeds everything nightly. Option B embeds only what changed. "
          "Which one should I plan around?")
MIXED = ("Yes. Let's proceed directly to the issue at hand.\n\nFirstly, let's verify the exact details of both meetings:\n\n"
         "1. **Review and Prepare**:\n   - Ensure all materials for the presentation are complete.\n2. **Schedule Check**:\n"
         "   - Double-check your calendar to ensure no other meetings conflict with this new time slot.\n3. **Notifications**:\n"
         "   - Set reminders for 4 PM today (5 hours before the presentation) to alert you about the upcoming meeting.\n"
         "   - Consider setting another reminder at 6:00 PM as a final check-in point.\n\nWould you like me to help you set up "
         "these reminders or take any other actions?")


@pytest.fixture()
def proposals(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "_path", lambda: tmp_path / "pending_proposal.json")
    yield


@pytest.fixture()
def agenda(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_AGENDA_DB", str(tmp_path / "agenda.sqlite3"))
    monkeypatch.setenv("ELI_CALENDAR_FILE", str(tmp_path / "calendar.ics"))
    monkeypatch.setattr("eli.kernel.state.get_active_user_id", lambda *a, **k: "owner")
    ag.set_delivery(lambda item, missed: None)
    yield
    ag.set_delivery(None)


def _kinds(text, **kw):
    return [(i["n"], i["kind"], i["command"]) for i in pp.read_reply(text, **kw)["items"]]


def _leave_open(text):
    got = pp.read_reply(text)
    pp.set_pending_proposal("", items=got["items"], question=got["question"], from_reply=True)


# ── what a reply leaves open ─────────────────────────────────────────────────

def test_an_offer_eli_carries_out_by_writing_is_kept_in_the_users_words():
    assert _kinds(WRITING) == [(None, "task", "walk me through how the search actually works")]
    assert _kinds("That is the short version. Want me to elaborate?") == [(None, "task", "elaborate")]
    assert _kinds("Shall I draft the email to John?") == [(None, "task", "draft the email to John")]
    assert _kinds("I could show you your options?") == [(None, "task", "show me my options")]


def test_a_plan_eli_asks_to_go_ahead_with_is_kept_step_by_step():
    assert _kinds(PLAN) == [(1, "task", "Draft an outline for the report"), (2, "task", "Write the abstract"),
                            (3, "task", "List the open questions for the discussion section")]
    labelled = ("Here is a plan:\n\n1. **Draft the outline**\n2. **Write the abstract**: about 200 words.\n"
                "3. **Check the weather for Friday**\n\nWhich of these should I start with?")
    assert _kinds(labelled) == [(1, "task", "Draft the outline"), (2, "task", "Write the abstract: about 200 words"),
                                (3, "action", "Check the weather for Friday")]


def test_a_step_with_an_action_and_a_step_without_sit_in_the_same_list():
    kinds = [(n, kind) for n, kind, _ in _kinds(MIXED)]
    assert kinds == [(1, "task"), (2, "action"), (3, "action"), (3, "action")]


@pytest.mark.parametrize("reply", [
    "Three facts about Mars:\n1. It has two moons.\n2. Its day is 24.6 hours long.\n3. It is red because of iron oxide.",
    "I can see why that is frustrating. I'll keep that in mind. You want me to be more direct.",
    "Paris is the capital of France.",
    "Good morning. How did the presentation go last night?",
    EITHER,
    "What would you like me to do next?",
])
def test_a_reply_that_offers_nothing_leaves_no_step_behind(reply):
    assert pp.read_reply(reply)["items"] == []


def test_a_list_of_facts_is_not_a_plan_because_an_offer_follows_it():
    facts = ("Three facts about Mars:\n1. It has two moons.\n2. Its day is 24.6 hours long.\n"
             "3. It is red because of iron oxide.\n\nWant me to tell you about Jupiter too?")
    assert _kinds(facts) == [(None, "task", "tell me about Jupiter too")]


def test_the_question_a_reply_ends_on_is_kept_and_a_question_in_passing_is_not():
    assert pp.read_reply(EITHER)["question"] == "Which one should I plan around?"
    assert pp.read_reply("Good morning. How did the presentation go last night?")["question"].startswith("How did")
    assert pp.read_reply("Did it rain? No idea. Anyway, the build passed.")["question"] == ""


def test_something_only_the_users_own_words_may_start_is_never_a_task_for_the_model():
    got = pp.read_reply("The persona is locked. Want me to clear the persona lock?")["items"]
    assert [(i["kind"], i["command"]) for i in got] == [("explicit", "clear the persona lock")]
    assert "clear the persona lock" in pp.own_words_line(["clear the persona lock"])


def test_the_result_of_an_action_offers_only_what_it_asks():
    done = "Reminder set for today at 16:00: Go over my slides. I'll remind you then.\n- Check the news later."
    assert pp.read_reply(done, offers_only=True)["items"] == []
    asked = pp.read_reply(done + " Want me to check the news now?", offers_only=True)["items"]
    assert [i["action"] for i in asked] == ["NEWS_FETCH"]


def test_a_record_with_only_a_question_is_not_an_offer_to_older_callers(proposals):
    pp.set_pending_proposal("", question="Which one should I plan around?", from_reply=True)
    assert pp.get_pending_proposal() is None
    assert pp.get_follow_up()["question"] == "Which one should I plan around?"
    pp.clear_pending_proposal()
    assert pp.get_follow_up() is None


# ── saying yes, picking, declining ───────────────────────────────────────────

@pytest.mark.parametrize("text", ["yes please", "yes", "ok", "sure", "go ahead", "do it", "sounds good", "that works",
                                  "why not", "go for it", "I said yes already", "YES! DO 1-3", "both", "perfect, do it",
                                  "yes please do that", "i'd like that"])
def test_ways_of_agreeing(text):
    assert pp.is_consent(text)


@pytest.mark.parametrize("text", ["all good thanks", "not now", "no thanks", "thanks", "great weather today",
                                  "yes please dig into the timestamps", "ok but what about the cost", "the second one",
                                  "what's an abstract?"])
def test_things_that_are_not_agreement(text):
    assert not pp.is_consent(text)


def test_yes_to_a_writing_offer_is_carried_out_as_that_task(proposals):
    from eli.execution.router_enhanced import route
    _leave_open(WRITING)
    got = route("yes please")
    assert got["action"] == "CHAT" and got["meta"]["matched_by"] == "pending_proposal.confirm"
    assert got["args"]["agreed"]["tasks"] == ["walk me through how the search actually works"]
    assert got["args"]["agreed"]["commands"] == [] and pp.get_follow_up() is None       # spent


@pytest.mark.parametrize("reply,tasks", [
    ("yes please", ["Draft an outline for the report", "Write the abstract",
                    "List the open questions for the discussion section"]),
    ("do 2", ["Write the abstract"]),
    ("yes, 1 and 3", ["Draft an outline for the report", "List the open questions for the discussion section"]),
    ("the second one", ["Write the abstract"]),                     # a pick needs no "yes"
    ("the abstract one", ["Write the abstract"]),                   # by its own words
    ("just the outline", ["Draft an outline for the report"]),
    ("2", ["Write the abstract"]),
])
def test_a_reply_picks_from_the_plan_by_number_or_by_name(proposals, reply, tasks):
    from eli.execution.router_enhanced import route
    _leave_open(PLAN)
    got = route(reply)
    assert got["meta"]["matched_by"] == "pending_proposal.confirm" and got["args"]["agreed"]["tasks"] == tasks


@pytest.mark.parametrize("reply", ["what's an abstract?", "how long would the outline take", "tell me a joke instead",
                                   "the weather"])
def test_a_new_question_or_request_is_not_taken_as_a_pick(proposals, reply):
    from eli.execution.router_enhanced import route
    _leave_open(PLAN)
    assert (route(reply).get("meta") or {}).get("matched_by") != "pending_proposal.confirm"


def test_a_decline_drops_what_was_offered(proposals):
    from eli.execution.router_enhanced import route
    _leave_open(WRITING)
    assert (route("no thanks").get("meta") or {}).get("matched_by") != "pending_proposal.confirm"
    assert pp.get_follow_up() is None
    assert (route("yes please").get("meta") or {}).get("matched_by") != "pending_proposal.confirm"   # nothing left to agree to


def test_agreeing_to_a_mixed_list_runs_the_actions_and_writes_the_rest(proposals):
    from eli.execution.router_enhanced import route
    _leave_open(MIXED)
    got = route("YES! DO 1-3")["args"]["agreed"]
    assert got["tasks"] == ["Ensure all materials for the presentation are complete"]
    assert len(got["commands"]) == 3 and got["commands"][0].startswith("Double-check your calendar")
    _leave_open(MIXED)
    only_actions = route("do 2 and 3")
    assert only_actions["action"] == "MULTI_COMMAND" and only_actions["args"]["results_only"] is True


def test_yes_to_an_offer_that_needs_the_users_own_words_is_passed_on_as_that(proposals):
    from eli.execution.router_enhanced import route
    _leave_open("The persona is locked. Want me to clear the persona lock?")
    got = route("yes")["args"]["agreed"]
    assert got["explicit"] == ["clear the persona lock"] and got["tasks"] == [] and got["commands"] == []


# ── carrying it out ──────────────────────────────────────────────────────────

def _engine(monkeypatch, reply="Here is the walk-through."):
    from eli.kernel.engine import CognitiveEngine
    seen = SimpleNamespace(messages=[], agreed=[], ran=[])

    def process(message, **kw):
        seen.messages.append(message)
        seen.agreed.append(dict(rc.agreed_task_var.get() or {}))
        if kw.get("stream"):
            return (piece for piece in [reply])
        return {"ok": True, "action": "CHAT", "response": reply, "content": reply}

    def execute(action, args=None, *a, **k):
        seen.ran.append((action, list((args or {}).get("commands") or []), (args or {}).get("results_only")))
        return {"ok": True, "action": action, "response": "On your calendar today:\n- nothing", "content": ""}

    monkeypatch.setattr("eli.kernel.engine.execute_action", execute)
    me = SimpleNamespace(process=process)
    return CognitiveEngine._carry_out_agreed, me, seen


def test_an_agreed_task_runs_as_a_turn_of_its_own_with_the_task_as_its_message(monkeypatch):
    carry, me, seen = _engine(monkeypatch)
    out = carry(me, "yes please", {"tasks": ["walk me through how the search actually works"], "commands": [],
                                   "explicit": [], "offer": "Want me to walk you through it?"})
    assert seen.messages == ["walk me through how the search actually works"] and seen.ran == []
    assert seen.agreed[0]["said"] == "yes please" and seen.agreed[0]["message"] == seen.messages[0]
    assert out["response"] == "Here is the walk-through."
    assert rc.agreed_task_var.get() is None                    # set for that turn only


def test_agreed_actions_run_first_and_their_results_lead_the_reply(monkeypatch):
    carry, me, seen = _engine(monkeypatch, reply="Checklist: slides, notes, clicker.")
    agreed = {"commands": ["check my calendar", "remind me at 4pm"], "tasks": ["Ensure all materials are complete"],
              "explicit": [], "offer": ""}
    out = carry(me, "YES! DO 1-3", agreed)
    assert seen.ran == [("MULTI_COMMAND", ["check my calendar", "remind me at 4pm"], True)]
    assert out["response"] == "On your calendar today:\n- nothing\n\nChecklist: slides, notes, clicker."
    assert seen.agreed[0]["done"] == "On your calendar today:\n- nothing"
    streamed = "".join(str(p) for p in carry(me, "YES! DO 1-3", agreed, stream=True))
    assert streamed == "On your calendar today:\n- nothing\n\nChecklist: slides, notes, clicker."


def test_yes_to_an_explicit_only_offer_says_what_to_say_and_calls_no_model(monkeypatch):
    carry, me, seen = _engine(monkeypatch)
    out = carry(me, "yes", {"commands": [], "tasks": [], "explicit": ["clear the persona lock"], "offer": ""})
    assert seen.messages == [] and seen.ran == []
    assert out["response"] == 'That one I only do on your own words, not on a yes to mine. Say "clear the persona lock" and I will.'


def test_the_task_turn_is_chat_without_routing_or_resolving_eli_s_words_again(monkeypatch):
    from eli.kernel import engine as E
    monkeypatch.setattr(E, "route_intent", lambda text: pytest.fail("the task was routed again"))
    token = rc.agreed_task_var.set({"said": "yes", "message": "play the outline back to me", "done": ""})
    try:
        got = E.CognitiveEngine._parse_intent(SimpleNamespace(), "play the outline back to me", [])
    finally:
        rc.agreed_task_var.reset(token)
    assert got["action"] == "CHAT" and got["meta"]["matched_by"] == "pending_proposal.task"


def test_the_model_is_told_what_the_message_is_a_reply_to():
    from eli.kernel.engine import _follow_up_line
    assert _follow_up_line() == ""
    facts = rc.turn_facts_var.set({"user_input": "Write the abstract"})
    agreed = rc.agreed_task_var.set({"said": "do 2", "message": "Write the abstract", "done": "Reminder set for 16:00."})
    try:
        line = _follow_up_line()
        assert line.startswith('\nAGREED: You offered this in your last message and the user answered "do 2".')
        assert "Do it now, completely" in line and "ALREADY DONE THIS TURN" in line and "Reminder set for 16:00." in line
        rc.turn_facts_var.get()["user_input"] = "something else"       # a turn nested inside it is not the task
        assert _follow_up_line() == ""
    finally:
        rc.agreed_task_var.reset(agreed)
        rc.turn_facts_var.reset(facts)
    facts = rc.turn_facts_var.set({"user_input": "the second one", "answers_question": "Which one should I plan around?"})
    try:
        line = _follow_up_line()
        assert 'ASKING THE USER: "Which one should I plan around?"' in line and "Do not ask the same question again" in line
    finally:
        rc.turn_facts_var.reset(facts)


def test_every_reply_replaces_what_the_last_one_left_open(proposals):
    from eli.kernel.engine import CognitiveEngine
    me = SimpleNamespace(memory=SimpleNamespace(add_conversation_turn=lambda *a, **k: None), session_id="s", user_id="u",
                         _in_nested_turn=lambda: False)
    token = rc.turn_facts_var.set({"user_input": "x"})
    try:
        CognitiveEngine._store_assistant_turn(me, PLAN)
        assert [i["n"] for i in pp.get_follow_up()["items"]] == [1, 2, 3]
        CognitiveEngine._store_assistant_turn(me, EITHER)
        left = pp.get_follow_up()
        assert left["items"] == [] and left["question"] == "Which one should I plan around?"
        CognitiveEngine._store_assistant_turn(me, "Paris is the capital of France.")
        assert pp.get_follow_up() is None
    finally:
        rc.turn_facts_var.reset(token)


@pytest.mark.parametrize("text,short", [("the second one", True), ("B", True), ("friday at 3pm", True),
                                        ("what do you mean?", False), ("how long would that take", False), ("", False),
                                        ("well I was thinking we could look at the whole thing again from the start maybe", False)])
def test_what_counts_as_a_short_answer(text, short):
    assert pp.is_short_answer(text) is short


# ── an action that asks is answered, not forgotten ───────────────────────────

def test_the_answer_to_when_is_it_completes_the_request(agenda, proposals):
    from eli.execution import executor_enhanced as ex
    from eli.execution.router_enhanced import route
    asked = ex.execute("ADD_EVENT", {"text": "add dentist appointment to my calendar"})
    assert not asked["ok"] and asked["response"].startswith("I can add that. When is it?")
    assert pp.get_follow_up()["awaiting"] == {"command": "add dentist appointment to my calendar", "action": "ADD_EVENT",
                                              "needs": "when"}
    got = route("friday at 3pm")
    assert got["action"] == "ADD_EVENT" and got["meta"]["matched_by"] == "pending_proposal.answer"
    added = ex.execute("ADD_EVENT", got["args"])
    assert added["ok"] and added["response"].startswith("Added to your calendar: Dentist appointment, ")
    assert "at 15:00" in added["response"]


def test_a_new_command_after_a_question_is_a_new_command(agenda, proposals):
    from eli.execution import executor_enhanced as ex
    from eli.execution.router_enhanced import route
    ex.execute("ADD_EVENT", {"text": "add dentist appointment to my calendar"})
    assert pp.get_follow_up()["question"] == "When is it?"
    assert route("set a timer for 5 minutes")["action"] == "SET_TIMER"
    assert route("what's on tomorrow")["action"] == "LIST_EVENTS"          # names a day, but asks for something else


def test_the_answer_to_when_should_i_remind_you_sets_the_reminder(agenda, proposals):
    from eli.execution import executor_enhanced as ex
    from eli.execution.router_enhanced import route
    asked = ex.execute("SET_ALARM", {"text": "remind me to call mum"})
    assert asked["response"].startswith("When should I remind you?")
    got = route("in 20 minutes")
    assert got["action"] == "SET_ALARM" and got["meta"]["matched_by"] == "pending_proposal.answer"
    assert ex.execute("SET_ALARM", got["args"])["response"].startswith("Reminder set for ")


@pytest.mark.parametrize("answer", ["the second one", "2", "the check-up", "the check-up one please"])
def test_which_one_is_answered_by_number_or_by_name(agenda, proposals, answer):
    from eli.execution import executor_enhanced as ex
    from eli.execution.router_enhanced import route
    ex.execute("ADD_EVENT", {"text": "add dentist appointment in 3 days at 2:30pm to my calendar"})
    ex.execute("ADD_EVENT", {"text": "add dentist check-up in 10 days at 10am to my calendar"})
    asked = ex.execute("REMOVE_EVENT", {"text": "cancel the dentist"})
    assert asked["error"] == "ambiguous" and len(pp.get_follow_up()["items"]) == 2
    got = route(answer)
    assert got["action"] == "REMOVE_EVENT"
    gone = ex.execute("REMOVE_EVENT", got["args"])
    assert gone["ok"] and gone["response"].startswith("Removed from your calendar: Dentist check-up")
    left = ex.execute("LIST_EVENTS", {"text": "what's on my calendar this month"})["response"]
    assert "Dentist appointment" in left and "check-up" not in left


@pytest.mark.parametrize("reply,is_it", [("friday at 3pm", True), ("in 20 minutes", True), ("tomorrow", True),
                                         ("at 4", True), ("make it 7.30pm", True), ("next monday at 9", True),
                                         ("set a timer for 5 minutes", False), ("what's on tomorrow", False),
                                         ("play some jazz at 4pm", False), ("no idea", False)])
def test_a_reply_that_is_only_a_day_or_a_time_is_the_detail_asked_for(reply, is_it):
    assert pp.is_the_detail(reply, "when") is is_it


@pytest.mark.parametrize("word", ["Dublin", "Tuesday", "Pizza", "Spotify", "Morgan", "Tomorrow", "Brilliant"])
def test_a_word_on_its_own_is_not_the_users_name(proposals, word):
    from eli.execution.router_enhanced import route
    assert route(word)["action"] != "SET_USER_NAME"
    pp.set_pending_proposal("", question="Which city is the conference in?", from_reply=True)
    assert route(word)["action"] != "SET_USER_NAME"


def test_a_word_on_its_own_is_the_name_when_eli_asked_for_it(proposals):
    from eli.execution.router_enhanced import route
    pp.set_pending_proposal("", question="So, to start with, what should I call you?", from_reply=True)
    got = route("Morgan")
    assert got["action"] == "SET_USER_NAME" and got["args"]["name"] == "Morgan"


@pytest.mark.parametrize("reply", ["B", "2", "tomorrow", "later", "Dublin"])
def test_one_word_after_a_question_is_an_answer_not_a_fragment(proposals, reply):
    from eli.execution.router_enhanced import route
    assert route(reply)["action"] == "NOOP"                    # nothing open: "I only caught ..." as before
    pp.set_pending_proposal("", question="Which one should I plan around?", from_reply=True)
    assert route(reply)["action"] != "NOOP"


@pytest.mark.parametrize("text", ["the pasta needs 20 minutes", "in 20 minutes", "give me twenty minutes"])
def test_a_duration_is_not_a_complaint_about_speed(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] != "EXPLAIN_COGNITION_RUNTIME"


@pytest.mark.parametrize("text", ["it took you 20 minutes to generate that answer?", "why did you take 20 minutes to respond?"])
def test_a_complaint_about_speed_still_gets_the_timing_report(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] == "EXPLAIN_COGNITION_RUNTIME"


# ── asking for help with something is not asking what ELI can do ─────────────

@pytest.mark.parametrize("text", ["help", "help me", "i need help", "help please", "commands", "what can i ask you?",
                                  "show me the commands", "what commands do you have"])
def test_asking_what_eli_can_do_lists_it(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] == "HELP"


@pytest.mark.parametrize("text", ["help me with my essay", "help me plan my week", "help me understand compound interest",
                                  "what can i do about my landlord", "command line tips for git",
                                  "help me with the write-up for my index project"])
def test_asking_for_help_with_something_is_a_request_for_that(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] != "HELP"


# ── a question about the world is not a question about ELI ───────────────────

@pytest.mark.parametrize("text", ["what's a vector index?", "what is a knowledge graph", "what is faiss",
                                  "how does memory work in the brain", "how do i improve my memory",
                                  "my memory is terrible, any tips?"])
def test_general_questions_do_not_get_elis_own_internals(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] not in ("EXPLAIN_MEMORY_RUNTIME", "PERSONAL_MEMORY_DEEP_EXPLAIN", "MEMORY_STATUS")


@pytest.mark.parametrize("text,action", [
    ("how does your memory work", "EXPLAIN_MEMORY_RUNTIME"), ("explain your memory system", "EXPLAIN_MEMORY_RUNTIME"),
    ("how do you use faiss", "EXPLAIN_MEMORY_RUNTIME"), ("is the vector index healthy", "EXPLAIN_MEMORY_RUNTIME"),
    ("how does the memory system work", "EXPLAIN_MEMORY_RUNTIME"), ("what is in my memory", "PERSONAL_MEMORY_DEEP_EXPLAIN"),
    ("explain my memory internals", "PERSONAL_MEMORY_DEEP_EXPLAIN"),
])
def test_questions_about_elis_memory_still_get_the_report(text, action):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] == action


# ── weather for a day ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,place", [("check the weather for tomorrow", None), ("weather for tomorrow", None),
                                        ("what's the weather in Dublin tomorrow", "Dublin"), ("weather in Paris", "Paris"),
                                        ("what's the forecast for this weekend in Galway", "Galway")])
def test_a_day_is_not_a_place_and_asking_about_tomorrow_is_not_a_job_for_tomorrow(text, place):
    from eli.execution.router_enhanced import route
    got = route(text)
    assert got["action"] == "GET_WEATHER" and got["args"]["location"] == place


@pytest.mark.parametrize("text", ["check the weather in Cork at 7am tomorrow", "get the news at 7am", "open spotify at 8pm"])
def test_a_clock_time_still_makes_it_a_job(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] == "SCHEDULE_TASK"


def _weather_net(monkeypatch, calls):
    from datetime import date, timedelta
    from eli.plugins.weather import plugin as wp
    days = [(date.today() + timedelta(days=n)).isoformat() for n in range(14)]

    def fake(url):
        calls.append(url)
        if "geocoding" in url:
            return {"results": [{"name": "Dublin", "admin1": "Leinster", "country_code": "IE",
                                 "latitude": 53.3, "longitude": -6.2}]}
        if "daily=" in url:
            return {"daily": {"time": days, "weather_code": [61] * 14, "temperature_2m_min": [9] * 14,
                              "temperature_2m_max": [15] * 14, "precipitation_probability_max": [70] * 14}}
        return {"current": {"temperature_2m": 12, "apparent_temperature": 10, "relative_humidity_2m": 80,
                            "wind_speed_10m": 14, "weather_code": 3}}
    monkeypatch.setattr(wp, "_get_json", fake)
    monkeypatch.setattr("eli.core.netguard.should_block_network", lambda *a, **k: False)


def test_asked_about_tomorrow_the_answer_is_tomorrows_forecast_not_now(monkeypatch, proposals):
    from eli.execution import executor_enhanced as ex
    calls = []
    _weather_net(monkeypatch, calls)
    now = ex.execute("GET_WEATHER", {"location": "Dublin", "_raw_user_text": "what's the weather in Dublin"})
    assert now["response"].startswith("Weather for Dublin, Leinster, IE: 12°C")
    later = ex.execute("GET_WEATHER", {"location": "Dublin", "_raw_user_text": "what's the weather in Dublin tomorrow"})
    assert later["ok"] and later["response"].startswith("Forecast for Dublin, Leinster, IE, ")
    assert later["response"].endswith(": 9 to 15°C, slight rain, 70% chance of rain.") and any("daily=" in u for u in calls)


def test_where_is_asked_once_and_the_answer_completes_the_request(monkeypatch, proposals):
    from eli.execution import executor_enhanced as ex
    from eli.execution.router_enhanced import route
    _weather_net(monkeypatch, [])
    token = rc.session_id_var.set("weather-test-session")
    try:
        asked = ex.execute("GET_WEATHER", {"location": None, "_raw_user_text": "check the weather for tomorrow"})
        assert asked["response"] == "Where? Give me a town or city." and asked["error"] == "missing_location"
        got = route("Dublin")
        assert got["action"] == "GET_WEATHER" and got["args"]["location"] == "Dublin"
        assert got["meta"]["matched_by"] == "pending_proposal.answer"
        assert ex.execute("GET_WEATHER", got["args"])["response"].startswith("Forecast for Dublin, Leinster, IE, ")
        again = ex.execute("GET_WEATHER", {"location": None, "_raw_user_text": "and the weather now"})   # remembered
        assert again["response"].startswith("Weather for Dublin, Leinster, IE: 12°C")
    finally:
        rc.session_id_var.reset(token)


@pytest.mark.parametrize("reply,is_it", [("Dublin", True), ("in Cork", True), ("new york", True), ("it's Galway", True),
                                         ("no", False), ("never mind", False), ("yes", False), ("what do you mean", False),
                                         ("somewhere near the coast i think maybe", False)])
def test_a_reply_that_is_only_a_place_is_the_detail_asked_for(reply, is_it):
    assert pp.is_the_detail(reply, "place") is is_it


@pytest.mark.parametrize("text", ["start with the outline", "run through it again", "start over", "start by explaining the plan"])
def test_starting_something_is_not_opening_an_app(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] != "OPEN_APP"


@pytest.mark.parametrize("text", ["start spotify", "run firefox", "open steam", "launch vlc"])
def test_opening_an_app_still_opens_it(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] in ("OPEN_APP", "OPEN_BROWSER", "PLAY_MEDIA", "OPEN_MEDIA_HUB")


# ── "for tonight" says what it is about, not when to do it ───────────────────

@pytest.mark.parametrize("text", ["help me plan a study session for tonight", "write a speech for tomorrow",
                                  "find a recipe for tonight", "i need to study tonight", "make a packing list for tomorrow",
                                  "prepare some questions for my interview tomorrow", "check the weather for tomorrow"])
def test_a_request_about_a_day_is_answered_now_not_queued_for_2am(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] != "SCHEDULE_TASK"


@pytest.mark.parametrize("text", ["research quantum computing overnight", "build me a script at 2am",
                                  "get a morning report ready for me tomorrow morning", "run the test suite tonight",
                                  "remind me to research flights tomorrow", "schedule a morning report every morning",
                                  "write the report later tonight", "have the summary ready by tomorrow, research the market"])
def test_a_request_to_do_it_later_is_still_a_job(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] in ("SCHEDULE_TASK", "SET_ALARM")


def test_a_scheduled_test_run_is_stored_as_a_command_that_runs_tests():
    from eli.execution.router_enhanced import route
    job = route("run the test suite tonight")
    assert job["action"] == "SCHEDULE_TASK" and job["args"]["request"] == "run the test suite"
    assert route(job["args"]["request"])["action"] == "RUN_TESTS"          # what the job does when it fires


def test_the_calendar_can_be_asked_about_a_month(agenda):
    from datetime import datetime
    now = datetime(2026, 10, 5, 9, 5)
    ag.do_add_event({"text": "add dentist check-up on 20 October at 10am to my calendar"}, now=now)
    ag.do_add_event({"text": "add conference on 12 November at 9am to my calendar"}, now=now)
    this = ag.do_list_events({"text": "what's on my calendar this month"}, now=now)["response"]
    assert this.startswith("On your calendar for the rest of this month:") and "check-up" in this and "Conference" not in this
    following = ag.do_list_events({"text": "anything on next month"}, now=now)["response"]
    assert following.startswith("On your calendar next month:") and "Conference" in following and "check-up" not in following


@pytest.mark.parametrize("said,offered", [
    ("help me plan a study session for tonight", False),          # no time was given
    ("i have a meeting this evening", False),
    ("i have a team meeting at 8pm tonight", True),
    ("got a dentist appointment tomorrow at 2.30pm", True),
])
def test_an_event_is_offered_back_only_with_the_time_the_user_gave(agenda, said, offered):
    from datetime import datetime
    assert (ag.mentioned_event([said], now=datetime(2026, 10, 5, 9, 5)) is not None) is offered


def test_a_request_that_names_its_own_event_does_not_borrow_another_events_time(agenda):
    from datetime import datetime
    now = datetime(2026, 10, 5, 9, 5)
    said = "I thought i had a presentation at 10am for RAIMS, but it is not until 7.30pm haha"
    assert ag.from_text("add dentist appointment to my calendar", earlier=[said], now=now) is None      # asks when
    asked = ag.do_add_event({"text": "add dentist appointment to my calendar"}, earlier=[said], now=now)
    assert not asked["ok"] and asked["response"].startswith("I can add that. When is it?")
    same = ag.from_text("add the RAIMS presentation to my calendar", earlier=[said], now=now)            # the same event
    assert same["title"] == "RAIMS presentation" and datetime.fromtimestamp(same["start_ts"]).strftime("%H:%M") == "19:30"
    it = ag.from_text("add it to my calendar", earlier=[said], now=now)                                   # names nothing
    assert it["title"] == "RAIMS presentation" and datetime.fromtimestamp(it["start_ts"]).strftime("%H:%M") == "19:30"


# ── offers made as statements, and questions from any action ─────────────────

@pytest.mark.parametrize("reply,task", [
    ("That is the gist. Let me know if you'd like me to draft the cover letter.", "draft the cover letter"),
    ("If you want, I can walk you through the proof.", "walk me through the proof"),
    ("I can turn this into a checklist if you'd like.", "turn this into a checklist"),
    ("Just say the word and I'll write the summary.", "write the summary"),
    ("Need me to explain the second step?", "explain the second step"),
    ("How about I outline the chapters first?", "outline the chapters first"),
])
def test_an_offer_is_an_offer_however_it_is_phrased(reply, task):
    assert [(i["kind"], i["command"]) for i in pp.read_reply(reply)["items"]] == [("task", task)]


@pytest.mark.parametrize("reply", ["Is there anything else I can help with?", "Can I help with anything else?",
                                   "Want me to help with anything else?", "Let me know if you need anything else.",
                                   "I can see how that would be annoying if you had a deadline."])
def test_a_closing_pleasantry_is_not_something_to_carry_out(reply):
    assert pp.read_reply(reply)["items"] == []


def test_yes_to_an_offer_made_as_a_statement_is_carried_out(proposals):
    from eli.execution.router_enhanced import route
    _leave_open("That is the gist. Let me know if you'd like me to draft the cover letter.")
    got = route("yes please")
    assert got["meta"]["matched_by"] == "pending_proposal.confirm"
    assert got["args"]["agreed"]["tasks"] == ["draft the cover letter"]


@pytest.mark.parametrize("result,asks", [
    ({"ok": False, "response": "Which file do you mean?"}, True),                       # any handler that asks
    ({"ok": False, "response": "No app called 'spotfy'. Did you mean 'spotify'?"}, True),
    ({"ok": False, "awaiting": {"command": "x", "action": "Y"}, "response": "When is it?"}, True),
    ({"ok": False, "response": "The file could not be read."}, False),                  # a real failure
    ({"ok": True, "response": "Done. Anything else?"}, False),                          # it worked
    ("Which file?", False),
])
def test_an_action_that_answers_with_a_question_is_asking_not_failing(result, asks):
    from eli.kernel.engine import _asks_the_user
    assert _asks_the_user(result) is asks


def test_an_offer_survives_the_tidying_of_the_stored_reply(proposals):
    from eli.cognition.output_governor import govern_output
    from eli.kernel.engine import CognitiveEngine
    offer = "That is the gist. Let me know if you'd like me to draft the cover letter."
    assert govern_output(offer, is_grounded=False) == offer                        # a particular offer is kept
    assert govern_output("That is the gist. Let me know if you need anything else!", is_grounded=False) == "That is the gist."
    stored = []
    me = SimpleNamespace(memory=SimpleNamespace(add_conversation_turn=lambda role, text, *a, **k: stored.append(text)),
                         session_id="s", user_id="u", _in_nested_turn=lambda: False)
    token = rc.turn_facts_var.set({"user_input": "x"})
    try:
        # even where the stored copy loses a sentence, what was offered is read from what was shown
        CognitiveEngine._store_assistant_turn(me, "Here it is. I'd be happy to turn this into a checklist if you'd like.")
        assert [i["command"] for i in pp.get_follow_up()["items"]] == ["turn this into a checklist"]
        assert stored == ["Here it is."]
    finally:
        rc.turn_facts_var.reset(token)
