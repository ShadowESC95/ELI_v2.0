"""Behaviour lock: two bugs seen live in a real session.

#2  A command typed early ("pause spotify") was captured as the user's NAME, so
    every self-report greeted them as "You're pause spotify."
#3  "Can you explain what you meant by 'the context window was full of noise'?"
    routed to the raw EXPLAIN_COGNITION_RUNTIME data dump (paths, line numbers,
    every DB table) — the user's "that is not what i asked". The trigger fired on
    a bare 'context window' match inside quoted prose.
"""

import pytest

from eli.runtime.identity_validation import normalize_identity_candidate as _norm
from eli.execution.router_enhanced import route


# --------------------------------------------------------------------------
# #2 — a command is not a name
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "pause spotify", "open chrome", "play music", "turn off the lights",
    "set a timer", "mute the volume", "skip track", "search the web",
])
def test_command_phrases_are_not_valid_names(command):
    assert _norm(command) == "", f"{command!r} was accepted as a name"


@pytest.mark.parametrize("name", [
    "Jason", "Jason Bridgeman", "Mark", "Mary Jane", "Bill", "O'Brien",
])
def test_real_names_still_accepted(name):
    assert _norm(name) == name


def test_single_word_overlap_with_a_verb_is_left_alone():
    """The command guard only fires on the verb+object SHAPE, not lone words."""
    # "Set" as a standalone one-word candidate is not treated as a command here
    # (the guard requires >1 word), so ordinary short names are unaffected.
    assert _norm("Sky") == "Sky"


def test_set_user_name_rejects_a_command(tmp_path, monkeypatch):
    """End to end: the persistence chokepoint refuses to store a command."""
    from eli.kernel import state
    monkeypatch.setattr(state, "load_user_profile", lambda uid=None: {})
    saved = {}
    monkeypatch.setattr(state, "save_user_profile", lambda p, uid=None: saved.update(p))
    monkeypatch.setattr(state, "sync_identity_to_world_model", lambda **k: None)
    returned = state.set_user_name("pause spotify")
    assert returned == ""
    assert not saved.get("name")


# --------------------------------------------------------------------------
# #3 — explaining a prior claim is conversation, not a runtime dump
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    'can you explain "the context window was full of noise"?',
    "what do you mean the context window was full of noise?",
    "you said the context window was noisy — explain that",
    "So what improved, calibration wise? Can you explain what you meant?",
])
def test_explaining_a_prior_claim_does_not_dump_runtime(text):
    action = str(route(text).get("action"))
    assert action != "EXPLAIN_COGNITION_RUNTIME", f"{text!r} dumped the runtime map"


# Real diagnostics must still reach a GROUNDED report (not a confabulated CHAT).
# Which grounded action varies — a GPU question goes to GPU_STATUS, an inference
# question to EXPLAIN_COGNITION_RUNTIME — but never to unguarded chat.
_GROUNDED_DIAGNOSTICS = {"EXPLAIN_COGNITION_RUNTIME", "GPU_STATUS", "RUNTIME_STATUS"}


@pytest.mark.parametrize("text", [
    "what is my context window size?",
    "why did you take 20 minutes to respond?",
    "show me the current inference runtime",
    "what are my gpu layers set to?",
])
def test_real_diagnostics_still_route_to_a_grounded_report(text):
    assert str(route(text).get("action")) in _GROUNDED_DIAGNOSTICS
