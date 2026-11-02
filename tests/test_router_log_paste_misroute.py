"""ELI's own log noise (\"kg sync complete\") pasted into chat must not route to
EXPLAIN_MEMORY_RUNTIME."""
from __future__ import annotations

import pytest

from eli.execution.router_enhanced import route

# The actual pasted GUI log from the bug report (trimmed to the load-ladder
# lines that matter, including the "kg sync complete" line that caused it).
PASTED_GUI_LOG = (
    "[GUI][LOAD] attempt 1/13: requested (ctx=12384 gpu_layers=10 batch=128)\n"
    "[GUI][LOAD] verifying your settings on this machine "
    "(ctx=12384 gpu_layers=10 batch=128) — up to 180s this once, then remembered…\n"
    "persona_updater: overlay updated (8 sections)\n"
    "persona_updater: kg sync complete — 1 entities, 0 relations\n"
    "[LOAD_PROBE] timed out after 180s — treating as unproven\n"
    "[GUI][LOAD] could not verify your settings in time "
    "(probe timed out after 180s (unproven)) — they exceed the measured fit "
    "(ctx 12384>4096), and loading them unproven is what aborts mid-generation. "
    "Falling through to the measured fallbacks; raise ELI_LOAD_PROBE_TIMEOUT to "
    "allow the check more time, or set ELI_LOAD_PROBE=0 to load them as entered "
    "without proof.\n"
    "[GUI][LOAD] attempt 2/13: smart-fit (ctx=4096 gpu_layers=11 batch=128)\n"
    "[GUI][LOAD] selected=smart-fit (ctx=4096 gpu_layers=11 batch=128)"
)


def test_pasted_gui_log_no_longer_hijacks_the_memory_route():
    out = route(PASTED_GUI_LOG)
    assert out["action"] != "EXPLAIN_MEMORY_RUNTIME", (
        f"a pasted GUI load log's incidental 'kg sync complete' line must not "
        f"route the whole question to memory internals, got {out['action']} "
        f"(matched_by={out.get('meta', {}).get('matched_by')})"
    )


def test_bare_kg_alone_does_not_match_memory_internals():
    # Isolates the exact token that caused the false positive, independent of
    # the rest of the pasted log.
    out = route("persona_updater: kg sync complete — 1 entities, 0 relations")
    assert out.get("meta", {}).get("matched_by") != "eli.final_memory_internals_route_contract"


def test_bare_rag_alone_does_not_match_memory_internals():
    out = route("I bought a nice rag for cleaning the GPU fans")
    assert out.get("meta", {}).get("matched_by") != "eli.final_memory_internals_route_contract"


# The fix must not blunt genuine mechanism questions -- these still name the
# retrieval/storage stack unambiguously and should still route as before.
def test_knowledge_graph_full_phrase_still_matches():
    out = route("Explain how your knowledge graph works internally")
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out


def test_faiss_still_matches():
    out = route("Walk me through how FAISS fits into your memory pipeline")
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out


def test_hyde_still_matches():
    out = route("Explain how HyDE works in your retrieval pipeline start to finish")
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out


# ── a pasted message from someone else (2.5.16 log: ChatGPT's critique of ELI) ──

CHATGPT_CRITIQUE = (
    "Alright, tell ELI the review panel has its notes. ELI has evidence about its own memory "
    "architecture. Your runtime reported, live: Qwen3.6-35B-A3B Q4_K_M, ~16k effective context, eight "
    "physical SQLite stores, 507 memory entries, FTS5, FAISS and a knowledge graph. Show the receipt. "
    "You have an audit ledger. Use it. I am making it more precise: you need to enforce provenance. "
    "Your own trace for a simple greeting assembled a ~9,809-token prompt and took about 267 seconds."
)


def test_the_users_own_words_are_split_from_what_they_pasted():
    from eli.cognition.correction_patterns import shortcut_text, split_pasted
    own, pasted = split_pasted("here is the other assistant's reply, let's see what you make of it ---> " + CHATGPT_CRITIQUE)
    assert own == "here is the other assistant's reply, let's see what you make of it"
    assert pasted.startswith("Alright, tell ELI")
    own, pasted = split_pasted("here's what it said:\n" + CHATGPT_CRITIQUE)
    assert own == "here's what it said" and pasted.startswith("Alright")
    assert split_pasted("a -> b is an arrow in code") == ("a -> b is an arrow in code", "")
    # a report answers a short request for it; a long message is the user talking
    assert shortcut_text(CHATGPT_CRITIQUE) == ""
    assert shortcut_text("what is your runtime status?") == "what is your runtime status?"


def test_a_paste_mentioning_elis_runtime_and_memory_is_no_report_request():
    """Four runtime and personal-memory dumps answered a pasted ChatGPT critique in one evening."""
    from eli.cognition.correction_patterns import shortcut_text
    from eli.runtime.control_contracts import route_control_text
    for message in (CHATGPT_CRITIQUE, "Right, go all out on this know-it-all, here's its response --> " + CHATGPT_CRITIQUE):
        said = shortcut_text(message)
        assert not said or route_control_text(said, "CHAT") in (None, "", "CHAT")


def test_a_recap_of_the_last_few_messages_is_read_from_the_conversation():
    """It went to the intent model (90 s) and came back as a memory dump reaching back to August."""
    for text in ("can you check the last, say 7-8 messages, summarise what has been said/happening please",
                 "summarise the last few messages", "what was said in the last couple of messages?"):
        out = route(text)
        assert out["action"] == "CHAT" and out["meta"]["matched_by"] == "conversation.recap", text
    assert route("play the last few songs")["action"] != "CHAT"


