"""CPU/iGPU hosts without an active GPU backend must size from RAM, not shared VRAM."""
from __future__ import annotations

import pytest

from eli.core.hardware_profile import (
    HardwareProfile,
    effective_use_gpu_layers,
    recommend,
)


def _igpu_hw(*, ram_gb: float = 7.0, avail_gb: float = 4.7) -> HardwareProfile:
    return HardwareProfile(
        cpu_threads=8,
        ram_gb=ram_gb,
        available_ram_gb=avail_gb,
        has_gpu=True,
        gpu_name="Intel Iris Xe",
        gpu_vendor="intel",
        gpu_integrated=True,
        free_vram_mb=1462,
        total_vram_mb=2048,
        vram_gb=1462 / 1024.0,
    )


def _models(size_gb: float = 1.8):
    return [{
        "name": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "path": "/tmp/qwen3b.gguf",
        "size_gb": size_gb,
        "size_bytes": int(size_gb * 1e9),
    }]


def test_effective_use_gpu_layers_false_without_backend(monkeypatch):
    monkeypatch.setattr(
        "eli.core.hardware_profile._llama_gpu_offload_available",
        lambda: False,
    )
    assert effective_use_gpu_layers(_igpu_hw()) is False


def test_recommend_cpu_path_matches_ram_not_igpu_vram(monkeypatch):
    """Field test jess@blue: tuner must not report gpu_layers=2 ctx=3996 when CPU-only."""
    monkeypatch.setattr(
        "eli.core.hardware_profile._llama_gpu_offload_available",
        lambda: False,
    )
    rec = recommend(_igpu_hw(), _models())
    assert rec.n_gpu_layers == 0
    assert rec.n_ctx >= 4096
    assert rec.batch_size >= 32
    assert any("CPU/RAM" in r or "CPU inference" in r for r in rec.reasoning)


def test_recommend_cpu_threads_cpu_bound_leaves_one():
    from eli.core.hardware_profile import recommend_cpu_threads
    assert recommend_cpu_threads(8, cpu_bound=True) == 7
    assert recommend_cpu_threads(8, cpu_bound=False) == 6
    assert recommend_cpu_threads(4, cpu_bound=False) == 3


def test_recommend_threads_and_kv_on_iris_class(monkeypatch):
    monkeypatch.setattr(
        "eli.core.hardware_profile._llama_gpu_offload_available",
        lambda: False,
    )
    rec = recommend(_igpu_hw(ram_gb=8.0, avail_gb=4.7), _models())
    assert rec.n_threads == 7  # 8 cores, CPU-bound → leave 1
    assert rec.cache_type_k == "q4_0"
    assert rec.use_mmap is True
    assert rec.use_mlock is False


def test_compute_mode_cpu_forces_zero_layers(monkeypatch):
    monkeypatch.setattr(
        "eli.core.hardware_profile._llama_gpu_offload_available",
        lambda: True,
    )
    hw = _igpu_hw()
    hw.free_vram_mb = 6000
    hw.total_vram_mb = 8192
    monkeypatch.setenv("ELI_FORCE_GPU_LAYERS", "0")
    assert effective_use_gpu_layers(hw) is False
    rec = recommend(hw, _models())
    assert rec.n_gpu_layers == 0
