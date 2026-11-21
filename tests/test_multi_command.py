"""Multi-command splitting: one utterance chaining several imperative commands runs each."""
from __future__ import annotations

import pytest

from eli.runtime.command_splitter import read_message, split_commands
from eli.execution.router_enhanced import route


@pytest.fixture(autouse=True)
def isolated_command_sequence_log(tmp_path, monkeypatch):
    # test_executor_runs_each_command below exercises MULTI_COMMAND for real, which
    # persists to command_sequence_log.py — without this it writes to the real
    # artifacts/runtime/command_sequences.json.
    monkeypatch.setenv("ELI_COMMAND_SEQUENCE_LOG", str(tmp_path / "seq.json"))


@pytest.mark.parametrize("text,n", [
    ("close steam and set an alarm for 7am", 2),
    ("open spotify then play vincents tale", 2),
    ("open spotify and get the news and close steam", 3),
])
def test_split_chained_commands(text, n):
    segs = split_commands(text)
    assert segs is not None and len(segs) == n
    assert all(s.strip() for s in segs)


@pytest.mark.parametrize("text", [
    "play tom and jerry",                    # 'jerry' not imperative → whole
    "open the file and folder manager",      # 'folder manager' not imperative
    "set the volume and brightness",
    "who are you and who am i?",             # question → handled elsewhere
    "close steam",                           # single command
    "how are you today",                     # not imperative
])
def test_does_not_oversplit(text):
    assert split_commands(text) is None


def test_router_routes_chain_to_multi_command():
    r = route("close steam and set an alarm for 7am")
    assert r["action"] == "MULTI_COMMAND"
    assert r["args"]["commands"] == ["close steam", "set an alarm for 7am"]


@pytest.mark.parametrize("text,expected", [
    ("close steam", "CLOSE_APP"),
    ("play tom and jerry", "PLAY_MEDIA"),
    ("who are you and who am i?", None),     # not MULTI_COMMAND
])
def test_single_or_nonchain_not_multi(text, expected):
    a = route(text)["action"]
    assert a != "MULTI_COMMAND"
    if expected:
        assert a == expected


def test_executor_runs_each_command():
    from eli.execution.executor_enhanced import execute
    # two read-only commands → combined result, no side effects / no model needed
    r = execute("MULTI_COMMAND", {"commands": ["what time is it", "what time is it"]})
    assert r["action"] == "MULTI_COMMAND"
    assert r["content"].count("•") == 2


def test_executor_empty_commands():
    from eli.execution.executor_enhanced import execute
    # No commands = incomplete input, not a system fault: ELI asks what to run
    # (ok=True) and marks fault=False so it isn't logged as a recurring error.
    r = execute("MULTI_COMMAND", {"commands": []})
    assert r.get("fault") is False
    assert r.get("needs_input") is True


# ── a message read as instructions and talk ──────────────────────────────────
#
# Live, one evening on a 35B model: a complaint that ended "open nasa website" stopped the film
# that was playing and opened nothing; "see, you can do it! open spotify" was answered by the
# model alone, which wrote that Spotify was opening and then that a song was playing; and a
# sentence of ELI's own explanation ("Spotify received that stop signal, paused the track, ...")
# was stored as a step and run when the user said "yes please".

from eli.runtime import command_splitter as cs

COMPLAINT = ("took too long, you need to sort out a plan properly. And you did not open spotify or play any song "
             "just now, you need to stop lying to me and giving false task updates.")
NARRATIVE = ("Spotify received that stop signal, paused the track, but left the app window open because it "
             "wasn't told to quit, just to halt playback")


