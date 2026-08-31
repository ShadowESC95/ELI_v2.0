"""Lock on SET_TONE not firing when the user DENIES an emotion.

This produced a self-sustaining loop in a live session, and a harmful one.

ELI's proactive check-in said "you've been reading more sad lately". The user
replied to it — "i am not sad eli, i am just trying to get your codebas correct".
The router matched `tone.set` and returned SET_TONE(sad): denying the emotion set
ELI to it. That reading was recorded, the counter climbed, and the check-in fired
again with the same sentence. The log shows it escalating sad×3 -> sad×7 in a
single session, each round telling the user they seemed sad because they had just
said they were not.

Two causes, both here:

* The gate listed `more`, `less`, `get` and `go` as "tone-setting verbs". They are
  ordinary English, so the gate passed on almost any sentence and whatever emotion
  word it contained became a command.
* Nothing checked for negation at all.
"""
import pytest

from eli.execution.router_enhanced import route


def _action(text: str) -> str:
    return (route(text) or {}).get("action") or ""


def _tone(text: str):
    return ((route(text) or {}).get("args") or {}).get("tone")


# ── the exact live failures ─────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "i am not sad eli, i am just trying to get your codebas correct",
    "yes, but how does that make me red more sad lately, as you stated ?",
])
def test_the_live_misfires_are_chat(text):
    assert _action(text) != "SET_TONE"


# ── denial in general ───────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "I am NOT sad",
    "i'm not sad",
    "i am not angry, just tired of this bug",
    "don't be sad about it",
    "stop being sad",
])
def test_denied_emotions_never_set_the_tone(text):
    assert _action(text) != "SET_TONE", f"denial set the tone: {text!r}"


# ── ordinary words must not gate a tone change ──────────────────────────────
@pytest.mark.parametrize("text", [
    "can you get the sad file from my desktop",
    "i want to go over the angry customer emails",
    "there are more happy paths than error paths in this function",
])
def test_common_words_do_not_carry_a_tone_directive(text):
    """`more`, `less`, `get`, `go` are not instructions — they were the hole."""
    assert _action(text) != "SET_TONE", f"ordinary sentence set the tone: {text!r}"


# ── genuine directives must still work ──────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("be more cheerful", "happy"),
    ("be sad", "sad"),
    ("talk happy", "happy"),
])
def test_real_tone_directives_still_fire(text, expected):
    """The fix must not make the feature unreachable — `be`/`sound`/`talk` carry
    the instruction, the adverb never did."""
    assert _action(text) == "SET_TONE"
    assert _tone(text) == expected


def test_sound_less_formal_still_fires():
    assert _action("sound less formal") == "SET_TONE"


def test_clearing_the_tone_still_works():
    assert _action("back to normal") == "CLEAR_TONE"


@pytest.mark.parametrize("text", [
    "are you back to normal yet, or not?",
    "are you back to normal yet?",
    "are you back to normal",
    "you back to normal yet?",
])
def test_status_check_in_is_not_clear_tone(text):
    assert _action(text) != "CLEAR_TONE", f"status question routed to CLEAR_TONE: {text!r}"
