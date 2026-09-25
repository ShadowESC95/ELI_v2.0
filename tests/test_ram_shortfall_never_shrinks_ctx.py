"""A RAM shortfall for memory-mapped weights must not throw away ctx, and the tuner's own
layer count must never come back as the operator's pin."""
from __future__ import annotations

from eli.core import hardware_profile as hp
from eli.core.runtime_settings import pinned_gpu_layers_for_model

MODEL = "/models/Qwen3.6-35B-A3B-Q4_K_M.gguf"


def _fit(priority, ram_gb, user_layers=None):
    return hp.unified_fit_config(
        21.17, 6576, ram_gb, user_ctx=12248, user_batch=256, reserve_mb=700,
        kv_quantized=True, model_path=MODEL, total_layers=40,
        fit_priority_mode=priority, user_gpu_layers=user_layers)


def test_weights_larger_than_the_ram_budget_keep_the_requested_ctx():
    for ram in (18.4, 25.3):
        ctx, layers, _batch = _fit("max_ctx", ram)
        assert ctx == 12248
        assert layers >= 5


def test_a_pinned_layer_count_is_still_a_ceiling():
    ctx, layers, _batch = _fit("max_ctx", 18.4, user_layers=5)
    assert ctx == 12248 and layers <= 5


def test_cpu_only_still_reduces_ctx_to_the_ram_budget():
    ctx, layers, _batch = hp.unified_fit_config(
        4.0, 0, 3.0, user_ctx=32768, user_batch=512, kv_quantized=False,
        model_path="/m/small.gguf", total_layers=32, force_cpu=True)
    assert layers == 0 and ctx < 32768


def _settings(**over):
    base = {"n_gpu_layers": 5, "n_gpu_layers_model": MODEL.rsplit("/", 1)[-1], "n_gpu_layers_ctx": 12248}
    base.update(over)
    return base


def test_a_pin_the_tuner_wrote_is_not_a_pin():
    assert pinned_gpu_layers_for_model(MODEL, _settings(n_gpu_layers_source="tuner"), current_ctx=12248) is None


def test_an_old_file_whose_pin_equals_the_tuner_mirror_is_not_a_pin():
    assert pinned_gpu_layers_for_model(MODEL, _settings(hw_profile_n_gpu_layers=5), current_ctx=12248) is None


def test_a_pin_the_operator_set_still_applies():
    assert pinned_gpu_layers_for_model(MODEL, _settings(n_gpu_layers_source="user"), current_ctx=12248) == 5
    assert pinned_gpu_layers_for_model(MODEL, _settings(hw_profile_n_gpu_layers=9), current_ctx=12248) == 5
