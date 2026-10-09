"""The 2026-10-03 18:32 session on 2.5.1: memory, identity, web and orchestration faults.

Each test is one of them, reproduced from the user's own database and log:
  - "If my name is listed as unknown, ..." renamed the user "listed"
  - a model-guessed PERSONA_LOCK_CLEAR ran before the turn fell back to chat, and the
    audit row said CHAT
  - quick mode threw away every turn found for "yesterday"; deep modes had them but the
    prompt said "ground user-specific claims ONLY from these rows"; the action ledger with
    every song played was never read
  - "what has been going on the past day or two?" was web-searched
  - "check again in full" lost the period of the question before it
  - restored working-memory pins from 59 days ago were shown as this session's facts
  - the tone reader called a furious "!!" ecstatic
  - "what date is it, and how many days ago was 09-09-2026" got only the date
"""
from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import pytest

DAY = 86400.0


# ── identity ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "If my name is listed as unknown, then why the fuck did you not do the onboarding setups so you would know my name?",
    "my name is not fucking listed!!! You have over 500 memories stored",
    "my name is listed",
    "what if my name is Bob?",
    "You know my name, check your memory. What is my name?",
])
def test_talking_about_a_name_is_not_giving_one(text):
    from eli.runtime.identity_validation import extract_explicit_identity_facts
    from eli.execution.router_enhanced import route
    assert extract_explicit_identity_facts(text) == {}
    assert route(text)["action"] != "SET_USER_NAME"


@pytest.mark.parametrize("text,name", [
    ("my name is Morgan", "Morgan"),
    ("hi, my name is morgan and i work in tech", "morgan"),
    ("call me Sam please", "Sam"),
    ("my name is speak, my name is alex", "alex"),
    ("if you forget, my name is Morgan", "Morgan"),
])
def test_real_declarations_still_set_the_name(text, name):
    from eli.execution.router_enhanced import route
    r = route(text)
    assert r["action"] == "SET_USER_NAME" and r["args"]["name"] == name


def test_a_stored_junk_name_is_not_reported_and_cannot_be_set():
    from eli.kernel.state import _clean_name
    from eli.execution.executor_enhanced import set_user_name
    assert _clean_name("listed") == ""
    assert set_user_name("listed")["ok"] is False


def test_the_graph_only_learns_a_real_name(tmp_path, monkeypatch):
    from eli.memory.knowledge_graph import KnowledgeGraph, _junk_name_relation
    kg = KnowledgeGraph(db_path=tmp_path / "kg.sqlite3")
    kg.extract_from_memory("If my name is listed as unknown, then why did you not ask?", source="user")
    kg.extract_from_memory("my name is not fucking listed!!!", source="user")
    names = [r["object"] for r in (kg.query_entity("User") or {}).get("outbound", [])
             if r.get("predicate") == "has_name"]
    assert names == []
    kg.extract_from_memory("my name is Morgan", source="user")
    names = [r["object"] for r in (kg.query_entity("User") or {}).get("outbound", [])
             if r.get("predicate") == "has_name"]
    assert names == ["Morgan"]
    assert _junk_name_relation({"predicate": "has_name", "object": "not fucking listed"})
    assert not _junk_name_relation({"predicate": "has_name", "object": "Morgan"})


def test_what_is_my_name_gets_a_name_not_a_database_dump(monkeypatch):
    from eli.runtime import deterministic_introspection as di
    monkeypatch.setattr("eli.kernel.state.get_user_name", lambda *a, **k: "Morgan")
    assert di.handle_diagnostic_action("USER_IDENTITY_SUMMARY", "what is my name?") == "Your name is Morgan."
    monkeypatch.setattr("eli.kernel.state.get_user_name", lambda *a, **k: "")
    out = di.handle_diagnostic_action("USER_IDENTITY_SUMMARY", "what is my name?")
    assert "don't have your name" in out and "db" not in out.lower()


# ── actions that ran must be on the record ───────────────────────────────────

