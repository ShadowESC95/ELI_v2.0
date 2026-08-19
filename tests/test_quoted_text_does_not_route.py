"""Route on what the user asked, not on words they are quoting back.

Live at 2.3.6 the user quoted ELI's own sentence and challenged it:

    "If you're building something that requires depth, you might push toward
     more layers. But if it's about speed or resource usage, 26 is a smart
     middle ground." -- is that not counterintuitive?

"layers" + "you" INSIDE THE QUOTE fired eli.gpu_status_guard at 0.995, so a
conversational challenge was answered with a VRAM dump, and the user replied
"What the fuck Eli, answer me".

The principle was already written down in the router, in _explain_prior_claim:
"even when it quotes ELI's own words back, which may incidentally contain
'context window', 'confidence', 'max_tokens'". It had simply never reached the
GPU trigger.
"""
import pytest

from eli.execution.router_enhanced import route, _eli_outside_quotes


QUOTED_CHALLENGE = (
    '"If you\'re building something that requires depth, you might push toward more '
    'layers. But if it\'s about speed or resource usage, 26 is a smart middle '
    'ground." -- is that not counterintuitive?'
)


def test_a_quoted_challenge_is_conversation_not_a_diagnostic():
    assert route(QUOTED_CHALLENGE)["action"] == "CHAT"


@pytest.mark.parametrize("text", [
    "why are you only on 26 layers?",
    "how many layers are you using?",
    "are you using the gpu?",
    "what's my gpu status?",
    "nvidia-smi",
])
def test_real_gpu_questions_still_report(text):
    """The documented cases this guard exists for: left to CHAT they confabulated
    (one session answered a layer question with After Effects advice)."""
    assert route(text)["action"] == "GPU_STATUS"


def test_quote_stripping_keeps_the_question():
    asked = _eli_outside_quotes(QUOTED_CHALLENGE.lower())
    assert "counterintuitive" in asked
    assert "middle ground" not in asked


def test_a_message_that_is_only_a_quote_still_routes():
    """Stripping everything would leave nothing to match on, so a bare quote
    falls back to the whole text rather than silently becoming unroutable."""
    only = '"how many layers are you using?"'
    assert _eli_outside_quotes(only).strip()
    assert route(only)["action"] == "GPU_STATUS"


def test_short_quotes_are_left_alone():
    """A 12-character floor: stripping every "x" would eat ordinary punctuation
    and emphasis out of normal questions."""
    assert "gpu" in _eli_outside_quotes('is the "gpu" busy?')


def test_apostrophes_are_not_quote_marks():
    """An apostrophe is not a quote mark in English. Including it made
    "you're building..." read as a quoted span and ate half the sentence,
    including the words that decided the route."""
    kept = _eli_outside_quotes("why aren't you using the gpu, isn't it idle?")
    assert "gpu" in kept and "idle" in kept
