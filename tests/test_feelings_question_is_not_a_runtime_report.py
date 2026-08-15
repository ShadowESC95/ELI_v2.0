"""Asking ELI how it feels must not return a runtime status dump.

Live at 2.1.93, 23:59. The router had already decided CHAT; the control contract
overrode it:

    Intent → CHAT (conf=0.85 via=chat.long_question_guard)
    Control contract upgraded action -> SELF_REPORT
    Query class: GROUNDED

and the answer to "so you are feeling, fine?" was

    "I'm ELI … running Qwen_Qwen3-8B-Q4_K_M.gguf locally on GPU (31 layers
     offloaded). Context window: 10384 tokens. All core systems nominal."

Two independent causes, both here:

1. A bare mention of "your persona" forced SELF_REPORT. The user had said "nice
   to see your persona" — a remark — and the actual question followed it in the
   same sentence. Every other trigger in that branch is request-shaped
   ("who are you", "tell me about yourself"); these two were bare noun phrases.

2. `_is_conversational_persona` exists to stop exactly this and covers
   "your feelings", "how do you feel", "your mood" — but not "how ARE you
   feeling" or "you ARE feeling". One word of phrasing.

This is the 2.1.82 defect ("what have you been doing?" → maintenance report) one
layer up: the router and this override both decide conversational-vs-grounded,
and they disagreed.
"""
import pytest

from eli.runtime.control_contracts import route_control_text


@pytest.mark.parametrize("said", [
    # the exact turns from the transcript
    "okay i am finished mesing around with your codebase. how are you feeling?",
    "I am the one asking how you are feeling..",
    "nice to see your persona, and memory for my world domination plans, "
    "good to see! so you are feeling, fine?",
    "it is nice to see your persona, and memory for my world domination plans, "
    "good to see! so you are feeling, fine?",
    # the phrasing family the guard was missing
    "how are you feeling",
    "are you feeling ok",
    "are you feeling alright?",
    "you doing alright?",
    "how do you feel",          # this one always worked — it must keep working
    # persona/identity mentioned, not asked about
    "love your persona mate",
    "your persona is class",
    "your identity is safe with me",
])
def test_conversational_turns_stay_in_chat(said):
    assert route_control_text(said, "CHAT") is None, said


@pytest.mark.parametrize("asked", [
    "what is your persona",
    "what's your identity",
    "describe your persona",
    "explain your persona",
    "tell me about your identity",
    "tell me about yourself",
    "who are you",
    "how has your persona evolved",
])
def test_real_identity_requests_still_reach_self_report(asked):
    """The contract exists for a reason — narrowing it must not disarm it."""
    assert route_control_text(asked, "CHAT") == "SELF_REPORT", asked


def test_the_other_control_routes_are_untouched():
    assert route_control_text("self-update", "CHAT") == "SELF_UPDATE"
    assert route_control_text(
        "what is your confidence in your last response", "CHAT") == "EXPLAIN_LAST_RESPONSE"


def test_a_feelings_question_beats_a_persona_mention_in_the_same_sentence():
    """The specific collision: a compliment about the persona outranked the
    question that followed it."""
    said = "nice to see your persona — so how are you feeling?"
    assert route_control_text(said, "CHAT") is None
