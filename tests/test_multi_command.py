"""Multi-command splitting: one utterance chaining several imperative commands runs each."""
from __future__ import annotations

import pytest

from eli.runtime.command_splitter import split_commands
from eli.execution.router_enhanced import route


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
    r = execute("MULTI_COMMAND", {"commands": []})
    assert r["ok"] is False
