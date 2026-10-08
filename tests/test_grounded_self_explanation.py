"""ELI explains its own behaviour from what the pipeline recorded, or not at all.

Live 2026-10-03, on a 35B model: asked why it web-searched a question about the user's own
week, ELI blamed "vector search drift" and "embedding model decay"; asked about logging it
offered to enable a `verbose_media_logging` setting, cited an `action_logs` table, and later
said "Consider it done. The audit trail is now active" for logging that was always on. None of
it exists. Routing and escalation never reach the model, so each turn now records what the
pipeline did, the record is handed over when ELI is asked about itself, and sentences that
name things ELI doesn't have are dropped, in streamed replies too.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from eli.cognition import self_claims as sc
from eli.kernel import request_context as rc
from eli.cognition import self_claims
from eli.kernel.request_context import turn_facts_var


@pytest.fixture()
def turn():
    """A turn's facts, as process() sets them."""
    facts = {"user_input": "you should have logs of every song played, why don't you?", "t0": time.perf_counter()}
    token = rc.turn_facts_var.set(facts)
    yield facts
    rc.turn_facts_var.reset(token)


@pytest.mark.parametrize("text,about", [
    ("why did you search the web for that?", True),
    ("What is with all the issues?", True),
    ("Why the fuck are you lying to me and making shit up?", True),
    ("i want logging for every single thing that you do", True),
    ("what went wrong there?", True),
    ("YOU DO NOT NEED TO SEARCH THE FUCKING WEB FOR ANY OF THOSE QUESTIONS!!", True),
    ("you should have logs of every song played", True),
    ("i asked you a fucking question Eli!!", True),
    ("play my mom by eminem", False),
    ("why is the sky blue?", False),
    ("what is the capital of France?", False),
])
def test_questions_about_elis_own_behaviour_are_recognised(text, about):
    assert sc.asks_about_own_behaviour(text) is about


def test_the_turn_describes_what_the_pipeline_did():
    line = sc.describe_turn({
        "via": "chat.long_question_guard",
        "retrieval": "keyword 8, semantic 0, documents 0, graph 0",
        "escalation": "searched the web, the results did not match the question, so declined to guess "
                      "(the question was classed as an outside fact and grounding was 0.26, below the 0.55 this mode needs)",
    })
    assert "routed by chat.long_question_guard (a long question, sent to chat)" in line
    assert "searched the web" in line and "grounding was 0.26" in line


def test_the_audit_row_carries_the_route_and_the_escalation(monkeypatch):
    from eli.kernel.engine import CognitiveEngine
    rows = []
    monkeypatch.setattr("eli.runtime.orchestrator_audit_ledger.record_turn_async", lambda **k: rows.append(k))
    facts = {"t0": time.perf_counter(), "meta": {"action": "CHAT"}, "via": "chat.long_question_guard",
             "escalation": "searched the web, the results did not match the question, so declined to guess",
             "executed_actions": ["WEB_SEARCH"]}
    me = SimpleNamespace(session_id="s", user_id="u", _turn_action=CognitiveEngine._turn_action)
    CognitiveEngine._record_turn_audit_row(me, facts, True, "ok")
    out = rows[0]["outcome"]
    assert out.startswith("ok; routed by chat.long_question_guard")
    assert "searched the web" in out and "also executed: WEB_SEARCH" in out


def test_escalating_to_the_web_is_written_on_the_turn(turn, monkeypatch):
    from eli.runtime import grounding_escalation as ge
    monkeypatch.setattr("eli.core.config.network_allowed", lambda *a, **k: True)
    monkeypatch.setattr("eli.execution.executor_enhanced.execute", lambda action, args=None, *a, **k: {
        "ok": True, "web_grounded": True, "results": [{"title": "Unrelated", "body": "nothing"}], "content": "x"})
    bus = SimpleNamespace(grounding_confidence=0.26, aggregated_confidence=0.26)
    out = ge.escalate(SimpleNamespace(), "who won the 2022 world cup final?", {"action": "CHAT"}, bus,
                      reasoning_mode="quick")
    assert out and out["meta"]["response_mode"] == "ungrounded_hedge"
    assert "searched the web" in turn["escalation"] and "grounding was 0.26" in turn["escalation"]