def test_an_action_the_bus_ran_is_in_the_audit_row(monkeypatch):
    from eli.kernel import request_context as rc
    from eli.kernel.engine import CognitiveEngine
    from eli.execution import executor_enhanced as ex
    facts = {"user_input": "Eli, can you not tell me who i am??", "t0": time.perf_counter(),
             "meta": {"action": "CHAT"}}
    token = rc.turn_facts_var.set(facts)
    try:
        ex._action_post_dispatch("PERSONA_LOCK_CLEAR", {}, {"ok": True, "content": "Persona lock cleared."})
    finally:
        rc.turn_facts_var.reset(token)
    assert facts["executed_actions"] == ["PERSONA_LOCK_CLEAR"]
    rows = []
    monkeypatch.setattr("eli.runtime.orchestrator_audit_ledger.record_turn_async", lambda **k: rows.append(k))
    me = SimpleNamespace(session_id="s", user_id="u", _turn_action=CognitiveEngine._turn_action)
    CognitiveEngine._record_turn_audit_row(me, facts, True, "ok")
    assert rows[0]["action"] == "CHAT"
    assert "also executed: PERSONA_LOCK_CLEAR" in rows[0]["outcome"]


# ── recall of a period ───────────────────────────────────────────────────────

@pytest.fixture()
def period_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    from eli.memory.memory import Memory
    from eli.runtime.evidence_ledger import ensure_schema
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    y = time.time() - DAY
    c = sqlite3.connect(mem.db_path)
    ensure_schema(c)
    for i, (role, text) in enumerate([("user", "play head honcho by eminem on spotify"),
                                      ("assistant", "Sure, here's a long made-up story about your day"),
                                      ("user", "what is currently playing?")]):
        c.execute("insert into conversation_turns (session_id, user_id, role, content, ts, timestamp) "
                  "values ('s', 'u', ?, ?, ?, ?)", (role, text, y + i * 60, y + i * 60))
    for i, (action, content) in enumerate([("PLAY_MEDIA", "Playing “head honcho eminem” on Spotify."),
                                           ("NOW_PLAYING", "▶ Playing: Eminem — Bagpipes From Baghdad — spotify.")]):
        c.execute("insert into runtime_events (ts, timestamp, event_type, source, action, content, outcome) "
                  "values (?, ?, 'executor_action', 'executor.post_dispatch', ?, ?, 'ok')",
                  (y + i * 60 + 5, y + i * 60 + 5, action, content))
    c.commit()
    c.close()
    return mem


def test_the_period_log_has_the_users_turns_and_every_action_ran(period_memory):
    from eli.cognition.query_planner import parse_window
    from eli.memory.retrieval import retrieve_for_turn
    from eli.memory.unified_retrieval import format_period_log
    q = "can you name all of the songs i played yesterday?"
    tr = retrieve_for_turn(period_memory, q, window=parse_window(q), use_cache=False)
    assert len(tr.actions) == 2
    log = format_period_log(tr, q)
    assert "Bagpipes From Baghdad" in log and "ELI ran PLAY_MEDIA" in log
    assert "play head honcho by eminem" in log
    assert "made-up story" not in log  # ELI's own prose is never recalled as history


def test_quick_mode_keeps_the_period(period_memory):
    """need_semantic=False (quick) used to drop the period's turns with the semantic hits."""
    from eli.cognition.query_planner import parse_window
    from eli.memory.unified_retrieval import format_period_log, orchestrator_retrieve
    q = "what songs did i play yesterday?"
    eng = SimpleNamespace(memory=period_memory, session_id="s", user_id="u")
    kw, sem, tr = orchestrator_retrieve(eng, q, q, {"need_keyword": True, "need_semantic": False,
                                                    "window": parse_window(q)})
    assert "head honcho" in format_period_log(tr, q)
    assert not any(h["source"] == "conversation" for h in sem)  # once, in the log


def test_a_long_period_keeps_actions_and_what_was_asked_about():
    from eli.memory.retrieval import TurnRetrievalResult
    from eli.memory.unified_retrieval import format_period_log
    t0 = time.time() - DAY
    turns = [{"role": "user", "content": f"unrelated chatter number {i} about nothing much at all",
              "timestamp": t0 + i} for i in range(300)]
    turns.append({"role": "user", "content": "play my mom by eminem on spotify", "timestamp": t0 + 500})
    tr = TurnRetrievalResult(conv_hits=turns, window_stats={"since": t0, "until": t0 + DAY},
                             actions=[{"ts": t0 + 501, "action": "PLAY_MEDIA",
                                       "content": "Playing “my mom eminem” on Spotify.", "outcome": "ok"}])
    log = format_period_log(tr, "name the songs i played on spotify", max_chars=2000)
    assert len(log) < 2600
    assert "my mom" in log and "Showing" in log


