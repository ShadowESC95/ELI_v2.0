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
