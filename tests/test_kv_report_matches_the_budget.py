"""The tuning panel must report the KV size it is actually budgeting.

Live at 2.3.9 on a 2060 SUPER, four lines apart in one tuning run:

    KV cache: q4_0 (4× more ctx for the same VRAM, minimal quality loss)
    ...
    28/32 layers on GPU (KV 1901MB + 350MB CUDA overhead)

1901MB is the fp16 figure. The loader had reserved 475MB — exactly 4× less,
because it *was* using q4_0, as the first line says. Every fit call passed
`kv_quantized=kv_q`; only the report line omitted it.

Why it matters beyond tidiness: overstating KV fourfold makes context look like the
lever for winning back GPU layers. It is nearly the weakest one. On this model
(5.03GB / 32 layers → 161MB per layer) at q4_0, cutting 1904 tokens frees 87MB —
half a layer. The panel implied roughly two, so the operator cut ctx expecting
layers back and got 0.5 of one.

What was true all along: the cache was fp16 in every load. The type was handed
to llama-cpp-python as `cache_type_k`, a name it ignores, so the 1901MB line was the one that
matched what loaded and the 475MB reservation was the fiction. And a real q4_0 cache answers
wrongly (measured), so the quantized cache is q8_0: 34/64 of fp16, not a quarter. The figures
below are that cache's.
"""
import pytest

from eli.core.hardware_profile import _CUDA_OVERHEAD_MB, _kv_cache_mb


def test_quantised_kv_is_about_half_of_fp16():
    """The premise: the quantized cache is q8_0 (34 bytes for 32 values against fp16's 64)."""
    fp16 = _kv_cache_mb(10384, 32, quant=False)
    q8 = _kv_cache_mb(10384, 32, quant=True)
    assert round(fp16 / q8, 2) == 1.88


def test_the_reported_kv_matches_the_budgeted_kv():
    """The invariant that was broken: report and fit must use the same figure."""
    import inspect

    from eli.core import hardware_profile as hp

    src = inspect.getsource(hp.recommend)
    line = [
        l for l in src.splitlines()
        if "layers on GPU" in l or ("_kv_cache_mb(rec.n_ctx" in l)
    ]
    joined = "\n".join(line)
    assert "quant=kv_q" in joined, (
        "the KV figure in the panel is computed without the quantisation flag the "
        "fit uses — it will overstate KV nearly twofold on any card using a quantized cache"
    )


@pytest.mark.parametrize("ctx,layers,expected", [
    (10384, 32, 1010),
    (12288, 32, 1195),
    (4096, 32, 398),
])
def test_quantised_kv_sizes_for_a_2060_class_card(ctx, layers, expected):
    assert round(_kv_cache_mb(ctx, layers, quant=True)) == expected


def test_context_is_a_weak_lever_for_gpu_layers():
    """Documents the arithmetic the panel was hiding, so a future change that makes
    ctx look decisive again has to argue with a number."""
    layers, model_gb = 32, 5.03
    per_layer_mb = (model_gb * 1024) / layers
    freed = _kv_cache_mb(12288, layers, quant=True) - _kv_cache_mb(10384, layers, quant=True)
    assert freed < 2 * per_layer_mb, "cutting ~1900 ctx should buy about one layer, not several"
    assert round(freed / per_layer_mb, 1) == 1.2


def test_the_panel_states_the_per_1k_cost():
    """So the trade-off is visible without the operator doing the division."""
    import inspect

    from eli.core import hardware_profile as hp

    assert "per 1k ctx" in inspect.getsource(hp.recommend)


def test_cuda_overhead_is_still_reported_separately():
    """It is a fixed cost, not part of KV, and conflating them would hide the same
    trade-off in a different way."""
    assert _CUDA_OVERHEAD_MB > 0
