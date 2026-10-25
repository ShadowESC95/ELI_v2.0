"""ELI must not assert its own accelerator state without having checked.

Live at 2.3.26, ungrounded, with 28 of the 99 requested layers on the card and
the user having just said so:

    "The GPU's back to full offload, the documentary is playing on loop..."

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
        "assumptions. The GPU's back to full offload, the documentary is playing on "
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


def test_what_the_hardware_is_doing_is_not_said_without_measuring_it(monkeypatch):
    """"Your RTX 2060 Supers are sitting at idle" while a model filled both cards: any wording of the
    class, and the cards' own model numbers count as naming them."""
    from types import SimpleNamespace
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda *a, **k: SimpleNamespace(
        gpus=[{"name": "NVIDIA GeForce RTX 2060 SUPER"}, {"name": "NVIDIA GeForce RTX 2060 SUPER"}]))
    reply = ("Point taken. Your RTX 2060 Supers are sitting at idle. The GPUs are gathering dust right now. "
             "I can index your physics folder.")
    out = drop_unverified_self_status(reply)
    assert "2060" not in out and "gathering dust" not in out and "physics folder" in out
    assert drop_unverified_self_status(reply, is_grounded=True) == reply
    assert drop_unverified_self_status("Your idle thoughts are welcome. The card game was fun.") == \
        "Your idle thoughts are welcome. The card game was fun."
