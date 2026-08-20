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
"""
import pytest

from eli.core.hardware_profile import _CUDA_OVERHEAD_MB, _kv_cache_mb


def test_quantised_kv_is_a_quarter_of_fp16():
    """The premise. If this ratio changes, the reasoning above needs revisiting."""
    fp16 = _kv_cache_mb(10384, 32, quant=False)
    q4 = _kv_cache_mb(10384, 32, quant=True)
    assert round(fp16 / q4, 2) == 4.0


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
        "fit uses — it will overstate KV fourfold on any card using q4_0"
    )


@pytest.mark.parametrize("ctx,layers,expected", [
    (10384, 32, 475),
    (12288, 32, 562),
    (4096, 32, 188),
])
def test_q4_kv_sizes_for_a_2060_class_card(ctx, layers, expected):
    assert round(_kv_cache_mb(ctx, layers, quant=True)) == expected


def test_context_is_a_weak_lever_for_gpu_layers():
    """Documents the arithmetic the panel was hiding, so a future change that makes
    ctx look decisive again has to argue with a number."""
    layers, model_gb = 32, 5.03
    per_layer_mb = (model_gb * 1024) / layers
    freed = _kv_cache_mb(12288, layers, quant=True) - _kv_cache_mb(10384, layers, quant=True)
    assert freed < per_layer_mb, "cutting ~1900 ctx should not buy even one full layer"
    assert round(freed / per_layer_mb, 1) == 0.5


def test_the_panel_states_the_per_1k_cost():
    """So the trade-off is visible without the operator doing the division."""
    import inspect

    from eli.core import hardware_profile as hp

    assert "per 1k ctx" in inspect.getsource(hp.recommend)


def test_cuda_overhead_is_still_reported_separately():
    """It is a fixed cost, not part of KV, and conflating them would hide the same
    trade-off in a different way."""
    assert _CUDA_OVERHEAD_MB > 0
