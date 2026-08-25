"""A repeated opening STEM is a tic, however the sentence continues.

The earlier fix compared whole first sentences and worked while the tic WAS the
whole sentence ("You're not wrong."). The model since learned to append an
em-dash clause; because the clause varies every time, first-sentence similarity
falls to ~0.5 against a 0.92 threshold. Live at 2.3.27, four of six replies in
one session opened "You're not wrong -" and the guard fired on none of them:

    "You're not wrong — I was running a 27B param model earlier today..."
    "You're not wrong — I was vague, and that's on me."
    "You're not wrong — and I'm not exactly the kind of AI that complains..."

To the reader that is the same tic the guard exists to stop.
"""
import pytest

try:
    from eli.kernel.engine import _is_repeat_of_recent, _opening_stem
except ImportError:
    from eli.kernel.stages.guards import _is_repeat_of_recent, _opening_stem

_FIRST = "You're not wrong — I was running a 27B param model earlier today, and it's a beast."


@pytest.mark.parametrize("later", [
    "You're not wrong — I was vague, and that's on me.",
    "You're not wrong — and I'm not exactly the kind of AI that complains about hardware.",
    "You're not wrong, the 2060 is a relic but it still has enough juice.",
])
def test_the_observed_tic_is_caught(later):
    assert _is_repeat_of_recent(later, [_FIRST]), later


@pytest.mark.parametrize("distinct", [
    "Right, the 27B is a different beast entirely and needs more VRAM than you have.",
    "Honestly that depends on what you are asking about, so let me check the runtime first.",
    "The second film is Reloaded, and it does drag in the middle if you are honest.",
])
def test_genuinely_different_openings_are_not_flagged(distinct):
    assert not _is_repeat_of_recent(distinct, [_FIRST]), distinct


def test_the_stem_stops_at_the_continuation():
    a = _opening_stem("You're not wrong — I was vague.")
    b = _opening_stem("You're not wrong, the 2060 is a relic.")
    assert a == b, f"{a!r} != {b!r}"


def test_a_very_short_opening_is_not_judged():
    """'Okay.' repeated is not the failure being fixed."""
    assert not _is_repeat_of_recent("Okay.", ["Okay."])
