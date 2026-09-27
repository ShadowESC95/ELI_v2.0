"""The GUI printed a conservative layer split ('HW Profile (recommended): ... gpu_layers=8') and,
separately, a footnote saying MoE expert offload would push it to 52 — two numbers for the same
thing with no visible connection, and the pinned/canonical value saved from the recommendation
stayed at the stale, lower one. `recommend()` now applies the MoE bump itself, so the number this
panel shows (and pins) is the one that actually loads.
"""
from eli.core import hardware_profile, moe_offload
from eli.core.hardware_profile import HardwareProfile, recommend


def _gpu_hw() -> HardwareProfile:
    return HardwareProfile(
        cpu_threads=12, ram_gb=32.0, available_ram_gb=27.0,
        has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER", gpu_vendor="nvidia",
        gpu_integrated=False, free_vram_mb=6800, total_vram_mb=8192, vram_gb=8.0,
    )


def _moe_model(size_gb: float = 19.71):
    return [{"name": "moe-model.gguf", "path": "/tmp/moe-model.gguf",
             "size_gb": size_gb, "size_bytes": int(size_gb * 1e9)}]


def test_the_recommended_layer_count_is_the_post_moe_one(monkeypatch):
    monkeypatch.setattr(hardware_profile, "layers_for_model", lambda *a, **k: 40)
    monkeypatch.setattr(moe_offload, "plan",
                         lambda *a, **k: {"resident_gb": 2.0, "experts_gb": 17.7, "layers": 40})
    rec = recommend(_gpu_hw(), _moe_model())
    assert rec.n_gpu_layers == 40
    assert any("expert offload puts all 40" in line and "this is what actually loads" in line.lower()
               for line in rec.reasoning)


def test_a_dense_model_with_no_plan_is_left_alone(monkeypatch):
    monkeypatch.setattr(moe_offload, "plan", lambda *a, **k: None)
    rec = recommend(_gpu_hw(), _moe_model())
    assert not any("mixture-of-experts" in line.lower() for line in rec.reasoning)