def test_asked_about_itself_eli_is_handed_the_record(monkeypatch):
    now = time.time()
    monkeypatch.setattr("eli.runtime.orchestrator_audit_ledger.flush", lambda *a, **k: True)
    monkeypatch.setattr("eli.runtime.orchestrator_audit_ledger.recent_turns", lambda *a, **k: [
        {"ts": now - 60, "elapsed_ms": 7000.0, "action": "CHAT", "reasoning_mode": "quick", "user_id": "u",
         "parent_request_id": "", "outcome": "ok; routed by chat.long_question_guard; searched the web, the results "
                                             "did not match the question, so declined to guess; also executed: WEB_SEARCH"},
        {"ts": now - 400, "elapsed_ms": 1000.0, "action": "CHAT", "reasoning_mode": "quick", "user_id": "someone-else",
         "parent_request_id": "", "outcome": "ok"},
    ])
    mem = SimpleNamespace(get_recent_conversation=lambda **k: [
        {"role": "user", "timestamp": now - 66, "content": "can you tell me what has been going on the past day or two?"}])
    block = sc.turn_record_block(mem, user_id="u", now=now)
    assert block.startswith("What you did on recent turns")
    assert "“can you tell me what has been going on" in block
    assert "searched the web" in block and "also executed: WEB_SEARCH" in block
    assert block.count("\n") == 1  # the other user's turn is not in it


RECORD = ["[today 18:34] “what has been going on the past day or two?” -> CHAT (quick, 1 s): ok; routed by "
          "chat.long_question_guard (a long question, sent to chat); retrieval: keyword 12, semantic 0, documents 0, "
          "graph 0; searched the web, the results did not match the question, so declined to guess (the question was "
          "classed as an outside fact and grounding was 0.26, below the 0.45 this mode needs)"]


@pytest.fixture()
def fault_turn():
    """A complaint about ELI, with the pipeline's record of the turn it is about."""
    facts = {"user_input": "YOU DO NOT NEED TO SEARCH THE FUCKING WEB FOR ANY OF THOSE QUESTIONS!!",
             "_record_lines": RECORD, "_record": "\n".join(RECORD)}
    token = rc.turn_facts_var.set(facts)
    yield facts
    rc.turn_facts_var.reset(token)


INVENTED_DIAGNOSES = [
    "The issues you are facing stem from a specific failure in how I align semantic memory with temporal memory.",
    "My command executor has no concept of concurrency or sequence.",
    "The system prioritized vibe over chronology.",
    "It ignored your explicit correction because its retrieval score for that specific entity was artificially high.",
    "It was a routing error where the deep dive request triggered an external retrieval agent instead of staying local.",
    "Netflix opened, but because there is no state tracking between commands, I didn't know it was open.",
    "The vector index prioritized recency of entity mention over conversational context.",
    "The embedding model decayed the context window’s relevance too quickly, allowing stale entities to bleed through.",
    "This suggests the temporal anchoring layer is not consistently syncing with the live system time.",
    "My attention mechanism latched onto that string because it was the last failed entity in the log buffer.",
    "Command queues are being dropped or executed out of order when multiple inputs arrive.",
    "It struggles with process cleanup and state synchronization between Spotify and system media keys.",
]


@pytest.mark.parametrize("sentence", INVENTED_DIAGNOSES)
def test_a_cause_the_record_does_not_show_is_not_served(sentence, fault_turn):
    """All six are from real replies. None of these mechanisms is in the record of the turn."""
    reply = f"You're right, that search was not needed. {sentence} The record shows grounding was 0.26."
    out = sc.drop_invented_self_claims(reply)
    assert sentence not in out
    assert "that search was not needed" in out and "grounding was 0.26" in out


def test_a_conclusion_drawn_from_a_dropped_sentence_goes_with_it(fault_turn):
    reply = ("The search ran at 18:34. The vector index conflates the two artists. That is why I told you Mos Def "
             "was on when he wasn't. Nothing else is recorded for that turn.")
    out = sc.drop_invented_self_claims(reply)
    assert "That is why" not in out and "The search ran at 18:34." in out and "Nothing else is recorded" in out


