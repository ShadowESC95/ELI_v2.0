"""Regression: onboarding must not store a greeting as the user's name.

Reported from a first-run on Arch: the user answered the name question with
"Hello and Good Morning" (a longer greeting, not a name), and ELI captured the
greeting AS the name and moved straight to the next question — the name step was
effectively skipped/verified against nothing. The name step now extracts a real
name from greetings/introductions and re-asks when there is no name.
"""
from __future__ import annotations

import pytest

from eli.onboarding import interview as I


@pytest.mark.parametrize("text,expected", [
    ("Hello and Good Morning", ""),      # the reported case — greeting, no name
    ("Good morning", ""),
    ("yo", ""),
    ("Hi, I'm Keith", "Keith"),
    ("call me Sam", "Sam"),
    ("Keith", "Keith"),
    ("hey there, my name is Bob", "Bob"),
    ("Good afternoon, this is Alex", "Alex"),
    ("I would like you to help me build a website", ""),  # a sentence, not a name
])
def test_extract_name(text, expected):
    assert I._extract_name(text) == expected


def test_greeting_at_name_step_reasks_not_stores(tmp_path, monkeypatch):
    """A greeting at the name step re-asks; it is NOT stored as the name, and the
    interview does NOT advance to the next step."""
    state = tmp_path / "onboarding_state.json"
    monkeypatch.setattr(I, "_state_file", lambda: state)
    captured = {}
    # Don't touch the real user DB / name store.
    monkeypatch.setattr("eli.kernel.state.set_user_name",
                        lambda n: captured.__setitem__("name", n), raising=False)

    I._set_onboarding_state("name", {})
    reply = I.onboarding_intercept("Hello and Good Morning")

    assert reply is not None and "call you" in reply.lower()   # re-asked for the name
    st = I.get_onboarding_state()
    assert st["step"] == "name"                                # did NOT advance
    assert not st["answers"].get("name")                       # greeting NOT stored
    assert "name" not in captured                              # set_user_name NOT called


def test_real_name_after_reask_advances(tmp_path, monkeypatch):
    state = tmp_path / "onboarding_state.json"
    monkeypatch.setattr(I, "_state_file", lambda: state)
    monkeypatch.setattr("eli.kernel.state.set_user_name", lambda n: None, raising=False)

    I._set_onboarding_state("name", {})
    I.onboarding_intercept("Hello and Good Morning")           # re-ask
    reply = I.onboarding_intercept("I'm Keith")                # real name

    st = I.get_onboarding_state()
    assert st["answers"].get("name") == "Keith"
    assert st["step"] == "role"                                # advanced past name
    assert reply is not None


# ── greeting-vs-name hardening (from a user screencast where "Greetings and
#    Salutations!" was captured as the name "Salutations") ──────────────────
@pytest.mark.parametrize("reply", [
    "Greetings and Salutations!", "Salutations", "sup", "what's up", "hola",
    "Good day to you", "greetings friend", "hi there friend",
    "nice to meet you", "pleased to meet you", "!!!",
])
def test_greetings_and_filler_are_never_stored_as_a_name(reply):
    from eli.onboarding.interview import _extract_name
    assert _extract_name(reply) == ""


@pytest.mark.parametrize("reply", ["Hello ELI", "hey eli", "hi assistant", "yo computer"])
def test_addressing_eli_is_not_the_users_name(reply):
    """'hello ELI' must not make the user's name 'ELI' — they'd be called that forever."""
    from eli.onboarding.interview import _extract_name
    assert _extract_name(reply) == ""


@pytest.mark.parametrize("reply,expected", [
    ("Hi, I'm Keith", "Keith"),
    ("call me Sam", "Sam"),
    ("my name is Rowan", "Rowan"),
    ("hello, my name is Ada", "Ada"),
    ("I'm Mary Anne", "Mary Anne"),
    ("Node815", "Node815"),
    ("Dr. Chen", "Dr. Chen"),
    ("Jean-Luc", "Jean-Luc"),
])
def test_real_names_still_captured_through_greetings(reply, expected):
    from eli.onboarding.interview import _extract_name
    assert _extract_name(reply) == expected


