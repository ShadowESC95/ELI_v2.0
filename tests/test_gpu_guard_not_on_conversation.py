"""A conversational turn that mentions the GPU is not a request for telemetry.

Live at 2.3.26, this fifty-word turn was routed to GPU_STATUS at 0.995 and
answered with a VRAM dump:

    "The GPU is not back to full offload yet, you are on 28 layers- why are you
     still lying? I did the matrix arse-ways, now i am back to watching the 2nd
     movie- reloaded. My story ? Waiting for my dealer to finish work so i cn
     get some weed, you?"

Two faults compounded: a trailing "?" made the whole turn a "request" even
though it belonged to the last clause (about weed, not the GPU), and the user
STATING the layer count -- a correction, they already knew it -- was read as
asking for it. The guard runs ahead of chat.long_question_guard by design, so
nothing downstream could rescue it.
"""
import pytest

from eli.execution.router_enhanced import route_command

_CHALLENGE = (
    "The GPU is not back to full offload yet, you are on 28 layers- why are you "
    "still lying? I did the matrix arse-ways, now i am back to watching the 2nd "
    "movie- reloaded. My story ? Waiting for my dealer to finish work so i cn "
    "get some weed, you?"
)


def _action(text):
    return (route_command(text) or {}).get("action")


def test_the_observed_challenge_is_chat_not_a_dump():
    assert _action(_CHALLENGE) == "CHAT"


@pytest.mark.parametrize("text", [
    "yeah you aree right about the layers, we need to claw some back",
    "i don't care about that, I was talking about incrasing your layers",
    "you are on 28 layers mate, that's not full offload at all is it",
])
def test_corrections_and_brush_offs_stay_chat(text):
    assert _action(text) == "CHAT"


@pytest.mark.parametrize("text", [
    "gpu status",
    "vram usage",
    "how many layers are you using?",
    "are you using the gpu?",
    "is the gpu being used?",
    "how much vram is free?",
    "what's the gpu temperature?",
])
def test_real_status_questions_still_reach_the_report(text):
    """The documented activations must survive the tightening."""
    assert _action(text) == "GPU_STATUS", text


def test_a_long_turn_whose_last_question_is_about_the_gpu_still_reports():
    """Length alone must not disqualify a genuine question."""
    long_ask = ("So I have been messing about with settings all afternoon and I am "
                "not really sure what changed or whether any of it helped at all. "
                "Anyway, how many gpu layers are you actually running right now?")
    assert _action(long_ask) == "GPU_STATUS"