def test_a_reply_that_lost_its_explanations_says_so_and_gives_the_record(fault_turn):
    reply = ("You asked what had been going on and I searched the web for it. The vector index conflates the artists. "
             "My command executor has no concept of sequence. The system prioritized vibe over chronology. "
             "That search found nothing that matched.")
    out = sc.drop_invented_self_claims(reply)
    assert out.startswith("You asked what had been going on and I searched the web for it. That search found nothing")
    assert "I've left out what I can't back from my own records" in out and "grounding was 0.26" in out
    streamed = "".join(sc.gate_stream(reply[i:i + 7] for i in range(0, len(reply), 7)))
    assert "left out what I can't back" in streamed and "vector" not in streamed


def test_the_ledger_answer_reworded_by_the_model_is_held_to_its_rows(monkeypatch):
    from eli.runtime import personal_memory_deep_response as pm
    monkeypatch.setattr("eli.cognition.self_claims.turn_record_lines", lambda *a, **k: list(RECORD))
    facts = {"user_input": "why did you search the web for that?"}
    token = rc.turn_facts_var.set(facts)
    try:
        answer = pm.build_routing_fault_explanation(facts["user_input"])
        assert sc.drop_invented_self_claims(answer) == answer  # its own words are in its own record
        reworded = ("I searched the web because the question was classed as an outside fact and grounding was 0.26. "
                    "This happened because my attention mechanism latched onto the wrong entity.")
        out = sc.drop_invented_self_claims(reworded)
        assert "grounding was 0.26" in out and "attention mechanism" not in out
    finally:
        rc.turn_facts_var.reset(token)


def test_a_cause_that_is_in_the_record_is_served(fault_turn):
    reply = ("I searched the web because the question was classed as an outside fact and grounding was 0.26, "
             "below the 0.45 quick mode needs. Retrieval had found 12 keyword rows and nothing semantic.")
    assert sc.drop_invented_self_claims(reply) == reply


def test_the_users_own_technical_words_are_not_inventions(fault_turn):
    fault_turn["user_input"] = "you keep getting this wrong, is the vector index stale?"
    reply = "The record does not say the vector index is stale. It shows 12 keyword rows and no semantic ones."
    assert sc.drop_invented_self_claims(reply) == reply


def test_technical_talk_on_an_ordinary_turn_is_left_alone():
    token = rc.turn_facts_var.set({"user_input": "how do vector databases handle embedding drift?"})
    try:
        reply = ("Embedding drift happens when the model that built the vectors changes. The index goes stale because "
                 "old and new vectors are no longer comparable, so you re-index.")
        assert sc.drop_invented_self_claims(reply) == reply
    finally:
        rc.turn_facts_var.reset(token)


def test_a_config_file_that_does_not_exist_is_not_served(turn):
    reply = ("Every action is already in the ledger. If you want every function logged, we need to enable verbose "
             "logging in the executor config (`/home/nobody/.local/share/ELI_v2/config/logging.yaml`). "
             "Do you want me to find that file and show you how to turn it on?")
    out = sc.drop_invented_self_claims(reply)
    assert out == "Every action is already in the ledger."


def test_a_fix_eli_has_no_action_for_goes_with_the_offer_to_run_it(fault_turn):
    reply = ("The web search was not needed. The fix requires a hard reset on the media process manager and a "
             "re-indexing of the last 48 hours of memory. Want me to run that now?")
    out = sc.drop_invented_self_claims(reply)
    assert out.startswith("The web search was not needed.\n\nI've left out what I can't back from my own records")
    assert "hard reset" not in out and "Want me to run that now" not in out


def test_a_section_left_empty_loses_its_heading_and_lines_stay_lines(fault_turn):
    reply = ("**1. What the record shows**\n"
             "The turn was routed to chat and searched the web.\n\n"
             "**2. The Temporal Drift**\n"
             "* My memory index is failing to anchor events to the correct day.\n"
             "* The timestamp alignment logic is slipping.\n\n"
             "**3. Next**\n"
             "Ask again and it will be answered from the record.")
    out = sc.drop_invented_self_claims(reply)
    assert "Temporal Drift" not in out and "anchor" not in out and "alignment" not in out
    assert out.splitlines()[0] == "**1. What the record shows**"
    assert "searched the web.\n" in out and "**3. Next**\nAsk again" in out


