"""Locks on the operator's own settings being tried first, and on answers being
worth the wait they cost.

From a live 2.2.0 session running a 22.28GB / 30B model on a card with 6.5GB
free. Single replies took 57s, 136s, 186s. What came back:

    user> So are you somewhat back to normal? No more spouting nonsense?
    ELI > Yes. I've stopped spouting nonsense.

Three separate causes, none of them the model being slow:

1. THE VOICE SAID BE SHORT. Six places defined ELI as "terse" — persona.txt,
   three prompts in engine.py, context_synthesiser. On a machine where a reply
   costs two minutes, an instruction to be brief is the wrong instruction.
   "No filler" is worth keeping; "terse" is not.

2. THE BUDGET DID NOT SCALE. mode_presets() documents "MODEL-AGNOSTIC capability
   scaling ... instead of staying throttled at the small-model defaults", and
   then capped quick at a flat 1024 and standard at a flat 3072 while every
   other preset used _tok() and scaled with tier. A 30B model got a 7B budget.

3. THE USER'S SETTINGS WERE NEVER TRIED. smart-fit ran first and its reduced
   result was queued ahead of "requested", so a config the operator explicitly
   chose in the startup dialog sat at position 2 behind one that always loaded.
   The setting was a suggestion, not a setting.

Nothing here hardcodes a new number. (2) applies the module's own existing
scaling function to the two presets that were skipping it, and is byte-identical
on a small model.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ── 1. the voice no longer instructs brevity ───────────────────────────────
VOICE_FILES = [
    "eli/cognition/persona.txt",
    "eli/cognition/context_synthesiser.py",
    "eli/kernel/engine.py",
]


@pytest.mark.parametrize("rel", VOICE_FILES)
def test_the_base_voice_does_not_ask_for_terseness(rel):
    import re
    text = (REPO / rel).read_text(encoding="utf-8")
    # Word-boundary: "terse" as a voice instruction, not a substring of prose.
    assert not re.search(r"\bterse\b", text, re.I), \
        f"{rel} still instructs the model to be terse"


def test_the_character_is_intact():
    """Removing 'terse' must not turn ELI into a cheerful assistant — the point
    was the length instruction, not the personality."""
    persona = (REPO / "eli/cognition/persona.txt").read_text(encoding="utf-8").lower()
    for trait in ("direct", "dry", "no flattery", "no filler"):
        assert trait in persona, f"lost '{trait}' from the persona"


def test_padding_is_still_discouraged():
    """"Say more" must not become "waffle"."""
    persona = (REPO / "eli/cognition/persona.txt").read_text(encoding="utf-8").lower()
    assert "filler" in persona or "padding" in persona


def test_a_scoped_terse_tone_is_still_allowed():
    """The 'exasperated' entry in the emotion palette is a deliberate, temporary
    tone — it is not the base voice and must survive."""
    palette = (REPO / "eli/cognition/emotion_palette.py").read_text(encoding="utf-8")
    assert "terse" in palette.lower(), "the scoped exasperated tone was removed too"


# ── 2. budgets scale with the model, and do not shrink small ones ──────────
def _presets(scale, n_ctx=12192, max_tokens=6000, monkeypatch=None):
    import eli.core.model_tier as MT
    from eli.core.startup_hardware_optimizer import mode_presets
    monkeypatch.setattr(MT, "tier_scale", lambda: scale)
    return mode_presets(n_ctx, max_tokens)


def test_small_model_budgets_are_unchanged(monkeypatch):
    """Behaviour-preserving where it matters most — modest hardware."""
    p = _presets(1.0, monkeypatch=monkeypatch)
    assert p["quick"]["max_tokens"] == 1024
    assert p["standard"]["max_tokens"] == 3072


@pytest.mark.parametrize("scale,expected_quick", [(1.5, 1536), (2.5, 2560), (4.0, 4096)])
def test_bigger_models_get_bigger_budgets(monkeypatch, scale, expected_quick):
    p = _presets(scale, monkeypatch=monkeypatch)
    assert p["quick"]["max_tokens"] == expected_quick


def test_quick_never_exceeds_the_window_budget(monkeypatch):
    """Scaling must still respect what the context can actually hold."""
    p = _presets(4.0, max_tokens=800, monkeypatch=monkeypatch)
    assert p["quick"]["max_tokens"] <= 800


def test_no_preset_carries_a_flat_ceiling_any_more():
    """quick and standard were the only two bypassing _tok(); the docstring
    claimed all of them scaled."""
    src = (REPO / "eli/core/startup_hardware_optimizer.py").read_text(encoding="utf-8")
    start = src.index("def mode_presets(")
    body = src[start:src.index("\ndef ", start + 10)]
    for bad in ("min(max_tokens, 1024)", "min(max_tokens, 3072)"):
        assert bad not in body, f"flat ceiling {bad} is back"


# ── 3. the operator's settings are attempted first ────────────────────────
def test_the_users_own_settings_are_the_first_load_attempt():
    """smart-fit's reduced result used to be queued ahead of them, so a config
    the operator explicitly chose was never tried."""
    src = (REPO / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    requested = src.index('_add_attempt("requested"')
    smartfit = src.index('_add_attempt("smart-fit"')
    assert requested < smartfit, "ELI still overrules the user before the driver does"


def test_the_calculated_fit_is_still_the_fallback():
    """Honouring the setting must not remove the safety net for hardware that
    genuinely cannot take it."""
    src = (REPO / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert '_add_attempt("smart-fit"' in src
    for rung in ('"live-tuner-gpu"', '"lower-batch-half"', '"cpu-fallback"'):
        assert rung in src, f"lost the {rung} fallback"


def test_requested_is_queued_once_not_twice():
    """It moved; the old call site had to go, or the ladder carries a duplicate."""
    src = (REPO / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert src.count('_add_attempt("requested"') == 1