@pytest.mark.parametrize("sentence,tells", [
    ("ok, could you open spotify please", "open spotify please"),
    ("I'd like you to pause the music", "pause the music"),
    ("you can stop the music now", "stop the music now"),
    ("open nasa website", "open nasa website"),
    ("you did not open spotify", ""),                       # about what happened
    ("And you did not open spotify or play any song just now", ""),
    ("did you open spotify?", ""),                          # asks about it
    ("why is nothing playing?", ""),
    ("it stopped again", ""),
    ("i think you should stop", ""),
    ("have you opened spotify", ""),
    ("look up the opening hours", "look up the opening hours"),   # a verb here, not a call for attention
    ("look, open spotify", "open spotify"),
    ("have the summary ready by tomorrow", "have the summary ready by tomorrow"),
    ("does.not.exist", "does.not.exist"),                   # an address, not a question
])
def test_an_instruction_is_told_from_a_statement_by_its_form(sentence, tells):
    assert cs.instruction(sentence) == tells


def test_sentences_are_split_at_their_ends_and_not_inside_a_title():
    assert cs.sentences("see, you can do it! open spotify") == ["see, you can do it!", "open spotify"]
    assert cs.sentences("play mr. brightside by the killers") == ["play mr. brightside by the killers"]
    assert cs.sentences("play order and chaos feat. red tamsin") == ["play order and chaos feat. red tamsin"]
    assert cs.sentences("this is great, play it again") == ["this is great,", "play it again"]
    assert cs.sentences("you did not open it - could you open spotify") == ["you did not open it", "could you open spotify"]
    whole = "Spotify received that stop signal, paused the track, but left the app window open"
    assert cs.sentences(whole) == [whole]
    assert cs.sentences("play salt in salt out, then pause it") == ["play salt in salt out, then pause it"]
    # speech has no punctuation: the request's own frame marks where it starts
    assert cs.sentences("that was great can you play some jazz") == ["that was great", "can you play some jazz"]
    assert cs.sentences("it stopped again please resume it") == ["it stopped again", "please resume it"]
    assert cs.sentences("can you play some jazz") == ["can you play some jazz"]


def test_a_complaint_that_names_a_command_is_talk():
    got = route(COMPLAINT)
    assert got["action"] == "CHAT"
    assert got["meta"]["matched_by"] == "router.not_an_instruction", "and it is not sent on to be resolved again"
    assert got["meta"]["not_told"]["action"]


def test_the_command_at_the_end_of_a_complaint_is_the_one_thing_carried_out():
    got = route(COMPLAINT + " open nasa website")
    assert got["action"] == "CHAT" and got["meta"]["matched_by"] == "message.instructions_and_talk"
    plan = got["args"]["agreed"]
    assert plan["commands"] == ["open nasa website"] and plan["rest_of_message"] is True
    assert "stop lying" in plan["tasks"][0] and "nasa" not in plan["tasks"][0]


def test_a_command_after_a_remark_is_carried_out_and_the_remark_is_answered():
    plan = route("see, you can do it! open spotify")["args"]["agreed"]
    assert plan["commands"] == ["open spotify"] and plan["tasks"] == ["see, you can do it!"]


def test_a_sentence_of_explanation_is_not_a_command_and_is_not_kept_as_an_offered_step():
    assert route(NARRATIVE)["action"] == "CHAT"
    from eli.runtime.pending_proposal import read_reply
    reply = ("Here is what happened:\n1. I sent the play command to Spotify. It started playing.\n"
             f"2. {NARRATIVE}.\nDo you want me to play it again?")
    assert all(item["kind"] != "action" or "Spotify received" not in item["command"]
               for item in read_reply(reply)["items"])


@pytest.mark.parametrize("text,action", [
    ("open spotify", "OPEN_APP"),
    ("can you open spotify", "OPEN_APP"),
    ("good. close youtube", "CLOSE_APP"),
    ("well done. vol up", "VOLUME"),
    ("you can stop the music now", "STOP_MEDIA"),
    ("pause the music for a second while i take this call", "PAUSE_MEDIA"),
    ("turn the volume up a bit please", "VOLUME"),
    ("whats playing?", "NOW_PLAYING"),
    ("stop", "STOP_MEDIA"),
    ("resume", "PLAY_MEDIA"),
    ("close spotify and resume browser", "MULTI_COMMAND"),
    ("play salt in salt out by kfr on spotify", "PLAY_MEDIA"),
])
def test_what_is_said_as_a_command_is_still_a_command(text, action):
    assert route(text)["action"] == action