def test_a_reply_that_is_all_invention_becomes_the_record(fault_turn):
    reply = ("The vector index prioritized recency over context. The embedding model decayed the context window. "
             "The fix requires re-indexing the last 48 hours.")
    out = sc.drop_invented_self_claims(reply)
    assert out.startswith("I won't guess at a cause or promise a change a reply can't make")
    assert "searched the web" in out and "vector" not in out


def test_elis_earlier_replies_are_not_evidence_for_what_it_says_now(turn):
    """An invented setting in the dialogue block licensed itself on the next turn."""
    prompt = ("[today 18:48] You: you should have logs\n"
              "[today 18:50] ELI: Option A: enable `verbose_media_logging` in your config.\n"
              "It writes every track change.\n"
              "[today 18:56] You: do it then")
    out = sc.drop_invented_self_claims("Every play is in the ledger already. Enabling `verbose_media_logging` adds "
                                       "nothing.", evidence=prompt)
    assert out == "Every play is in the ledger already."
    assert "verbose_media_logging" not in sc.without_own_prose(prompt) and "do it then" in sc.without_own_prose(prompt)


def test_a_question_about_elis_own_behaviour_is_never_web_searched(monkeypatch):
    from eli.runtime import grounding_escalation as ge
    ran = []
    monkeypatch.setattr("eli.core.config.network_allowed", lambda *a, **k: True)
    monkeypatch.setattr("eli.execution.executor_enhanced.execute", lambda action, *a, **k: ran.append(action) or {})
    bus = SimpleNamespace(grounding_confidence=0.1, aggregated_confidence=0.1)
    for text in ("why did you get that so wrong?", "YOU DO NOT NEED TO SEARCH THE WEB FOR THAT",
                 "what is with all the issues?"):
        assert ge.escalate(SimpleNamespace(), text, {"action": "CHAT"}, bus, reasoning_mode="quick") is None
    assert ran == []


@pytest.mark.parametrize("text", [
    "why did it take you so long to answer that, and what exactly did you do to answer it?",
    "why was that so slow?", "what did you just do?", "why did you search the web for that?",
])
def test_a_direct_question_about_the_last_turn_is_answered_from_the_ledger(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] == "ROUTING_FAULT_EXPLAIN"


@pytest.mark.parametrize("text", [
    "why did the chicken take so long to cook", "why is my laptop so slow", "what did you do yesterday?",
])
def test_other_questions_are_not_taken_for_one(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] != "ROUTING_FAULT_EXPLAIN"


def test_the_ledger_answer_gives_the_recorded_rows_and_no_more(monkeypatch):
    from eli.runtime import personal_memory_deep_response as pm
    monkeypatch.setattr("eli.cognition.self_claims.turn_record_lines", lambda *a, **k: list(RECORD))
    out = pm.build_routing_fault_explanation("why did you search the web for that?")
    assert "What the last turns did (from the audit ledger):" in out
    assert "grounding was 0.26" in out and "I won't guess one" in out
    assert "should be answered locally" not in out


def test_the_row_says_how_often_the_model_ran_and_on_how_much():
    line = sc.describe_turn({"via": "fallback.chat", "model_calls": 2, "prompt_chars": 30941})
    assert "model ran 2 times on 30,941 prompt characters" in line


def test_a_setting_or_table_eli_does_not_have_is_not_served(turn):
    reply = ("There is one entry for that date.\n"
             "I have scanned the raw action logs (`action_logs`) for 2026-10-02.\n"
             "Option A: Enable `verbose_media_logging` in your config.\n"
             "The ledger table is `runtime_events`.")
    out = sc.drop_invented_self_claims(reply)
    assert "verbose_media_logging" not in out and "action_logs" not in out
    assert "There is one entry" in out and "`runtime_events`" in out  # a real table stays


def test_a_name_that_is_in_the_evidence_stays(turn):
    reply = "The row came from `custom_plugin_table`, as the record shows. That is all there is."
    assert sc.drop_invented_self_claims(reply, evidence="rows read from custom_plugin_table") == reply


