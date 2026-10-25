"""Multi-command splitting: one utterance chaining several imperative commands runs each."""
from __future__ import annotations

import pytest

from eli.runtime.command_splitter import split_commands
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