def test_restart_is_the_machine_s_only_when_it_has_no_other_object():
    assert route("restart")["action"] == "OPEN_POWER_SETTINGS"
    assert route("restart the computer")["action"] == "OPEN_POWER_SETTINGS"
    assert route('restart "North & South"')["action"] != "OPEN_POWER_SETTINGS"


@pytest.mark.parametrize("text", [
    "Write a complete Python module implementing a binary search tree with insert, delete and search, with unit tests.",
    "write a function with add, remove and search",
    "make a class with read and write methods",
    "write a parser that can read and write csv",
])
def test_verbs_listed_inside_what_is_asked_for_are_not_instructions(text):
    assert split_commands(text) is None
    assert len(read_message(text, chains=True)) == 1


@pytest.mark.parametrize("text", [
    "write a script that renames files and test it",
    "write a python script that sorts a list and tests it",
    "make a script that sorts a list and make sure it works",
    "write a bash script that backs up a folder, and test it",
])
def test_code_to_write_and_test_is_one_task_for_the_coding_agent(text):
    """"write a script that renames files and test it" was split into a script to write and a second
    command "test it", which went to chat: the script was written unchecked."""
    got = route(text)
    assert got["action"] == "CODE_SOLVE", got
    assert got["args"]["description"] == text


def test_writing_tests_and_writing_a_plain_script_keep_their_own_actions():
    assert route("write unit tests for the parser")["action"] == "GENERATE_TESTS"
    assert route("write a script that renames files")["action"] == "GENERATE_SCRIPT"


@pytest.mark.parametrize("text", ["implement a function that reverses a string", "implement a class for a bank account",
                                  "develop a parser for csv files"])
def test_code_to_implement_without_test_wording_is_a_script_to_write(text):
    """"implement a function that X" went to chat: CODE_SOLVE needs test wording, and the script rule
    did not know "implement"."""
    assert route(text)["action"] == "GENERATE_SCRIPT"


@pytest.mark.parametrize("text", ["implement the plan we discussed", "create a class schedule"])
def test_implementing_what_is_not_code_is_not_a_script(text):
    assert route(text)["action"] not in ("GENERATE_SCRIPT", "CODE_SOLVE")


@pytest.mark.parametrize("text", ["make a list of places to go", "write it down and go", "create a backup and go",
                                  "build the index and go"])
def test_the_word_go_is_not_the_go_language(text):
    """The code rules read "go" anywhere as the Go language, so these were Go scripts to write."""
    assert route(text)["action"] not in ("GENERATE_SCRIPT", "CODE_SOLVE")


@pytest.mark.parametrize("text,language", [
    ("write a script that renames files and test it and go", "python"),
    ("write a script in go that prints hello and test it", "go"),
    ("write a golang function that adds two numbers and test it", "go"),
])
def test_the_coding_agent_gets_the_language_named_as_a_language(text, language):
    got = route(text)
    assert got["action"] == "CODE_SOLVE" and got["args"]["language"] == language, got


@pytest.mark.parametrize("text", ["write a go program that prints hello", "build me a small rust cli",
                                  "create a typescript interface for a user"])
def test_code_in_a_language_named_as_one_is_still_a_script_to_write(text):
    assert route(text)["action"] == "GENERATE_SCRIPT"