def test_code_the_user_asked_for_is_never_touched():
    token = rc.turn_facts_var.set({"user_input": "write me a function that parses a csv"})
    try:
        reply = "Here you go:\n```python\ndef verbose_media_logging():\n    pass\n```\nCall `parse_my_csv` with the path."
        assert sc.drop_invented_self_claims(reply) == reply
    finally:
        rc.turn_facts_var.reset(token)


@pytest.mark.parametrize("sentence", [
    "Consider it done.",
    "The audit trail is now active and persistent.",
    "I will enforce strict logging of every action going forward.",
    "I've enabled verbose logging for you.",
    "Do you want me to enable it now so we can test it?",
])
def test_reporting_a_change_nothing_made_is_dropped_unless_something_ran(sentence):
    reply = f"Every action I run is already written to the evidence ledger. {sentence} That is the whole of it."
    facts = {"user_input": "set a timer for ten minutes and log everything"}
    token = rc.turn_facts_var.set(facts)
    try:
        out = sc.drop_invented_self_claims(reply)
        assert sentence not in out and "already written to the evidence ledger" in out
        facts["executed_actions"] = ["SET_TIMER"]
        assert sentence in sc.drop_invented_self_claims(reply)
    finally:
        rc.turn_facts_var.reset(token)


def test_the_same_check_runs_on_a_streamed_reply(turn):
    reply = ("Every action I run is already in the ledger. Consider it done. The audit trail is now active. "
             "Option A: enable `verbose_media_logging`.\nYesterday you played My Mom at 18:08.\n"
             "```\nraw `made_up_name` in a code block stays\n```\nEnd.")
    out = "".join(sc.gate_stream(reply[i:i + 9] for i in range(0, len(reply), 9)))
    assert "Consider it done" not in out and "now active" not in out and "verbose_media_logging" not in out
    assert "already in the ledger" in out and "My Mom at 18:08" in out and "made_up_name" in out


def test_a_reply_that_is_nothing_but_claims_is_still_served(turn):
    reply = "Consider it done."
    assert "".join(sc.gate_stream([reply])) == reply
    assert sc.drop_invented_self_claims(reply) == reply


def test_buffered_replies_go_through_the_same_check(turn):
    from eli.cognition.output_governor import govern_output
    out = govern_output("Every action is already logged in the ledger. Consider it done. The audit trail is now active.")
    assert "Consider it done" not in out and "already logged" in out


def test_the_self_model_says_logging_is_always_on():
    import inspect
    from eli.runtime.awareness_boot import AwarenessState
    assert "Logging is always on" in inspect.getsource(AwarenessState._live_self_model)


def test_troubleshooting_eli_is_not_stored_as_the_users_work(tmp_path):
    """The session summary's "current work" once held ELI's own invented diagnosis, which then
    came back in every prompt as a recalled topic."""
    import sqlite3
    from eli.runtime import profile_extractor as pe
    db = tmp_path / "user.sqlite3"
    pe.ensure_profile_tables(db)
    con = sqlite3.connect(db)
    cur = con.cursor()
    quoted = ('you should be the one that corrects me -- "want a deep dive into why the vector search is drifting '
              '(likely the embedding model\'s decay on long-term context)" -> yes i want that')
    pe._route_summary_to_profile(cur, "CURRENT WORK: Analyzing the technical reasons behind vector search drift, "
                                      "comparing embedding model decay against short-term urgency.\n", user_text=quoted)
    pe._route_summary_to_profile(cur, "CURRENT WORK: Frustrated with ELI's memory and temporal awareness.\n",
                                 user_text="your memory is broken")
    assert cur.execute("select count(*) from user_patterns where pattern_type='project.current'").fetchone()[0] == 0
    pe._route_summary_to_profile(cur, "CURRENT WORK: Writing the harbour coursework pack on high-risk AI use cases.\n",
                                 user_text="here is the harbour coursework i am writing, a high-risk AI use case pack")
    assert "harbour" in cur.execute("select pattern_data from user_patterns where pattern_type='project.current'").fetchone()[0]
    con.close()


