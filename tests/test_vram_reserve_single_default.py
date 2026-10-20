"""Locks on the VRAM headroom having ONE default, and that default loading.

Live failure at 2.1.98 on a 2060 SUPER, 6,346MB free, 4.68GB model, ctx=10384:

    [GUI][LOAD] smart-fit (... reserve=250MB ...): ctx=10384 gpu_layers=99
    [GUI][LOAD] attempt failed: Failed to create llama_context
    [GUI][LOAD] attempt 2/12: hw-profile (ctx=4096 ...)   <- selected

Two faults, and the interesting one is not the loader.

1. The knob had two defaults in four places. The startup dialog's spin box and
   the startup optimizer defaulted to 250; the loader and gguf_inference to 700.
   The dialog EXPORTS its value into ELI_VRAM_RESERVE_MB, so 250 always won.

2. 250 sits on the wrong side of a cliff. Same machine, same model, same ctx:

       reserve=250MB -> "all 99 layers fit"   <- llama.cpp refused it
       reserve=400MB -> 31 layers
       reserve=700MB -> 29 layers             <- loads

   A 150MB swing flips 99 layers to 31, so at 250 the answer sits exactly on
   the driver's allocation boundary and whether it loads depends on
   fragmentation. It had been loading for three releases; on 2.1.98 it did not.

The consequence was not a slower load, it was a broken session: the loader fell
through to a static 4,096 profile and every turn afterwards ran in a window
smaller than its own prompt — replies truncated mid-sentence, then capped at 128
tokens.

hardware_profile.allocate() documents the intended order (GPU layers -> batch ->
shed layers -> ctx LAST, "context is preserved as long as possible"). With a
correct reserve it does exactly that here: ctx=10384 kept, layers reduced to 29.
"""
import pytest

from eli.core import load_plan
from eli.core.hardware_profile import smart_fit_config, vram_reserve_mb
from eli.core.load_plan import Device

# The live case, as logged, and the reserve that case was measured against.
FREE_MB, MODEL_GB, USER_CTX, USER_BATCH = 6346, 4.68, 10384, 128
RESERVE_MB = 700


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("ELI_VRAM_RESERVE_MB", raising=False)
    monkeypatch.setattr(load_plan, "devices", lambda: [Device(0, "CUDA0", "Card", 6346.0, 8192.0, False)])


# ── one source: measured on this machine, or the operator's own figure ─────
def test_nothing_is_held_back_by_a_guess_before_anything_is_measured():
    """It was a fixed 700 MB (400 on integrated GPUs), measured once on one card."""
    assert vram_reserve_mb() == 0


def test_what_was_measured_on_this_machine_is_the_reserve(monkeypatch):
    plan = load_plan.Plan(model_path="m.gguf", n_ctx=8192, n_gpu_layers=9, n_batch=512, n_threads=6,
                          cache_type_k="", cache_type_v="", flash_attn=True, split_mode=1, main_gpu=0,
                          tensor_split=None, experts_in_ram=None, blocks=8, devices=load_plan.devices())
    load_plan.watch_headroom(plan)
    monkeypatch.setattr(load_plan, "devices", lambda: [Device(0, "CUDA0", "Card", 6300.0, 8192.0, False)])
    load_plan.note_headroom()
    assert vram_reserve_mb() == 46


def test_the_spin_box_still_wins_when_set(monkeypatch):
    """The knob must remain a real control."""
    monkeypatch.setenv("ELI_VRAM_RESERVE_MB", "400")
    assert vram_reserve_mb() == 400


@pytest.mark.parametrize("raw", ["", "0", "-1", "junk", "  "])
def test_unusable_values_mean_measured(monkeypatch, raw):
    monkeypatch.setenv("ELI_VRAM_RESERVE_MB", raw)
    assert vram_reserve_mb() == 0


def test_no_module_hardcodes_its_own_default_any_more():
    """Four call sites, two different defaults, and the lowest one won because
    the dialog exports it."""
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'ELI_VRAM_RESERVE_MB["\']?\s*,\s*["\']?\d+')
    offenders = []
    for rel in ("eli/gui/panels/startup.py",
                "eli/core/startup_hardware_optimizer.py",
                "eli/cognition/gguf_inference.py",
                "eli/gui/eli_pro_audio_gui_v2_0.py"):
        text = (repo / rel).read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(rel)
    assert not offenders, f"still carrying their own reserve default: {offenders}"


# ── the default must produce a config that actually loads ───────────────────
def test_the_default_reserve_does_not_claim_every_layer_fits():
    """At 250 the fit said 99 layers and llama.cpp refused to make the context."""
    _, layers, _ = smart_fit_config(
        MODEL_GB, FREE_MB, user_ctx=USER_CTX, user_batch=USER_BATCH,
        kv_quantized=True, reserve_mb=RESERVE_MB)
    assert layers < 99, "still green-lighting a full offload that will not allocate"


def test_the_user_context_survives_the_correction():
    """The whole doctrine: shed layers, keep ctx. The failure did the opposite —
    it kept 99 layers and lost 60% of the context."""
    ctx, layers, _ = smart_fit_config(
        MODEL_GB, FREE_MB, user_ctx=USER_CTX, user_batch=USER_BATCH,
        kv_quantized=True, reserve_mb=RESERVE_MB)
    assert ctx == USER_CTX, f"context cut to {ctx} instead of shedding layers"
    assert layers > 0, "shed the GPU entirely when layer reduction would do"


def test_the_fit_is_not_balanced_on_a_cliff():
    """250 -> 99 layers, 400 -> 31. Sitting on that edge is why three releases
    loaded and the fourth did not. Around the default the answer must be stable."""
    got = [
        smart_fit_config(MODEL_GB, FREE_MB, user_ctx=USER_CTX, user_batch=USER_BATCH,
                         kv_quantized=True, reserve_mb=r)[1]
        for r in (RESERVE_MB - 150, RESERVE_MB, RESERVE_MB + 150)
    ]
    assert max(got) - min(got) <= 8, f"layer count still swings wildly: {got}"


def test_a_bigger_reserve_never_yields_more_layers():
    prev = None
    for r in (400, 700, 1000, 1400):
        _, layers, _ = smart_fit_config(MODEL_GB, FREE_MB, user_ctx=USER_CTX,
                                        user_batch=USER_BATCH, kv_quantized=True,
                                        reserve_mb=r)
        if prev is not None:
            assert layers <= prev, "more headroom produced MORE offload"
        prev = layers


# ── recovery order, when a load fails anyway ───────────────────────────────
