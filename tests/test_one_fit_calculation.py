"""The recommendation must predict the load, not offer a second opinion.

recommend() and smart_fit_config() both decided ctx and GPU layers from free
VRAM — with OPPOSITE policies. recommend() picked layers first and cut context to
pay for them; smart_fit_config keeps the context and sheds layers, cutting ctx
only as a last resort. smart_fit_config is what the load ladder actually runs.

Live at 2.3.4, one second apart on the same machine and model, the Hardware
Tuning tab showed:

    HW Profile (recommended): ctx=8192  gpu_layers=30
    [GUI][LOAD] selected=smart-fit    ctx=12288 gpu_layers=27

The recommendation is displayed to the operator AND stored as the hw_profile_*
fallback used when their settings fail to load, so a second answer is not a
cosmetic problem.
"""
import pathlib

import pytest

from eli.core.hardware_profile import (HardwareProfile, _layers_for_size, recommend,
                                       smart_fit_config, vram_reserve_mb)

MODEL = pathlib.Path("/home/jay/.local/share/ELI_v2/models/Qwen_Qwen3-8B-Q4_K_M.gguf")


def _hw(free_mb: int, total_mb: int = 7752) -> HardwareProfile:
    return HardwareProfile(cpu_threads=12, ram_gb=33.5, available_ram_gb=18.9,
                           has_gpu=True, gpu_name="test GPU", free_vram_mb=free_mb,
                           total_vram_mb=total_mb, vram_gb=total_mb / 1024.0)


def _models(size_gb: float):
    return [{"name": "test.gguf", "path": "/tmp/test.gguf", "size_gb": size_gb}]


def _loader_fit(size_gb: float, free_mb: int, ctx: int, kv_q: bool):
    total = _layers_for_size(size_gb)
    _c, layers, _b = smart_fit_config(size_gb, free_mb, user_ctx=ctx, user_batch=128,
                                      reserve_mb=vram_reserve_mb(), kv_quantized=kv_q,
                                      total_layers=total, min_batch=128)
    return _c, (total if int(layers) >= 99 else int(layers))


@pytest.mark.parametrize("size_gb,free_mb,total_mb", [
    (4.68, 6168, 7752),     # the live case: 8B on a 2060 SUPER
    (4.68, 3000, 4096),     # small card
    (0.7, 6168, 7752),      # 1B — must not be assumed
    (20.0, 6168, 7752),     # 34B on a small card
    (20.0, 24000, 24576),   # 34B with room
    (60.0, 80000, 81920),   # 100B+ on a big card
])
def test_the_recommendation_matches_what_the_loader_would_do(size_gb, free_mb, total_mb):
    hw = _hw(free_mb, total_mb)
    rec = recommend(hw, _models(size_gb))
    kv_q = bool(total_mb < 12000)
    ctx, layers = _loader_fit(size_gb, free_mb, rec.n_ctx, kv_q)
    assert (rec.n_ctx, rec.n_gpu_layers) == (ctx, layers), (
        f"recommendation {rec.n_ctx}/{rec.n_gpu_layers} != load {ctx}/{layers}"
    )


def test_the_opposite_policy_blocks_are_gone():
    """The three blocks that bought layers by cutting context."""
    import inspect
    src = inspect.getsource(recommend)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    for gone in ("after ctx settled", "_MIN_GPU_LAYERS", "from VRAM budget"):
        assert gone not in code, f"a second fit policy survived: {gone}"
    assert "smart_fit_config(" in code, "recommend() no longer runs the loader's fit"


def test_the_fit_is_reported_to_the_operator():
    """The tab shows rec.reasoning; the fit must be visible there, not silent."""
    rec = recommend(_hw(6168), _models(4.68))
    assert any("Fit (same calculation the loader runs)" in r for r in rec.reasoning)


def test_a_cpu_only_machine_is_unaffected():
    hw = HardwareProfile(cpu_threads=8, ram_gb=16.0, available_ram_gb=10.0, has_gpu=False,
                         gpu_name="", free_vram_mb=0, total_vram_mb=0, vram_gb=0.0)
    rec = recommend(hw, _models(4.68))
    assert rec.n_gpu_layers == 0
    assert rec.n_ctx >= 2048