def test_a_reply_pointed_at_by_count_is_an_earlier_reply():
    from eli.cognition.correction_patterns import refers_to_earlier_reply
    assert refers_to_earlier_reply("look at your message from 2 messages ago- you answered fine in the first half")
    assert refers_to_earlier_reply("a few replies back you said")
    assert not refers_to_earlier_reply("I have two messages for you")


@pytest.mark.parametrize("message", [
    "well don't get ahead of yourself, i am still waiting for my other 29 files.. the show is not paused, it's playing",
    "got anything else to say before i clock off for a bit?",
    "it's tuesday, i know what day it is.. i'm going to unplug you",
    "i know what the date is dude, you don't need to spar with me",
    "what did you actually search for?",
])
def test_said_or_asked_about_eli_is_not_a_command(message):
    from eli.execution.router_enhanced import route
    assert route(message)["action"] == "CHAT", message


def test_look_at_what_is_on_reads_the_media_session():
    from eli.execution.router_enhanced import route
    assert route("look at what i'm watching")["action"] == "NOW_PLAYING"


def test_every_folder_a_message_names_is_read(tmp_path):
    from eli.execution.router_enhanced import route
    dirs = [tmp_path / "1. First (a b)", tmp_path / "2. Second + more", tmp_path / "3. Third, thing"]
    for d in dirs:
        d.mkdir()
        (d / "paper.pdf").write_bytes(b"")
    for lead in ("analyse", "Eli! please analyse the 3 remaining folders"):
        got = route(lead + "\n" + "\n".join(str(d) for d in dirs))
        assert got["action"] == "ANALYZE_PDF_FOLDER", lead
        assert got["args"]["folders"] == [str(d) for d in dirs], lead


def test_a_path_with_nothing_asked_of_it_is_left_alone(tmp_path):
    from eli.execution.router_enhanced import paths_named
    a, b = tmp_path / "a b", tmp_path / "c"
    a.mkdir()
    b.mkdir()
    assert [p for _, p in paths_named(f"{a} and also {b}, ok")] == [str(a), str(b)]
    assert paths_named("this and/or that / other") == []


def test_analyse_them_is_the_job_in_hand_and_never_the_current_folder(tmp_path, monkeypatch):
    from eli.execution.router_enhanced import route
    from eli.runtime import background_tasks as bt
    monkeypatch.setattr(bt, "work_targets", lambda unfinished_only=False: [str(tmp_path)])
    got = route("analyse them")
    assert got["action"] == "ANALYZE_PDF_FOLDER" and got["args"]["folders"] == [str(tmp_path)]
    monkeypatch.setattr(bt, "work_targets", lambda unfinished_only=False: [])
    got = route("well analyse the remaining pdf files as a background task")
    assert got["args"].get("path") != "."


def test_a_topic_is_summarised_from_memory_but_analysing_a_thing_is_not_recall():
    from eli.execution.router_enhanced import route
    assert route("summarise the plan we talked about")["action"] == "MEMORY_RECALL"
    assert route("please analyse the budget idea")["action"] != "MEMORY_RECALL"


def test_a_pdf_command_with_no_path_asks_instead_of_opening_the_current_folder(monkeypatch):
    from eli.execution.executor_enhanced import execute
    from eli.runtime import background_tasks as bt
    monkeypatch.setattr(bt, "work_targets", lambda unfinished_only=False: [])
    for args in ({"path": ""}, {"path": "."}):
        got = execute("ANALYZE_PDF", args)
        assert got["ok"] is False and "Not a PDF" not in got["content"] and got["awaiting"]["needs"] == "path"


def test_a_script_that_only_names_a_marker_is_not_a_stub():
    from eli.execution.executor_enhanced import _stub_marker
    assert _stub_marker('count = text.count("TODO")\nname = "placeholder"\n') == ""
    assert "line 2" in _stub_marker("def f():\n    # TODO: implement this\n    pass\n")
    assert _stub_marker("Generate only the requested source code\nprint(1)\n")


def test_two_remarks_joined_by_and_are_not_two_commands():
    assert route("get out of your room and do some work")["action"] != "MULTI_COMMAND"
    got = route("pause and close spotify")
    assert got["action"] == "MULTI_COMMAND" and got["args"]["commands"] == ["pause", "close spotify"]


def test_the_record_of_a_file_is_not_the_reply():
    from eli.kernel.engine import _plain_artifact_reply
    record = '{"event": "artifact_generated", "kind": "script", "path": "/x/y.py", "verified": true}'
    got = _plain_artifact_reply({"ok": True, "action": "GENERATE_SCRIPT", "content": record, "response": record})
    assert got["content"] == "Saved the script as /x/y.py. It ran and passed its checks."
    assert got["artifact"]["path"] == "/x/y.py"
    plain = {"ok": True, "content": "{not a record}"}
    assert _plain_artifact_reply(plain) is plain


@pytest.mark.parametrize("said", [
    "clock off", "i'll clock off at five", "i know what day it is", "i know what the date is",
    "it's okay, you can see what i'm watching", "you can see the weather from here", "i need time",
    "i said it's raining", "i'm looking at the weather from here",
])
def test_a_word_of_a_question_in_a_statement_asks_nothing(said):
    assert route(said)["action"] == "CHAT"


@pytest.mark.parametrize("asked, action", [
    ("clock", "TIME"), ("check the clock", "TIME"), ("what does the clock say", "TIME"), ("i need the time", "TIME"),
    ("the date please", "DATE"), ("what day is it", "DATE"), ("vol don", "VOLUME"), ("is it raining", "GET_WEATHER"),
])
def test_the_same_words_asking_still_get_the_answer(asked, action):
    assert route(asked)["action"] == action