@pytest.mark.parametrize("sentence", [
    "No web search for future questions.",
    "I will rely solely on local context from now on.",
    "I won't search the web again going forward.",
    "I’ll stick to the local documentation and memory stores unless you explicitly ask otherwise.",
])
def test_a_standing_change_promised_in_a_reply_is_not_served(sentence, fault_turn):
    out = sc.drop_invented_self_claims(f"Understood. {sentence} The record shows that turn searched the web at 18:34.")
    assert sentence not in out and "searched the web at 18:34" in out
    # a complaint gets the record as soon as anything was left out
    assert "What the audit ledger holds for the last turns" in out and "grounding was 0.26" in out


def test_a_heading_that_names_an_unrecorded_cause_goes_and_its_section_stays(fault_turn):
    reply = ("### The Core Issue: Temporal Drift & Context Bleed\n"
             "That turn was routed to chat and searched the web.\n")
    out = sc.drop_invented_self_claims(reply)
    assert "Core Issue" not in out and out.startswith("That turn was routed to chat and searched the web.")


@pytest.mark.parametrize("text", [
    "how fast does a serious incident involving the crane-scheduling model have to be reported, and who files it?",
    "should a formal complaint be made about this?",
    "what would be a playful name to use for a cat?",
])
def test_a_tone_word_elsewhere_in_a_question_does_not_set_the_tone(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] != "SET_TONE"


@pytest.mark.parametrize("text", ["be more serious", "use a sarcastic tone", "keep it professional please",
                                  "eli, be playful", "can you be more cheerful", "I want you to be formal"])
def test_a_tone_asked_for_is_still_set(text):
    from eli.execution.router_enhanced import route
    assert route(text)["action"] in ("SET_TONE", "SET_COMMUNICATION_STYLE")


# A summary of a period writes only about days that have something in them.
#
# Live: "summarise the past 5 days" got a "Wednesday, 7 October" section full of things said on the
# Thursday; nothing at all was said that Wednesday. Asked "are you making that up?", ELI said no.
def _t(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))


WINDOW = (_t("2026-10-03 00:00"), _t("2026-10-08 21:48"))
RECORDED = ["2026-10-03", "2026-10-05", "2026-10-06", "2026-10-08"]
REPLY = """### Summary of the past 5 days

**Thursday, 8 October 2026**
- You asked about the show you are watching.

---

**Wednesday, 7 October 2026**
- Repeated questions about a show.
- A long talk about the calendar.

---

**Monday, 5 October 2026**
- You planned a presentation."""


@pytest.fixture
def period():
    token = turn_facts_var.set({"user_input": "summarise what we discussed over the past 5 days",
                                "_period_window": WINDOW, "_period_days": RECORDED})
    yield
    turn_facts_var.reset(token)


def test_a_day_with_nothing_recorded_loses_its_whole_section(period):
    out = self_claims.drop_invented_self_claims(REPLY)
    assert "Wednesday" not in out.split("Nothing is recorded")[0]
    assert "calendar" not in out and "Repeated questions" not in out
    assert "Thursday, 8 October" in out and "Monday, 5 October" in out
    assert out.strip().endswith("Nothing is recorded on Wednesday 7 October.")


def test_the_same_when_the_sections_run_together(period):
    flat = REPLY.replace("\n\n---\n\n", " --- ")
    out = self_claims.drop_invented_self_claims(flat)
    assert "Repeated questions" not in out and "planned a presentation" in out


def test_days_are_read_from_names_and_dates():
    from eli.cognition.query_planner import days_named
    assert days_named("On Wednesday you asked", WINDOW) == ["2026-10-07"]
    assert days_named("**Tuesday, 6 October 2026**", WINDOW) == ["2026-10-06"]
    assert days_named("Oct 5th and 2026-10-03", WINDOW) == ["2026-10-05", "2026-10-03"]
    assert days_named("in 2025 on 7 March", WINDOW) == []


def test_without_a_period_nothing_is_checked():
    assert self_claims.drop_invented_self_claims(REPLY).count("Wednesday") == 1


def test_asking_if_it_was_made_up_is_a_challenge():
    assert self_claims.complains_about_eli("Are you making that up? where are my timestamps")
