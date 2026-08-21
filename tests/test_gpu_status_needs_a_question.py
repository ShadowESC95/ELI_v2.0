"""Talking about layers is not asking for a VRAM dump.

`_gpu_layer_question` triggered on `layers?` plus ANY of you/your/gpu/model/…,
with no requirement that the turn was asking anything — and it returns confidence
0.995, which overrides everything downstream.

Live at 2.3.13, two consecutive conversational turns were answered with the same
VRAM report:

    "yeah you aree right about the layers, we need to claw some back alright"
    "i don't care about that, I was talking about incrasing your layers somehow"

Neither requested a status report. The second says outright that the first report
was unwanted — and got it again, verbatim.

An earlier fix taught this guard to ignore words inside QUOTES, after a user
quoted ELI's own sentence back and had it answered with a VRAM dump. These were
not quotes; they were the user talking. The missing condition was never "is this
quoted", it was "is this a request".
"""
from __future__ import annotations

import pytest

from eli.execution.router_enhanced import _eli_runtime_cognition_failure_guard as guard


def _dumps(text: str) -> bool:
    return (guard(text) or {}).get("action") == "GPU_STATUS"


@pytest.mark.parametrize("text", [
    "yeah you aree right about the layers, we need to claw some back alright",
    "i don't care about that, I was talking about incrasing your layers somehow",
    "we should claw back some layers at some point",
    "the layers thing is annoying me",
    "i was talking about your layers",
    "your gpu layers are the bottleneck here",
])
def test_conversation_about_layers_stays_conversation(text):
    assert _dumps(text) is False, f"data-dumped on: {text!r}"


@pytest.mark.parametrize("text", [
    "how many layers are you using?",
    "are you using the gpu?",
    "show me your gpu status",
    "what layers is the model loaded with",
    "check vram usage",
    "nvidia-smi",
    "tell me your vram usage",
    "how much vram is free",
])
def test_real_requests_still_get_the_grounded_report(text):
    """The guard exists for good reason — left to CHAT, 'are you using the gpu?'
    once drew 'I am running on CPU, not GPU' while layers were offloaded."""
    assert _dumps(text) is True, f"failed to report on: {text!r}"


@pytest.mark.parametrize("text", [
    "i don't care about the gpu status",
    "that's not what i asked about the gpu",
    "forget that, your gpu is fine",
    "never mind the vram",
])
def test_an_explicit_brush_off_is_not_a_request(text):
    """Whatever else the sentence contains, being told the last report was
    unwanted must not produce another one."""
    assert _dumps(text) is False


def test_graphics_layers_are_still_excluded():
    """Pre-existing behaviour: 'layers' in a design context is not GPU offload."""
    assert _dumps("how do i merge layers in photoshop?") is False
