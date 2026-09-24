"""Smart loader fit: reduce GPU layers → batch → ctx, in that order, to fit
the VRAM left after vision+nomic. Pure math — no GPU needed."""
from eli.core.hardware_profile import smart_fit_config, _layers_for_size

# A 7B-class Q3 model on an 8GB card (q4_0 KV), user asked for 16384 ctx / 256 batch.
MODEL_GB = 3.28
TOTAL = _layers_for_size(MODEL_GB)  # 32
USER_CTX, USER_BATCH = 16384, 256


def _fit(free_mb, reserve=700, user_gpu_layers=None):
    return smart_fit_config(
        MODEL_GB, free_mb, user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=reserve, kv_quantized=True, total_layers=TOTAL,
        user_gpu_layers=user_gpu_layers,
    )


def test_generous_vram_keeps_user_settings_full_offload():
    ctx, layers, batch = _fit(24000)
    assert ctx == USER_CTX and batch == USER_BATCH
    assert layers == 99  # all layers on GPU


def test_tight_vram_reduces_layers_first_preserving_ctx_and_batch():
    # Enough that shedding *some* GPU layers fits — ctx & batch must be untouched.
    ctx, layers, batch = _fit(5000)
    assert ctx == USER_CTX, "ctx must be preserved before layers are exhausted"
    assert batch == USER_BATCH, "batch must not drop while layer reduction suffices"
    assert 0 < layers < 99, f"expected partial GPU offload, got {layers}"


def test_tighter_vram_reduces_batch_before_ctx():
    # Tight enough that layer-floor alone fails and batch must drop — but ctx
    # should still be preserved (batch is reduced before ctx).
    ctx, layers, batch = _fit(3400)
    assert ctx == USER_CTX, "ctx must be preserved until batch reduction is exhausted"
    assert batch < USER_BATCH, "batch should have been reduced"


def test_tight_vram_preserves_ctx_by_shedding_layers():
    # "ctx last, quality over speed": when VRAM is tight but the KV cache still fits
    # CPU-only, ctx is PRESERVED and the GPU layers are shed instead (trade speed,
    # keep context — the fraction is the user's speed↔context dial).
    # (free=2700 is the demonstration point under the 128 batch floor — batch never
    # drops below 128, so a touch more VRAM is needed to hold full ctx at 0 layers.)
    ctx, layers, batch = _fit(2700)
    assert ctx == USER_CTX, "ctx preserved by shedding GPU layers before crushing ctx"
    assert layers == 0, "tight VRAM sheds to CPU-only to keep ctx"
    assert batch >= 128, "batch floor (128) is honoured even at the tightest GPU offload"


def test_very_tight_vram_finally_reduces_ctx():
    # Only when even CPU-only (0 layers) can't hold the KV cache does ctx finally drop.
    ctx, layers, batch = _fit(1500)
    assert ctx < USER_CTX, "ctx drops only when 0 layers + min batch still overflow"
    assert ctx >= 2048


def test_no_budget_falls_to_cpu():
    ctx, layers, batch = _fit(0)
    assert layers == 0  # CPU-only


def test_reduction_priority_order_holds_monotonically():
    # As VRAM shrinks, ctx should never drop before batch, and batch never
    # before layers leave full offload.
    prev_layers, prev_batch, prev_ctx = 99, USER_BATCH, USER_CTX
    for free in (24000, 6000, 5000, 4000, 3400, 3000, 2600, 2200):
        ctx, layers, batch = _fit(free)
        # ctx only changes after batch has already been reduced from user value
        if ctx < USER_CTX:
            assert batch <= USER_BATCH
        # batch only changes after layers left full offload (99)
        if batch < USER_BATCH:
            assert layers != 99


# gpu_layers is a ceiling like ctx and batch: freed headroom must not backfill more layers.
def test_user_gpu_layers_is_never_exceeded_by_the_backfill():
    # Generous VRAM: with no ceiling this backfills to 99 (all 32 layers), same
    # as test_generous_vram_keeps_user_settings_full_offload above.
    ctx, layers, batch = _fit(24000, user_gpu_layers=10)
    assert layers == 10, (
        f"operator asked for 10 GPU layers; smart-fit must not hand back more "
        f"even when VRAM allows it, got {layers}"
    )
    assert ctx == USER_CTX and batch == USER_BATCH


def test_user_gpu_layers_ceiling_still_sheds_when_it_does_not_fit():
    # Tight VRAM: 10 layers still doesn't fit, so the ceiling must still yield
    # to the same shed-first behaviour as an unconstrained fit.
    ctx, layers, batch = _fit(2700, user_gpu_layers=10)
    assert layers <= 10
    assert ctx == USER_CTX, "ctx preserved by shedding GPU layers before crushing ctx"


def test_user_gpu_layers_ceiling_matches_unconstrained_when_above_full_offload():
    # A ceiling at or above the model's own layer count is a no-op -- same
    # result as passing no ceiling at all.
    unconstrained = _fit(24000)
    ceiling_above_total = _fit(24000, user_gpu_layers=99)
    assert unconstrained == ceiling_above_total
