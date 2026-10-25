"""Failures found in a live session: recall answered from runtime internals, a screen question answered from chat,
GPU memory read as conversational memory, a file spec written literally, and store confirmations that were not receipts."""
import pytest

from eli.execution.router_enhanced import route

RECALL = ("Earlier I gave you a fictional validation fact involving a lighthouse and a bird. Without me restating it, "
          "what were the code and the bird? Explain whether you recalled this from stored memory or only from the "
          "current conversation context.")


def test_recalling_content_is_not_a_question_about_memory_internals():
    r = route(RECALL)
    assert r["action"] not in ("EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME", "PERSONAL_MEMORY_DEEP_EXPLAIN")


def test_asking_how_memory_works_still_reaches_the_internals_report():
    assert route("Explain how your memory system works internally, which db tables and functions")["action"] == "EXPLAIN_MEMORY_RUNTIME"


def test_gpu_memory_temperature_is_hardware_status():
    q = ("Tell me the current temperature of my GPU memory chips in degrees Celsius. Also, you do know the model "
         "that you are running on, it should be in your runtime, or a function/tool that you could call?")
    assert route(q)["action"] == "GPU_STATUS"


@pytest.mark.parametrize("q", [
    "Look at my screen. Is there a large purple triangle visible anywhere? Answer yes or no and briefly state where you looked. Do not assume.",
    "Is there a large purple triangle visible anywhere on my screen right now? Please answer yes or no and say where you looked",
    "what do you see on my screen right now, can you describe all of the windows that are open and what they contain please?",
])
def test_questions_about_the_screen_read_the_screen(q):
    assert route(q)["action"] == "SCREEN_READ_ANALYZE"


def test_a_long_question_that_only_mentions_a_screen_still_goes_to_chat():
    q = "Why did the meeting on my screen yesterday matter, and how do you think we should plan the next steps carefully?"
    assert route(q)["action"] == "CHAT"


def test_store_this_fact_in_memory_stores_only_the_fact():
    r = route("Please store this fact in memory: The validation lighthouse code is ORCHID-7319 and the fictional bird is "
              "a silver kestrel. Then confirm whether it was stored and in what kind of memory.")
    assert r["action"] == "MEMORY_STORE"
    assert r["args"]["text"] == "The validation lighthouse code is ORCHID-7319 and the fictional bird is a silver kestrel"


@pytest.mark.parametrize("spec,expected", [
    ("exactly three lines: alpha=17, beta=29, sum=46", "alpha=17\nbeta=29\nsum=46\n"),
    ("exactly three lines: alpha=17 beta=29 sum=46", "alpha=17\nbeta=29\nsum=46\n"),
    ("two lines: hello and goodbye", "hello\ngoodbye\n"),
    ("plain text content", "plain text content"),
    ("exactly 3 lines: a, b", "exactly 3 lines: a, b"),
])
def test_a_line_spec_becomes_those_lines(spec, expected):
    from eli.execution.executor_enhanced import _content_from_line_spec
    assert _content_from_line_spec(spec) == expected


def test_create_file_writes_the_lines_and_says_how_many(tmp_path, monkeypatch):
    from eli.execution import executor_enhanced as ex
    monkeypatch.setenv("ELI_ALLOW_ROOTS", str(tmp_path))
    r = ex.execute("CREATE_FILE", {"path": str(tmp_path / "t.txt"), "content": "exactly three lines: alpha=17, beta=29, sum=46"})
    assert r["ok"] and r["lines"] == 3 and "3 lines" in r["response"]
    assert (tmp_path / "t.txt").read_text() == "alpha=17\nbeta=29\nsum=46\n"


def test_a_store_receipt_names_the_row_and_a_rejection_says_so(tmp_path, monkeypatch):
    from eli.execution import executor_enhanced as ex
    from eli.memory.memory import Memory
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    monkeypatch.setattr("eli.memory.get_memory", lambda *a, **k: mem)
    monkeypatch.setattr(ex, "_get_memory_path", lambda: tmp_path / "user.sqlite3")
    ok = ex.execute("MEMORY_STORE", {"text": "The garage code is 4471 and the spare key is under the blue pot"})
    assert ok["ok"] and "row" in ok["response"] and "4471" in ok["response"]
    monkeypatch.setattr(mem, "store_memory", lambda **k: {"ok": True, "skipped": True, "reason": "persistence_gate"})
    no = ex.execute("MEMORY_STORE", {"text": "haha lol"})
    assert no["ok"] is False and "Not stored" in no["response"]


