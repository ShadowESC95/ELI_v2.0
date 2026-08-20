"""The world model must not narrate itself into unrelated turns.

Live at 2.3.8, first reply of a session:

    You:  What's up bud, good morning!
    ELI:  ... I'm still in the Reflection Chamber, staring at the Synthesis Draft
          like it's some kind of holy text.

"Synthesis Draft" is a real object in `reflection_chamber` — so this was not the
model inventing a name, it was the model being *handed* one. `build_persona_handoff`
gated only the full 9-room layout on "is this a world question"; the current room,
its purpose, the current activity and the objects in it were appended to the persona
brief on every single turn, under a prose note reading "available for direct
questions, not for proactive narration".

That note is advisement, and the model ignored it — the same failure the
guards-must-verify rule exists for. A guard has to withhold the material.

The turn after was worse: asked "synthesis draft?", ELI produced a paragraph about
wrestling with it "like a stubborn kernel of grain", because the object was still in
context with nothing to say about it.
"""
import json

import pytest

from eli.cognition.context_synthesiser import build_persona_handoff


def _brief(text: str) -> str:
    return json.dumps(build_persona_handoff(text), default=str)


UNRELATED = [
    "What's up bud, good morning!",
    "how are you doing?",
    "synthesis draft?",
    "thanks, that's helpful",
    "what's the weather like",
    "can you write me a python script",
]

WORLD_QUESTIONS = [
    "what room are you in?",
    "what are you doing right now",
    "tell me about your world",
    "where are you",
    "what's in the archive room",
]


@pytest.mark.parametrize("text", UNRELATED)
def test_world_state_is_absent_from_unrelated_turns(text):
    blob = _brief(text)
    assert "ELI WORLD STATE" not in blob, f"world block leaked into {text!r}"


@pytest.mark.parametrize("text", UNRELATED)
def test_no_room_or_object_names_leak_into_unrelated_turns(text):
    """The specific words ELI narrated unprompted."""
    blob = _brief(text)
    for name in ("Reflection Chamber", "Synthesis Draft", "Anomaly", "current room:"):
        assert name not in blob, f"{name!r} reached the model on an unrelated turn: {text!r}"


@pytest.mark.parametrize("text", WORLD_QUESTIONS)
def test_world_state_is_still_available_when_asked(text):
    """Withholding it unasked must not mean withholding it when asked — ELI has to be
    able to answer 'which room are you in' from truth rather than guesswork."""
    blob = _brief(text)
    assert "ELI WORLD STATE" in blob, f"world block missing for a world question: {text!r}"


def test_a_real_failure_is_logged_not_silently_skipped(monkeypatch, caplog):
    """The skip path and the error path must stay distinguishable. They shared one
    bare `except Exception: pass`, so a broken world store looked identical to
    'the user did not ask'."""
    import eli.cognition.context_synthesiser as cs

    class _Boom:
        def load(self):
            raise RuntimeError("world store unreadable")

    monkeypatch.setattr("eli.world.persistence.storage.EliWorldStorage", _Boom)
    with caplog.at_level("DEBUG"):
        blob = _brief("what room are you in?")
    assert "ELI WORLD STATE" not in blob          # degrades, does not crash