def test_the_memory_header_no_longer_tells_the_model_to_ignore_the_period_log():
    from eli.memory.unified_retrieval import VERIFIED_SCOPE_NOTE
    assert "ONLY" not in VERIFIED_SCOPE_NOTE and "period log" in VERIFIED_SCOPE_NOTE


def test_the_period_log_survives_trimming_before_other_memory():
    from eli.cognition.context_budget import _rank
    assert _rank("What happened in that period (Fri)") < _rank("Verified stored memories (3)")


def test_a_follow_up_keeps_the_period_it_follows():
    from eli.cognition.orchestrator import _followup_window
    store = {}
    eng = SimpleNamespace(_sticky_get=lambda k, d=None: store.get(k, d),
                          _sticky_set=lambda k, v: store.__setitem__(k, v))
    w = (1.0, 2.0)
    assert _followup_window(eng, "name all the songs i played yesterday", w) == w
    assert _followup_window(eng, "you should have logs of every song played, please check again in full", None) == w
    assert _followup_window(eng, "hey, how are you?", None) is None


def test_a_vector_entry_is_found_by_either_id_key_and_telemetry_is_not_reindexed():
    from eli.memory.vector_store import _embeddable_sql, _entry_id
    assert _entry_id({"memory_id": 7}) == 7 and _entry_id({"id": 8}) == 8
    c = sqlite3.connect(":memory:")
    c.execute("create table memories (id integer, text text, origin text)")
    assert "telemetry" in _embeddable_sql(c)


# ── working memory ───────────────────────────────────────────────────────────

def test_recalled_pins_do_not_carry_over_or_flood_the_prompt(tmp_path):
    from eli.cognition.working_memory import WorkingMemory, MAX_AGE_SECONDS
    db = str(tmp_path / "wm.sqlite3")
    wm = WorkingMemory()
    wm.pin("i got high and played xcom 2 last night", source="memory_recall", importance=0.9,
           ts=time.time() - 24 * DAY)
    wm.pin("User's name is Morgan", source="identity", importance=0.9)
    old = wm._facts[wm._key("User's name is Morgan")]
    wm.persist(db)
    wm2 = WorkingMemory()
    assert wm2.restore(db) == 1 and wm2._key("User's name is Morgan") in wm2._facts
    old.last_hit_ts = time.time() - MAX_AGE_SECONDS - 60
    wm.persist(db)
    assert WorkingMemory().restore(db) == 0  # unused for longer than the backstop
    block = wm.context_block()
    assert "said" in block and "pinned 24d ago" not in block
    for _ in range(3):
        wm.advance_turn()
    assert "xcom" not in wm.context_block()


# ── web search, tone, dates ──────────────────────────────────────────────────

def test_a_recap_of_the_users_own_days_is_not_a_web_question():
    from eli.runtime.grounding_escalation import classify_factual
    assert classify_factual("can you tell me what has been going on the past day or two? "
                            "What is with all the issues?") == (False, "none")
    assert classify_factual("what is going on in Ukraine?") == (True, "external")


def test_a_personal_period_question_with_its_own_log_skips_the_web(monkeypatch):
    from eli.cognition import orchestrator as orch
    monkeypatch.setattr("eli.runtime.grounding_escalation.escalate",
                        lambda *a, **k: pytest.fail("escalated a question its period log answers"))
    me = SimpleNamespace(engine=SimpleNamespace(_crisis_steering=None),
                         memory_agent=SimpleNamespace(_last_turn_retrieval=SimpleNamespace(
                             window_stats={"in_window": 0, "turns": 31, "actions": 20})))
    assert orch.AgentOrchestrator._maybe_grounding_escalate(
        me, SimpleNamespace(trace={}), "what songs did i play yesterday?", {}, stream=True,
        reasoning_mode="quick") is None
    assert not orch._PERSONAL_RE.search("can you tell me who won the match yesterday?")


def test_the_merge_uses_the_plans_cap():
    import inspect
    from eli.cognition.orchestrator import AgentOrchestrator
    assert 'retrieval_plan.get("merge_cap")' in inspect.getsource(AgentOrchestrator.run)