def test_gpu_status_names_the_model_and_the_requested_versus_effective_load(tmp_path, monkeypatch):
    import json
    from eli.execution import executor_enhanced as ex
    snap = {"model_name": "Qwen3.6-35B-A3B-Q4_K_M.gguf", "model_path": "/models/Qwen3.6-35B-A3B-Q4_K_M.gguf", "n_ctx": 12022,
            "n_gpu_layers": 8, "n_batch": 192, "n_threads": 10, "load_mode": "GPU",
            "requested": {"n_ctx": 12022, "n_gpu_layers": 8, "n_batch": 192},
            "effective": {"n_ctx": 12022, "n_gpu_layers": 8, "n_batch": 192}}
    (tmp_path / "runtime_snapshot.json").write_text(json.dumps(snap))
    monkeypatch.setattr(ex, "get_paths", lambda: type("P", (), {"artifacts_dir": tmp_path})())
    monkeypatch.setattr("eli.core.hardware_profile.get_live_gpu_telemetry", lambda: {"ok": False})
    text = ex._gpu_status_report()["content"]
    assert "model: Qwen3.6-35B-A3B-Q4_K_M.gguf" in text and "model file: /models/" in text
    assert "requested: ctx=12022 gpu_layers=8 batch=192; effective: ctx=12022 gpu_layers=8 batch=192" in text


def test_a_question_about_runtime_is_not_a_stance():
    from eli.cognition.stance_capture import detect_stance
    q = "Tell me the exact model, effective context size, GPU layers, batch size and VRAM you are running with."
    assert detect_stance(q, "I do not have the model path in the evidence, so I cannot say which file is loaded right now.") is None
    assert detect_stance("what do you think about machine consciousness and free will?",
                         "I do not believe machine consciousness follows from fluent language alone, whatever the output looks like.") is not None


@pytest.mark.parametrize("q,query", [
    ("forget that my locker number is 212", "my locker number is 212"),
    ("Please forget what I told you about Priya", "Priya"),
    ("erase what you know about my old address", "my old address"),
    ("delete the memory about the garage code", "the garage code"),
])
def test_a_request_to_forget_names_what_to_forget(q, query):
    r = route(q)
    assert r["action"] == "MEMORY_FORGET" and r["args"]["query"] == query


@pytest.mark.parametrize("q", ["forget it", "delete the file notes.txt", "forget everything about me"])
def test_vague_or_file_requests_are_not_memory_deletions(q):
    assert route(q)["action"] != "MEMORY_FORGET"


def test_forgetting_asks_first_and_deletes_only_on_confirmation(tmp_path, monkeypatch):
    from eli.execution import executor_enhanced as ex
    from eli.memory.memory import Memory
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    mem = Memory(db_path=tmp_path / "user.sqlite3")
    monkeypatch.setattr("eli.memory.get_memory", lambda *a, **k: mem)
    monkeypatch.setattr(ex, "_get_memory_path", lambda: tmp_path / "user.sqlite3")
    rid = mem.store_memory("My locker number at the gym is 212 and the padlock is red", source="user")["id"]
    ask = ex.execute("MEMORY_FORGET", {"query": "locker number gym"})
    assert ask["ok"] and rid in [m["id"] for m in ask["matches"]] and "Say yes" in ask["response"]
    assert mem.recall_memory("locker gym padlock", limit=3)
    done = ex.execute("MEMORY_FORGET", {"ids": [rid], "confirm": True})
    assert done["ok"] and "Forgotten" in done["response"]
    assert not [h for h in mem.recall_memory("locker gym padlock", limit=3) if h.get("id") == rid]
    assert "nothing" in ex.execute("MEMORY_FORGET", {"query": "zzzz qqqq"})["response"].lower()