def test_a_python_script_that_counts_is_written_in_python(monkeypatch):
    """GENERATE_SCRIPT found the language by substring: "ts" in "counts" made it TypeScript."""
    import types
    import eli.coding.sandbox as sandbox
    from eli.execution import executor_enhanced as ex
    asked = []
    monkeypatch.setattr("eli.coding.solve", lambda desc, language=None, **k: asked.append(language) or
                        {"code": "print('ok')\n", "solved": True}, raising=False)
    monkeypatch.setattr(sandbox, "run_code", lambda *a, **k: types.SimpleNamespace(crashed=False, traceback_tail=""))
    out = ex._execute_impl("GENERATE_SCRIPT", {"description": "write a python script that counts lines",
                                               "_no_background": True})
    assert asked == ["python"] and out["filename"].endswith(".py"), (asked, out)


@pytest.mark.parametrize("text, parts", [
    ("open spotify and pause", ["open spotify", "pause"]),
    ("remind me to call mum and open spotify", ["remind me to call mum", "open spotify"]),
    ("set an alarm for 7am and open spotify", ["set an alarm for 7am", "open spotify"]),
])
def test_instructions_after_such_a_phrase_still_divide(text, parts):
    assert split_commands(text) == parts


def test_a_question_among_sentences_is_talk_not_an_instruction():
    """A question whose words a rule happened to match was carried out as a command."""
    from eli.runtime.command_splitter import read_message
    said = read_message("lovely weather today. seems the kettle is busy, who is that by the way?")
    assert said[-1]["tells"] == ""
    assert read_message("thanks for that. can you open the calculator?")[-1]["tells"] == "open the calculator?"
    assert read_message("nice one. play some jazz?")[-1]["tells"] == "play some jazz?"


@pytest.mark.parametrize("text", [
    "Context: the depot ledger has 3 bins. Fern = BIN-0001. Moss = BIN-0002. Note: Fern is not Moss. Which bin belongs to Moss?",
    "Context: Moss is not Fern. Note: Fern has code KEY-A01 and Moss has code KEY-B01. What is Fern's code? Reply with only the code.",
    "Information supplied: Project Q-7 started in May. What is the passphrase for Project Q-7? If it is not provided, say UNKNOWN.",
])
def test_a_labelled_sentence_beside_a_question_is_material_not_a_command(text):
    """A "Note:" among other sentences wrote a note to disk and put "Wrote note to ..." in the answer."""
    assert all(part["tells"] == "" for part in read_message(text) if cs.labels_material(part["said"]))
    routed = route(text)
    assert routed["action"] == "CHAT" and not (routed.get("args") or {}).get("agreed")


def test_a_label_in_front_of_an_instruction_or_alone_still_tells():
    assert not cs.labels_material("Task: open steam")
    assert route("note: buy milk")["action"] == "WRITE_NOTE"
    assert route("write a note saying buy milk")["action"] == "WRITE_NOTE"


@pytest.mark.parametrize("text, kept", [
    ("My locker code is TULIP-4482. Please remember it.", "My locker code is TULIP-4482."),
    ("The spare tyre is in the shed. Remember that.", "The spare tyre is in the shed."),
])
def test_remember_it_keeps_what_the_message_said(text, kept):
    """"Please remember it" was stored as the word "it", which the memory filter turned down."""
    routed = route(text)
    assert routed["action"] == "MEMORY_STORE" and routed["args"]["text"] == kept


@pytest.mark.parametrize("text, action", [
    ("start dictation", "DICTATE"),
    ("start a new chat", "CLEAR_CHAT_HISTORY"),
    ("open system settings", "OPEN_SYSTEM_SETTINGS"),
    ("open media hub", "OPEN_MEDIA_HUB"),
    ("open network settings", "OPEN_NETWORK_BROWSER"),
    ("start a pomodoro", "POMODORO_START"),
    ("open spotify", "OPEN_APP"),
])
def test_elis_own_features_are_not_apps_to_open(text, action):
    """"start dictation" offered to install a program called "dictation". The features are known by
    their actions' names, so rewording a phrase in the capability list cannot lose one."""
    assert route(text)["action"] == action