@pytest.mark.parametrize("text,emo", [
    ("YOU DO NOT NEED TO SEARCH THE FUCKING WEB FOR ANY OF THOSE QUESTIONS!!", "angry"),
    ("Why the fuck are you lying to me and making shit up?", "angry"),
    ("i asked you a fucking question Eli!!", None),
    ("I'm so excited let's go!!!", "ecstatic"),
])
def test_tone_reads_anger_and_does_not_call_shouting_joy(text, emo):
    from eli.cognition.tone_adaptor import detect_text_emotion
    assert detect_text_emotion(text)[0] == emo


def test_tone_and_dates_read_the_users_message_not_the_history_before_it():
    from eli.cognition.evidence_format import latest_user_message
    assert latest_user_message("[Recent]\nYou: SHOUTING!!\n\nYou: calm question") == "calm question"


def test_dates_the_user_writes_come_with_the_days_worked_out():
    from eli.cognition.evidence_format import date_facts
    now = time.mktime(time.strptime("2026-10-03 19:01", "%Y-%m-%d %H:%M"))
    f = date_facts("tell me how many days ago the 09-09-2026 was?!?!?", now)
    assert "Wednesday 09 September 2026, 24 days before today" in f
    assert "reads two ways" in date_facts("what did we do on 10-03-2026", now)
    assert date_facts("hello there", now) == ""


def test_a_date_inside_a_not_clause_is_not_the_period():
    from eli.cognition.query_planner import parse_window
    w = parse_window("Give me your exact memory and timestamps over the past 3 days "
                     "(3 DAYS WHICH DOES NOT MEAN GIVING ME FUCKING LOGS FROM THE 09-25-2026!!!)")
    assert w and w[1] - w[0] > 2 * DAY


def test_a_date_question_that_also_asks_for_arithmetic_goes_to_chat():
    from eli.execution.router_enhanced import route
    assert route("What fucking date is it today Eli, and tell me how many days ago the 09-09-2026 was?")["action"] == "CHAT"
    assert route("what is the date?")["action"] == "DATE"


# ── one copy of each line per prompt ─────────────────────────────────────────

def test_the_prompt_carries_each_memory_and_dialogue_line_once():
    from eli.cognition.prompt_dedupe import dedupe_prompt_parts
    mem = ("Verified stored memories (1 found):\n"
           "  - [memory_id=1 status=verified] [2026-10-02 18:43] Uses Spotify for music (listens to Eminem).\n\n"
           "Reranked evidence:\n"
           "01. [fts5 | 2026-10-02 Fri, yesterday | score=1.300] Uses Spotify for music (listens to Eminem).")
    brief = ("RECENT DIALOGUE (timestamped):\n"
             "- [today 19:40] user: can you tell me what has been going on the past day or two?\n"
             "INTENT ACTION: CHAT\n\nGROUNDED FACTS:\n"
             "- 01. [fts5 | 2026-10-02 Fri, yesterday | score=1.300] Uses Spotify for music (listens to Eminem).\n\n"
             "FINAL INSTRUCTION:\nWrite ONE direct answer.")
    prompt = "[today 19:40] You: can you tell me what has been going on the past day or two?\n\nYou: next"
    m, b = dedupe_prompt_parts(mem, brief, others=(prompt,))
    assert m.count("Uses Spotify") == 1 and "Reranked evidence" not in m
    assert "Uses Spotify" not in b and "GROUNDED FACTS" not in b and "RECENT DIALOGUE" not in b
    assert "FINAL INSTRUCTION" in b and "INTENT ACTION: CHAT" in b


def test_old_json_envelopes_stay_out_of_recent_conversation():
    from eli.runtime.persistence_gate import is_internal_report_dump
    assert is_internal_report_dump('{ "surface": "control_result_without_visible_synthesis", "action": "META_DIAGNOSTIC" }')


def test_reliability_is_not_phrased_as_a_count():
    import inspect
    from eli.runtime.awareness_boot import AwarenessState
    src = inspect.getsource(AwarenessState._reliability_line)
    assert "of {b['n']} runs" not in src and "chance of success" in src


