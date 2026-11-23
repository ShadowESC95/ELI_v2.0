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
    # a real file says how long a context it was trained for (32k for this 3B)
    monkeypatch.setattr("eli.core.startup_hardware_optimizer._gguf_metadata_ctx", lambda p: 32768)
    rec = recommend(_igpu_hw(), _models())
    assert rec.n_gpu_layers == 0
    assert rec.n_ctx >= 4096
    assert rec.batch_size >= 32
    assert any("CPU/RAM" in r or "CPU inference" in r for r in rec.reasoning)


def test_recommend_cpu_threads_is_the_physical_cores():
    """llama.cpp is fastest at one thread per physical core (i7-8700: 4.37 tok/s at 6 threads, 3.99 at
    12); without hyper-threads one core is left for the desktop."""
    from eli.core.hardware_profile import recommend_cpu_threads
    assert recommend_cpu_threads(12, physical=6) == 6
    assert recommend_cpu_threads(8, physical=8) == 7
    assert recommend_cpu_threads(4, physical=4) == 3
    assert recommend_cpu_threads(1, physical=1) == 1


def test_recommend_threads_and_kv_on_iris_class(monkeypatch):
    monkeypatch.setattr(
        "eli.core.hardware_profile._llama_gpu_offload_available",
        lambda: False,
    )
    # a model trained on 32k: 4.7 GB available cannot hold that at fp16, so the cache is quantized
    monkeypatch.setattr("eli.core.startup_hardware_optimizer._gguf_metadata_ctx", lambda p: 32768)
    rec = recommend(_igpu_hw(ram_gb=8.0, avail_gb=4.7), _models())
    assert rec.n_threads == 7  # 8 cores, CPU-bound → leave 1
    assert rec.cache_type_k == "q8_0"      # the quantized cache that answers the same as fp16
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


@pytest.mark.parametrize("integrated,free_vram_mb,avail_gb", [
    (True, 3800, 4.5),          # a laptop's integrated GPU, taking its share of the same RAM
    (False, 7400, 6.0),         # an 8 GB card in a machine with little RAM free
])
def test_the_model_chosen_from_several_fits_what_the_gpu_leaves_in_ram(gpu_offload_runtime, integrated,
                                                                       free_vram_mb, avail_gb):
    """With several models on disk the largest one any layer of which fit on the GPU was chosen,
    whatever it left in RAM: an 18 GB model on an 8 GB laptop with an integrated GPU. The first run
    writes that choice as the model to load."""
    hw = _igpu_hw(ram_gb=7.6 if integrated else 15.5, avail_gb=avail_gb)
    hw.gpu_integrated = integrated
    hw.free_vram_mb = hw.total_vram_mb = free_vram_mb
    if not integrated:
        hw.gpu_name, hw.gpu_vendor = "NVIDIA GeForce RTX 3070", "nvidia"
    big = {"name": "big.gguf", "path": "/m/big.gguf", "size_gb": 18.0, "size_bytes": int(18.0 * 1024 ** 3)}
    small = {"name": "small.gguf", "path": "/m/small.gguf", "size_gb": 0.7, "size_bytes": int(0.7 * 1024 ** 3)}
    # a context short enough that the large model's cache leaves room for some of its layers on the GPU
    rec = recommend(hw, [big, small], user_ctx=4096)
    assert rec.model_path == small["path"], rec.reasoning
    roomy = _igpu_hw(ram_gb=64.0, avail_gb=56.0)       # with the RAM for what is left over it is chosen
    roomy.gpu_integrated = integrated
    roomy.free_vram_mb = roomy.total_vram_mb = free_vram_mb
    assert recommend(roomy, [big, small], user_ctx=4096).model_path == big["path"]
