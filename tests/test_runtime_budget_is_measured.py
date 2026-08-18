"""Runtime parameters are derived from measured memory, not size bands.

`dynamic_runtime_budget.derive_budget` picked ctx from
{16384, 12288, 8192, 6144, 4096} by RAM band, gpu_layers from
{99, 35, 24, 16, 8, 4} by model-size band, and batch from {512, 384, 256, 128}
by VRAM band. None of it measured the KV cache or the compute graph, so it
disagreed with the loader: on a live 2.3.0 launch the table said ctx=12288 and
the resident context was 10384, on the same machine, at the same moment — while
the tuning panel displayed a third number, 6144, labelled "AUTHORITATIVE".

The measured arithmetic already existed in hardware_profile.smart_fit_config
(KV bytes per token, compute-graph reserve, MB per layer from the model's own
size). This derives from it instead.
"""
import pytest

from eli.core import dynamic_runtime_budget as drb


def test_the_bucket_ladders_are_gone():
    """Strip comments before matching. Three times this session a test was
    written that matched the very comment describing the bug, and passed
    against code that still had it."""
    import inspect
    src = inspect.getsource(drb.derive_budget)
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#") and l.strip() != '"""')
    for bucket in ("16384", "12288", "6144", "= 35", "= 24", "= 16", "384"):
        assert bucket not in code, f"a hardcoded {bucket} bucket survived in derive_budget"
    assert "smart_fit_config" in code, "derive_budget must use the measured fit"


def test_the_output_budget_is_a_share_not_a_band():
    """ctx 6143 vs 6144 used to differ by 1024 output tokens for no reason."""
    a, b = drb._output_budget_for_ctx(6143), drb._output_budget_for_ctx(6144)
    assert abs(a - b) <= 2
    assert drb._output_budget_for_ctx(16384) <= drb._MAX_OUTPUT_TOKENS
    assert drb._output_budget_for_ctx(1024) >= 512


def test_ctx_ceiling_scales_with_ram_rather_than_stepping():
    """Twice the RAM must not mean 'the same bucket'."""
    small = drb._ctx_ceiling_for_ram(8, 4.68)
    mid = drb._ctx_ceiling_for_ram(16, 4.68)
    assert mid > small, "the ceiling did not move with RAM"
    assert abs(mid - 2 * small) <= 2, "the ceiling is not proportional to RAM"


def test_a_heavier_model_gets_a_smaller_ceiling():
    """KV cost per token rises with layer count, so the ceiling must fall."""
    light = drb._ctx_ceiling_for_ram(16, 4.68)
    heavy = drb._ctx_ceiling_for_ram(16, 40.0)
    assert heavy < light


def test_the_ceiling_never_exceeds_the_training_window():
    """llama.cpp warns `n_ctx_seq > n_ctx_train`; beyond it quality degrades."""
    assert drb._ctx_ceiling_for_ram(1024, 4.68) <= drb._ABSOLUTE_CTX_CAP


def test_the_ceiling_has_a_floor():
    assert drb._ctx_ceiling_for_ram(0, 4.68) >= drb._MIN_CTX
    assert drb._ctx_ceiling_for_ram(-5, 4.68) >= drb._MIN_CTX


def test_the_per_token_cost_is_the_loaders_own_measurement():
    """Not a constant invented in this module — an earlier draft did exactly
    that and implied an 18k context on an 8GB machine."""
    import inspect
    src = inspect.getsource(drb._ctx_ceiling_for_ram)
    assert "_kv_cache_mb" in src and "_layers_for_size" in src


def test_batch_scales_with_free_vram():
    assert drb._batch_ceiling_for_vram(500) == drb._MIN_BATCH
    assert drb._batch_ceiling_for_vram(12000) >= drb._batch_ceiling_for_vram(3000)
    assert drb._batch_ceiling_for_vram(12000) <= 512


@pytest.mark.parametrize("vram", [0, 500, 4000, 16000])
def test_derive_budget_never_raises(vram, monkeypatch):
    monkeypatch.setattr(drb, "detect_gpu", lambda: ("test", vram, vram))
    b = drb.derive_budget("")
    assert b.n_ctx >= drb._MIN_CTX
    assert b.batch_size >= drb._MIN_BATCH
    assert b.n_gpu_layers >= 0


def test_no_gpu_means_no_layers(monkeypatch):
    monkeypatch.setattr(drb, "detect_gpu", lambda: ("none", 0, 0))
    assert drb.derive_budget("").n_gpu_layers == 0