def test_another_user_is_not_shown_the_owners_actions(tmp_path):
    """Shared installs: the action log in a period answer is the asker's own. Rows that name
    no user (the desktop owner's, and everything recorded before rows carried one) go to the
    owner only."""
    from eli.runtime.evidence_ledger import actions_between, record_event
    db = tmp_path / "user.sqlite3"
    now = time.time()
    record_event("executor_action", action="PLAY_MEDIA", content="owner's song", outcome="ok",
                 db_path=db, timestamp=now - 30)
    record_event("executor_action", action="OPEN_APP", content="alice's app", outcome="ok",
                 user_id="alice", db_path=db, timestamp=now - 20)
    seen = lambda **k: [a["content"] for a in actions_between(now - 60, now, db_path=db, **k)]
    assert seen() == ["owner's song", "alice's app"]
    assert seen(user_id="alice", include_unattributed=False) == ["alice's app"]
    assert seen(user_id="owner-id", include_unattributed=True) == ["owner's song"]


def test_a_mood_or_an_activity_is_not_what_the_user_is(tmp_path):
    """44 of the user's 83 graph relations were "User is_a going to bed now"-style rows."""
    from eli.memory.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=tmp_path / "kg.sqlite3")
    for text in ("I'm going to bed now, i am just checking in", "i'm not happy to be honest",
                 "I am a software developer."):
        kg.extract_from_memory(text, source="user")
    facts = [(r["predicate"], r["object"]) for r in (kg.query_entity("User") or {}).get("outbound", [])]
    assert facts == [("is_a", "software developer")]


_CLOCK = ("CURRENT TIME (authoritative — trust this over any assumption about the time of day): "
          "Saturday 03 October 2026, 18:34 IST (evening). Night is 21:00-05:00, morning 05:00-12:00, "
          "afternoon 12:00-17:00, evening 17:00-21:00. Do not guess the time, the timezone, or the "
          "part of day. You always know today's weekday and calendar date from this value — never "
          "claim you don't track dates or don't know what day it is.")


def _chunks(text, n=7):
    return (text[i:i + n] for i in range(0, len(text), n))


def test_a_reply_that_opens_by_reciting_its_instructions_has_that_cut():
    """On the real 35B model a quick reply began with the clock paragraph of its own prompt.
    The opening is stripped as it streams; nothing is regenerated."""
    from eli.kernel.engine import _instruction_sentences, _stream_holding_back_repeats
    leak = _instruction_sentences("GROUNDING PACKAGE FOR ELI\n" + _CLOCK + "\n- [today 19:40] user: hi")
    reply = ("Friday 02 October 2026, 18:34 IST (evening). Night is 21:00-05:00, morning 05:00-12:00, "
             "afternoon 12:00-17:00, evening 17:00-21:00. Do not guess the time, the timezone, or the "
             "part of day. You always know today's weekday and calendar date from this value — never "
             "claim you don't track dates or don't know what day it is.\n\n"
             "Here are the tracks confirmed as playing in that log:\n1. Eminem – My Mom (18:08)")
    out = "".join(_stream_holding_back_repeats(_chunks(reply), [], allow_retry=True, leak=leak))
    assert out.startswith("Here are the tracks confirmed")
    assert "Night is 21:00" not in out and "My Mom (18:08)" in out


def test_an_ordinary_reply_is_streamed_untouched_with_the_leak_guard_on():
    from eli.kernel.engine import _instruction_sentences, _stream_holding_back_repeats
    leak = _instruction_sentences(_CLOCK)
    for reply in ("Yesterday you played My Mom by Eminem at 18:08 and Bagpipes From Baghdad at 18:17. "
                  "Later there was Mos Def's Sunshine, paused at 18:24, and Don Martin at 19:37. " * 2,
                  "Yes."):
        assert "".join(_stream_holding_back_repeats(_chunks(reply), [], allow_retry=True, leak=leak)) == reply


def test_the_resolver_does_not_answer_date_arithmetic_with_the_bare_date(monkeypatch):
    """Real-model replay: the router passed the compound question on and the resolver chose DATE."""
    import json
    from eli.cognition import llm_intent

    class _FakeGGUF:
        @staticmethod
        def chat_completion(*_a, **_k):
            return json.dumps({"action": "DATE", "args": {}, "confidence": 0.85})

    monkeypatch.setattr(llm_intent, "gguf_inference", _FakeGGUF)
    monkeypatch.setattr(llm_intent, "_GRAMMAR_CACHE", {})
    monkeypatch.setattr(llm_intent, "_cache", {})
    q = "What date is it today Eli, and tell me how many days ago the 09-09-2026 was?"
    assert llm_intent.parse_with_llm(q)["action"] == "CHAT"
    assert llm_intent.parse_with_llm("what's the date today")["action"] == "DATE"