# ── a command typed at a question is a command ──────────────────────────────
@pytest.fixture()
def interview(tmp_path, monkeypatch):
    """The interview with its state in this test's folder and no real name store."""
    monkeypatch.setattr(I, "_state_file", lambda: tmp_path / "onboarding_state.json")
    stored = {}
    monkeypatch.setattr("eli.kernel.state.set_user_name",
                        lambda n: stored.__setitem__("name", n), raising=False)
    return stored


@pytest.mark.parametrize("typed", ["resume", "pause", "louder", "vol up", "mute", "next",
                                   "resume browser", "help"])
def test_a_command_typed_at_the_name_question_is_carried_out_not_stored_as_the_name(typed, interview):
    """"resume" answered "what should I call you?" and ELI then said "Your name is resume." The
    words are not listed anywhere here: the router is asked, as it is for every message."""
    from eli.execution.router_enhanced import route

    I._set_onboarding_state("name", {})
    assert I.onboarding_intercept(typed, route=route) is None, "it goes on to be carried out"
    assert "name" not in interview and not I.is_onboarding_active()


@pytest.mark.parametrize("typed,name", [
    ("jason", "jason"), ("Mark", "Mark"), ("Will", "Will"), ("June", "June"), ("Rose", "Rose"),
    ("call me Pause", "Pause"),             # introduced as a name: a name, whatever the word
    ("hi, my name is Stop", "Stop"),
])
def test_a_name_is_still_a_name_with_the_router_asked(typed, name, interview):
    from eli.execution.router_enhanced import route

    I._set_onboarding_state("name", {})
    reply = I.onboarding_intercept(typed, route=route)
    assert reply is not None and interview.get("name") == name
    assert I.get_onboarding_state()["step"] == "role"


def test_a_command_from_a_new_user_is_carried_out_not_met_with_a_question(interview, monkeypatch):
    from eli.execution.router_enhanced import route

    monkeypatch.setattr(I, "_profile_missing", lambda db_path=None: True)
    assert I.onboarding_intercept("resume", route=route) is None
    assert not I.is_onboarding_active()
    assert "call you" in (I.onboarding_intercept("hi", route=route) or "").lower()


def test_picking_an_offered_choice_is_an_answer_whatever_the_router_makes_of_it(interview):
    key = next(iter(I._ROLE_OPTIONS))
    I._set_onboarding_state("role", {"name": "Keith"})
    reply = I.onboarding_intercept(key, route=lambda text: {
        "action": "PLAY_MEDIA", "confidence": 0.9, "meta": {"matched_by": "some.rule"}})
    assert reply is not None and I.get_onboarding_state()["step"] == "style"


@pytest.mark.parametrize("intent,expected", [
    ({"action": "PLAY_MEDIA", "confidence": 0.88, "meta": {"matched_by": "media.bare_command"}}, True),
    ({"action": "NOOP", "confidence": 0.999, "meta": {"matched_by": "eli.tiny_chat_fragment_guard"}}, False),
    ({"action": "CHAT", "confidence": 0.9, "meta": {"matched_by": "chat.greeting"}}, False),
    ({"action": "OPEN_APP", "confidence": 0.9, "meta": {"matched_by": "fallback.chat"}}, False),
    ({"action": "OPEN_APP", "confidence": 0.3, "meta": {"matched_by": "apps.open"}}, False),
    (None, False),
])
def test_what_the_router_calls_a_command(intent, expected):
    from eli.execution.route_contracts import is_command

    assert is_command(intent) is expected


def test_the_engine_gives_the_interview_the_router_s_answer():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "eli/kernel/engine.py").read_text(encoding="utf-8")
    call = source[source.index("_ob_intercept(user_input"):][:240]
    assert "route=_route_once" in call, "asked once per turn: routing a message is not free of effects"
