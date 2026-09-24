"""Auto context must be derived from the model and the machine, never a constant.

The operator's stated rule: ctx is theirs to choose (4k..100k+) and nothing in the
project may impose a fixed figure such as 12288 -- it ships to other people's
machines. "Auto" used to aim at DEFAULT_N_CTX for every model everywhere.
"""
import pytest

import eli.core.hardware_profile as hp
import eli.core.startup_hardware_optimizer as sho


def _target(train, *, vram=0, ram=64.0, size=4.0, use_gpu=False, monkeypatch=None):
    monkeypatch.setattr(sho, "_gguf_metadata_ctx", lambda p: train)
    return hp.auto_ctx_target("m.gguf", size, free_vram_mb=vram,
                              available_ram_gb=ram, use_gpu=use_gpu)


def test_follows_the_models_trained_context(monkeypatch):
    monkeypatch.delenv("ELI_CTX_FRACTION", raising=False)
    small = _target(4096, monkeypatch=monkeypatch)
    big = _target(131072, monkeypatch=monkeypatch)
    assert small < big
    assert small <= 4096
    assert big != 12288 and small != 12288


def test_an_unreadable_header_does_not_smuggle_in_a_constant(monkeypatch):
    """No metadata -> the memory limit alone decides, not train_ctx_for_model's fallback."""
    monkeypatch.delenv("ELI_MODEL_TRAIN_CTX", raising=False)
    monkeypatch.setattr(sho, "_gguf_metadata_ctx", lambda p: 0)
    roomy = hp.auto_ctx_target("m.gguf", 4.0, free_vram_mb=0, available_ram_gb=64.0, use_gpu=False)
    tight = hp.auto_ctx_target("m.gguf", 4.0, free_vram_mb=0, available_ram_gb=8.0, use_gpu=False)
    assert roomy > tight and roomy != 8192


def test_the_fraction_setting_scales_it(monkeypatch):
    monkeypatch.setenv("ELI_CTX_FRACTION", "0.5")
    half = _target(32768, monkeypatch=monkeypatch)
    monkeypatch.setenv("ELI_CTX_FRACTION", "0.9")
    most = _target(32768, monkeypatch=monkeypatch)
    assert half < most


def test_less_memory_lowers_it(monkeypatch):
    monkeypatch.delenv("ELI_CTX_FRACTION", raising=False)
    roomy = _target(1_000_000, ram=64.0, monkeypatch=monkeypatch)
    tight = _target(1_000_000, ram=6.0, size=4.0, monkeypatch=monkeypatch)
    assert tight < roomy


def test_vram_only_counts_when_offloading(monkeypatch):
    monkeypatch.delenv("ELI_CTX_FRACTION", raising=False)
    cpu = _target(1_000_000, vram=24000, ram=8.0, use_gpu=False, monkeypatch=monkeypatch)
    gpu = _target(1_000_000, vram=24000, ram=8.0, use_gpu=True, monkeypatch=monkeypatch)
    assert gpu > cpu


def test_result_is_grain_aligned_and_never_below_the_floor(monkeypatch):
    for train in (2048, 5000, 33333, 262144):
        v = _target(train, monkeypatch=monkeypatch)
        assert v >= 2048 and v % 2048 == 0


def test_constant_is_only_the_last_resort(monkeypatch):
    monkeypatch.setattr(sho, "_gguf_metadata_ctx", lambda p: 0)

    def _unmeasurable(*a, **k):
        raise RuntimeError("no memory reading")
    monkeypatch.setattr(hp, "cpu_ram_budget_mb", _unmeasurable)
    v = hp.auto_ctx_target(None, 0.0, free_vram_mb=0, available_ram_gb=0.0, use_gpu=False)
    from eli.core.runtime_settings import DEFAULT_N_CTX
    assert v == DEFAULT_N_CTX


def test_an_operator_chosen_ctx_is_never_replaced(monkeypatch):
    """4k and 100k are both the operator's to pick; recommend() must anchor on it."""
    monkeypatch.setattr(sho, "_gguf_metadata_ctx", lambda p: 8192)
    hw = hp.detect_hardware()
    models = [{"name": "m", "path": "m.gguf", "size_bytes": 4_000_000_000, "size_gb": 4.0}]
    for chosen in (4096, 102400):
        rec = hp.recommend(hw, models, user_ctx=chosen)
        assert rec.n_ctx <= chosen