def test_the_actions_a_question_is_about_come_first(period_memory):
    """Real-model replay: with five plays spread through a fifty-line log, the 35B model named
    four. Listed first and on their own, none is skipped."""
    from eli.cognition.query_planner import parse_window
    from eli.memory.retrieval import retrieve_for_turn
    from eli.memory.unified_retrieval import format_period_log
    q = "can you name all of the songs i played yesterday?"
    log = format_period_log(retrieve_for_turn(period_memory, q, window=parse_window(q), use_cache=False), q)
    focus, rest = log.split("Everything else said and done in that period:")
    assert "The 2 actions the question is about" in focus
    assert "Bagpipes From Baghdad" in focus and "head honcho eminem" in focus
    assert "what is currently playing?" in rest and "ELI ran" not in rest
    assert "action ledger, which records every action ELI runs" in log
    # a question about nothing in particular keeps one plain chronological list
    plain = format_period_log(retrieve_for_turn(period_memory, "what happened yesterday?",
                                                window=parse_window("what happened yesterday?"),
                                                use_cache=False), "what happened yesterday?")
    assert "the question is about" not in plain


def test_the_distinct_tracks_are_worked_out_for_the_model():
    """Real-model replay: given the seven media rows the model listed three tracks. The list is
    computed from the executor's own result formats, with a count."""
    from eli.memory.unified_retrieval import _tracks_in
    rows = [(1.0, 'ELI ran PLAY_MEDIA: I opened the Spotify search for “head honcho eminem” but couldn\'t confirm it started playing', True, "PLAY_MEDIA"),
            (2.0, "ELI ran PLAY_MEDIA: Playing “head honcho eminem” on Spotify.", True, "PLAY_MEDIA"),
            (3.0, "ELI ran NOW_PLAYING: ▶ Playing: Eminem — Bagpipes From Baghdad — spotify.", True, "NOW_PLAYING"),
            (4.0, "ELI ran PAUSE_MEDIA: ⏸ Paused — spotify (Eminem — Bagpipes From Baghdad)", True, "PAUSE_MEDIA"),
            (5.0, "ELI ran PAUSE_MEDIA: ⏸ Paused — spotify (Mos Def — Sunshine)", True, "PAUSE_MEDIA"),
            (6.0, "ELI ran PLAY_MEDIA: Playing “the point of no return immortal technique” on Spotify.", True, "PLAY_MEDIA"),
            (7.0, "ELI ran NEXT_MEDIA: ⏭ Next track — spotify (Immortal Technique — Point Of No Return)", True, "NEXT_MEDIA"),
            (8.0, "ELI ran PLAY_MEDIA: I opened the Spotify search for “liked” but playback didn't start", True, "PLAY_MEDIA")]
    out = _tracks_in(rows, lambda ts: f"t{int(ts)}")
    assert out.startswith("Distinct tracks in those actions (5):")
    assert "t2 “head honcho eminem”" in out                      # timed from the confirmed play
    assert out.count("Bagpipes From Baghdad") == 1 and "Mos Def — Sunshine" in out
    assert "t6 Immortal Technique — Point Of No Return" in out   # request and player title merged
    assert "“liked” (search opened, playback not confirmed)" in out


def test_a_junk_relation_an_old_extractor_stored_stays_out_from_either_side(tmp_path):
    """Stored before the extractor was fixed, "User is_a saying your memory is fine now" was hidden
    from the user's side but printed from the value's side, in a recall reply (2026-10-09)."""
    from eli.memory.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=tmp_path / "kg.sqlite3")
    kg.add_relation("User", "is_a", "saying your memory is fine now")
    kg.add_relation("User", "lives_in", "Bristol")
    text = kg.context_for_prompt("saying your memory is fine now") + kg.context_for_prompt("memory")
    assert "saying your memory" not in text
    assert "Bristol" in kg.context_for_prompt("Bristol")
