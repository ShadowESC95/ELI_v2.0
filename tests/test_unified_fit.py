"""Joint VRAM+RAM planner and fit-priority profiles."""
import pytest

from eli.core.hardware_profile import (
    FIT_PRIORITY_BALANCED,
    FIT_PRIORITY_MAX_CTX,
    FIT_PRIORITY_MAX_GPU,
    _layers_for_size,
    normalize_fit_priority,
    smart_fit_config,
    unified_fit_config,
)

MODEL_GB = 8.89
TOTAL = 32
USER_CTX, USER_BATCH = 10384, 512
FREE_VRAM_MB = 6346
AVAIL_RAM_GB = 32.0


def test_normalize_fit_priority_aliases():
    assert normalize_fit_priority("max-gpu") == FIT_PRIORITY_MAX_GPU
    assert normalize_fit_priority("MAX_CTX") == FIT_PRIORITY_MAX_CTX
    assert normalize_fit_priority("nonsense") == FIT_PRIORITY_BALANCED


def test_balanced_preserves_ctx_on_tight_vram():
    ctx, layers, batch = smart_fit_config(
        MODEL_GB, FREE_VRAM_MB,
        user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=700, kv_quantized=True, total_layers=TOTAL,
        fit_priority=FIT_PRIORITY_BALANCED,
    )
    assert ctx == USER_CTX
    assert 0 < layers < 99


def test_max_gpu_keeps_more_layers_than_balanced():
    balanced = smart_fit_config(
        MODEL_GB, FREE_VRAM_MB,
        user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=700, kv_quantized=True, total_layers=TOTAL,
        fit_priority=FIT_PRIORITY_BALANCED,
    )
    max_gpu = smart_fit_config(
        MODEL_GB, FREE_VRAM_MB,
        user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=700, kv_quantized=True, total_layers=TOTAL,
        fit_priority=FIT_PRIORITY_MAX_GPU,
    )
    assert max_gpu[1] >= balanced[1]


def test_max_ctx_prefers_cpu_spill_for_context():
    max_ctx = smart_fit_config(
        MODEL_GB, FREE_VRAM_MB,
        user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=700, kv_quantized=True, total_layers=TOTAL,
        fit_priority=FIT_PRIORITY_MAX_CTX,
    )
    assert max_ctx[0] == USER_CTX
    assert max_ctx[1] <= 99


def test_unified_fit_ram_slider_affects_dgpu_spill(monkeypatch):
    monkeypatch.setenv("ELI_RAM_BUDGET_PERCENT", "15")
    tight = unified_fit_config(
        MODEL_GB, FREE_VRAM_MB, AVAIL_RAM_GB,
        user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=700, kv_quantized=True, total_layers=TOTAL,
        fit_priority_mode=FIT_PRIORITY_MAX_CTX,
        gpu_integrated=False,
    )
    monkeypatch.setenv("ELI_RAM_BUDGET_PERCENT", "75")
    loose = unified_fit_config(
        MODEL_GB, FREE_VRAM_MB, AVAIL_RAM_GB,
        user_ctx=USER_CTX, user_batch=USER_BATCH,
        reserve_mb=700, kv_quantized=True, total_layers=TOTAL,
        fit_priority_mode=FIT_PRIORITY_MAX_CTX,
        gpu_integrated=False,
    )
    assert tight[0] >= 2048
    assert loose[0] >= tight[0]


def test_unified_fit_cpu_only_uses_ram_budget():
    ctx, layers, batch = unified_fit_config(
        3.28, 0, 16.0,
        user_ctx=16384, user_batch=256,
        reserve_mb=512, kv_quantized=True,
        total_layers=_layers_for_size(3.28),
        force_cpu=True,
    )
    assert layers == 0
    assert ctx >= 2048
    assert batch >= 128


def test_unified_fit_igpu_merges_budgets():
    ctx, layers, batch = unified_fit_config(
        MODEL_GB, 2048, 16.0,
        user_ctx=8192, user_batch=256,
        reserve_mb=400, kv_quantized=True, total_layers=TOTAL,
        gpu_integrated=True,
    )
    assert ctx >= 2048
    assert batch >= 128