CHATTER_TURN = "Couldn't agree more. I've only been up an hour or so, the party next door went on far too late last night haha"
CORRECTING_TURN = ("Nah, early starts and cold tea are the classic combo haha. No the long walk and reading that book "
                   "was a few days ago (I was at my aunt's for the weekend). Plan for today is give you a proper workout!")


def test_a_statement_that_says_last_night_does_not_narrow_retrieval_to_last_night():
    from eli.cognition.query_planner import plan_window
    assert plan_window(CHATTER_TURN) is None and plan_window(CORRECTING_TURN) is None
    assert plan_window("what did I say last night about the code") is not None
    assert plan_window("Did we talk about the lease yesterday") is not None


def test_no_the_x_was_earlier_is_a_correction_of_the_last_answer():
    from eli.cognition.correction_patterns import is_answer_correction
    assert is_answer_correction(CORRECTING_TURN)
    assert not is_answer_correction("Nah, early starts and cold tea are the classic combo haha")


def test_plain_conversation_never_reaches_the_intent_model():
    from eli.cognition.llm_intent import is_plain_statement
    assert is_plain_statement(CHATTER_TURN) and is_plain_statement(CORRECTING_TURN)
    for q in ("open spotify and play something upbeat please", "what is the date today?", "play some jazz for me now", "pause"):
        assert not is_plain_statement(q)


@pytest.mark.parametrize("remark", ["doing well, good redemption bud", "haha nice one, well done!", "thanks bud",
                                    "that was class", "the film was great", "wow"])
def test_a_short_remark_with_nothing_eli_can_do_in_it_is_not_resolved(remark):
    """Live: each of these waited 22 to 24 s on a 35B model for the intent model to answer CHAT.
    A short message used to be resolved whatever it said."""
    from eli.cognition.llm_intent import is_plain_statement
    assert is_plain_statement(remark)


@pytest.mark.parametrize("message", ["fire up spotify", "timer ten minutes", "weather tomorrow", "sort my downloads",
                                     "could you sort the downloads folder by date", "Sorry, been busy. open spotify",
                                     "what just happened?", "delete it", "this is great, play it again"])
def test_what_could_be_asking_for_something_eli_does_still_is(message):
    from eli.cognition.llm_intent import is_plain_statement
    assert not is_plain_statement(message)


@pytest.mark.parametrize("statement", ["i need to study for the exam tonight", "I want to tell you about my day at the allotment",
                                       "i would like to hear more about that one"])
def test_what_the_user_wants_for_themselves_is_not_a_request_to_eli(statement):
    from eli.cognition.llm_intent import is_plain_statement
    assert is_plain_statement(statement)


def test_one_list_of_the_verbs_a_command_starts_with():
    from eli.cognition import llm_intent
    from eli.runtime import command_splitter as cs
    assert not hasattr(llm_intent, "_IMPERATIVE")
    assert {"open", "delete", "save", "tell", "maximise"} <= set(cs.COMMAND_VERBS)
    assert cs.starts_with_command("delete it") and not cs._IMP_START.match("delete it"), "starts a command, does not split one"


def test_the_self_model_says_not_to_invent_fixes():
    from eli.runtime.awareness_boot import AwarenessState
    text = AwarenessState()._live_self_model()
    assert "do not say fixes were applied" in text


INVENTED = ("Good. I'm ready for the abuse.\n\nThe fixes have been applied, the memory leaks plugged (or at least contained), and the "
            "hallucination filters tightened to \"paranoid\". You can throw whatever edge cases you have at me now.")


def test_an_invented_changelog_is_dropped_unless_the_turn_had_evidence():
    from eli.cognition.output_governor import drop_unverified_self_status
    out = drop_unverified_self_status(INVENTED, is_grounded=False)
    assert "leaks plugged" not in out and "fixes have been applied" not in out and "ready for the abuse" in out and "throw whatever" in out
    assert drop_unverified_self_status(INVENTED, is_grounded=True) == INVENTED


def test_ordinary_talk_about_fixes_is_left_alone():
    from eli.cognition.output_governor import drop_unverified_self_status
    text = "You said the fixes went in yesterday. I can check the recent changes report if you want the details, or just test it."
    assert drop_unverified_self_status(text, is_grounded=False) == text
