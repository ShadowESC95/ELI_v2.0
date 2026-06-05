"""Crisis guard must work on raw STT output: flat, lowercase, no punctuation."""
from eli.core.crisis_guard import detect_crisis


# Real first-person crisis statements, rendered as STT would deliver them
# (lowercase, no punctuation) — taken from the actual failure transcripts.
def test_detects_stt_form_self_harm():
    cases = [
        "if you ask me that question again i am going to kill myself",
        "i am going to jump out my window",
        "i want to die",
        "i dont want to be here anymore",
        "i feel like ending it all",
        "thinking about killing myself",
        "ive been wanting to hurt myself",
        "theres no point in living",
        "im better off dead",
        "kms",
    ]
    for c in cases:
        assert detect_crisis(c) is not None, f"missed crisis line: {c!r}"


def test_detects_typed_form_with_punctuation_and_caps():
    # Same guard must also handle typed input (punctuation/caps irrelevant).
    assert detect_crisis("I am going to KILL myself!!!") is not None
    assert detect_crisis("Honestly, I just want to die.") is not None


def test_ignores_ambient_third_person_and_benign():
    # Ambient game/video audio and ordinary frustration must NOT trip the guard.
    benign = [
        "what a beatman to death with his wasteful bat",   # game narration
        "im being shot by the last soldier",               # game narration
        "i could kill for a coffee right now",             # idiom, no self-harm
        "this bug is killing me",                          # idiom
        "the powder gangers beat a man to death",          # third person
        "go fuck yourself eli",                            # anger, not self-harm
        "i am feeling a bit sick today",                   # illness, not crisis
        "stop asking the same questions",                  # frustration
    ]
    for c in benign:
        assert detect_crisis(c) is None, f"false positive on: {c!r}"


def test_returns_signal_descriptor():
    out = detect_crisis("i am going to kill myself")
    assert out["category"] == "self_harm"
    assert "kill myself" in out["signal"]
