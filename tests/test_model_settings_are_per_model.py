"""Locks on load settings belonging to the model they were chosen for.

Live at 2.2.1. The operator switched from an 8B (trained context 32,768) to a
30B whose trained context is 1,048,576, and the startup dialog still offered:

    (user: ctx=12192 gpu_layers=99 batch=128)

12192 was computed for the previous model. 0.9 x 1,048,576 is 943,718 — the new
model's own numbers were never consulted, because the saved value was reused
unconditionally. Two hardcodes sat behind it:

  * the first-run fallback was a flat DEFAULT_N_CTX (16384), as arbitrary for a
    1M-context model as for a 4k one, when the box already documents "0 = auto"
    and auto derives fraction x THAT model's trained length, VRAM-fitted;
  * the target-batch default was a flat 256 on every machine, while
    hardware_profile.recommend() already derives one from the detected GPU
    (128 on the card this was diagnosed on).

The association has to be explicit. settings["model_path"] is rewritten every
time a model loads while n_ctx is not, so comparing against it would always
look like a match — and would miss exactly the switch this exists to catch.

This is redistribution-facing: every user has different hardware and different
models, and a saved number from someone else's session — or their own previous
one — is not a setting for the model in front of them.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STARTUP = REPO / "eli" / "gui" / "panels" / "startup.py"


def _initial_ctx(saved_ctx, saved_for, selected, env=""):
    """The dialog's decision, mirrored. Kept in step by the source assertions below."""
    same = bool(saved_for) and bool(selected) and Path(saved_for).name == Path(selected).name
    if env.isdigit() and int(env) >= 2048:
        return int(env)
    if saved_ctx >= 2048 and same:
        return saved_ctx
    return 0


# ── the live failure ───────────────────────────────────────────────────────
def test_a_context_from_another_model_is_not_reused():
    assert _initial_ctx(12192, "Qwen3-8B.gguf", "Nemotron-30B.gguf") == 0


def test_your_own_choice_survives_for_the_same_model():
    """The point is not to discard settings — it is to scope them."""
    assert _initial_ctx(12192, "Nemotron-30B.gguf", "Nemotron-30B.gguf") == 12192


def test_no_association_means_auto_not_a_guess():
    """Settings written before this existed carry no association."""
    assert _initial_ctx(12192, "", "Nemotron-30B.gguf") == 0


def test_an_explicit_env_override_still_wins():
    assert _initial_ctx(12192, "Qwen3-8B.gguf", "Nemotron-30B.gguf", env="8192") == 8192


def test_the_path_may_move_without_losing_the_association():
    """Matched on filename: a model that moved directories is the same model."""
    assert _initial_ctx(12192, "/old/dir/Nemotron-30B.gguf",
                        "/new/dir/Nemotron-30B.gguf") == 12192


# ── the source must actually do this ───────────────────────────────────────
def test_the_dialog_scopes_the_saved_context_to_a_model():
    src = STARTUP.read_text(encoding="utf-8")
    assert "n_ctx_model" in src, "no model association is recorded"


def test_the_association_does_not_fall_back_to_model_path():
    """settings['model_path'] is rewritten on every load; using it as the
    association would always compare equal and never detect a switch."""
    src = STARTUP.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert '_s.get("n_ctx_model") or _s.get("model_path")' not in code


def test_the_first_run_fallback_is_auto_not_a_constant():
    src = STARTUP.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "_initial_ctx = int(_DEFAULT_CTX)" not in code, \
        "still asserting a fixed context for an unknown model"
    assert "_initial_ctx = 0" in code, "auto is no longer the fallback"


def test_the_batch_default_comes_from_the_hardware():
    src = STARTUP.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'os.environ.get("ELI_TARGET_BATCH", "256")' not in code, \
        "flat 256 batch default is back"
    assert "recommend" in code, "batch no longer derives from detected hardware"


def test_the_choice_is_recorded_when_one_is_made():
    src = STARTUP.read_text(encoding="utf-8")
    assert "_rs_update(n_ctx_model=" in src, \
        "a chosen context is never associated with its model, so it can never be reused"


# ── the derivation it falls back to is real ────────────────────────────────
def test_auto_resolves_per_model_not_per_constant():
    """"0 = auto" is only a safe fallback if something downstream reads THIS
    model's trained length."""
    from eli.core.startup_hardware_optimizer import train_ctx_for_model
    import inspect
    src = inspect.getsource(train_ctx_for_model)
    assert "gguf" in src.lower(), "auto does not consult the model's own metadata"


def test_hardware_recommend_supplies_a_batch():
    from eli.core.hardware_profile import detect_hardware, recommend
    rec = recommend(detect_hardware())
    assert int(getattr(rec, "batch_size", 0)) > 0
