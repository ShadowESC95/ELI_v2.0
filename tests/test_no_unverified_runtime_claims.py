"""ELI must not assert its own accelerator state without having checked.

Live at 2.3.26, ungrounded, with 28 of the 99 requested layers on the card and
the user having just said so:

    "The GPU's back to full offload, the matrix is playing on loop..."

Health claims ("all systems nominal") were already governed; hardware claims
were not, so this passed every guard and read as a flat lie. When the turn IS
grounded -- GPU_STATUS reads nvidia-smi and the live snapshot -- the same
sentence is legitimate and must survive.
"""
from eli.cognition.output_governor import (
    claims_unverified_self_status,
    drop_unverified_self_status,
)

_BAD = ("You're not exactly wrong, but I'm still running on a few half-baked "
        "assumptions. The GPU's back to full offload, the matrix is playing on "
        "loop, and I've got a 4th sequel in my head.")


def test_the_observed_claim_is_detected():
    assert claims_unverified_self_status(_BAD)


def test_it_is_dropped_when_nothing_was_checked():
    out = drop_unverified_self_status(_BAD, is_grounded=False)
    assert "full offload" not in out.lower()
    assert "half-baked assumptions" in out, "it removed more than the claim"


def test_a_grounded_turn_may_report_the_truth():
    out = drop_unverified_self_status(_BAD, is_grounded=True)
    assert out == _BAD


def test_talking_about_the_users_hardware_is_untouched():
    for keep in ("The GPU in your machine is a 2060 Super, which is plenty.",
                 "Offloading more layers would need free VRAM.",
                 "Your GPU is not the bottleneck here."):
        assert drop_unverified_self_status(keep, is_grounded=False) == keep, keep


def test_it_never_empties_a_reply():
    only = "The GPU's back to full offload."
    assert drop_unverified_self_status(only, is_grounded=False) == only
