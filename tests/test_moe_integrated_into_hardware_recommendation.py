"""The GUI printed a conservative layer split ('HW Profile (recommended): ... gpu_layers=8') and,
separately, a footnote saying MoE expert offload would push it to 52 — two numbers for the same
thing with no visible connection, and the pinned/canonical value saved from the recommendation
stayed at the stale, lower one. `recommend()` now applies the MoE bump itself, so the number this
panel shows (and pins) is the one that actually loads.

Previously that bump was an unconditional assertion ("MoE always means every layer"), with no
check that the real GPU-resident ("core") weight footprint actually fits free VRAM. It now runs
the real fit (`unified_fit_config(..., moe_resident_gb=...)`) — generous VRAM still lands on all
layers (below), but a VRAM-starved machine gets a genuine partial count instead of an unverified
full-layer gamble.
"""
from eli.core import hardware_profile, moe_offload
from eli.core.hardware_profile import HardwareProfile, recommend


def _gpu_hw(free_vram_mb: int = 6800) -> HardwareProfile:
    return HardwareProfile(
        cpu_threads=12, ram_gb=32.0, available_ram_gb=27.0,
        has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER", gpu_vendor="nvidia",
        gpu_integrated=False, free_vram_mb=free_vram_mb, total_vram_mb=8192, vram_gb=8.0,
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
    assert any(
        "40/40 layers' core weights fit" in line and "this is what actually loads" in line.lower()
        for line in rec.reasoning
    ), rec.reasoning


def test_a_vram_starved_machine_gets_a_real_partial_fit(monkeypatch):
    """2GB of core weights does not fit in ~800MB of budget — the recommendation must say
    so honestly (a genuine partial count) instead of forcing all 40 layers regardless."""
    monkeypatch.setattr(hardware_profile, "layers_for_model", lambda *a, **k: 40)
    monkeypatch.setattr(moe_offload, "plan",
                         lambda *a, **k: {"resident_gb": 2.0, "experts_gb": 17.7, "layers": 40})
    rec = recommend(_gpu_hw(free_vram_mb=2500), _moe_model())
    assert 0 < rec.n_gpu_layers < 40, rec.n_gpu_layers
    assert any(
        f"{rec.n_gpu_layers}/40 layers' core weights fit" in line
        for line in rec.reasoning
    ), rec.reasoning


def test_a_dense_model_with_no_plan_is_left_alone(monkeypatch):
    monkeypatch.setattr(moe_offload, "plan", lambda *a, **k: None)
    rec = recommend(_gpu_hw(), _moe_model())
    assert not any("mixture-of-experts" in line.lower() for line in rec.reasoning)


def test_gpu_present_but_backend_inactive_does_not_crash_or_suggest_gpu_layers(monkeypatch):
    """GPU hardware detected with free VRAM, but the llama.cpp backend isn't active
    (`_llama_gpu_offload_available()` False) — the dense-fit path already routes this to
    CPU-only (use_gpu_layers=False). The MoE re-fit must not run in this case: it has no
    `use_gpu_layers`-gated `_pre_fit_ctx` to read from (that capture only matters once this
    is gated correctly), and suggesting GPU layers here would recommend a config the real
    loader can never actually use."""
    monkeypatch.setattr(hardware_profile, "layers_for_model", lambda *a, **k: 40)
    monkeypatch.setattr(hardware_profile, "_llama_gpu_offload_available", lambda: False)
    plan_calls = []
    monkeypatch.setattr(
        moe_offload, "plan",
        lambda *a, **k: plan_calls.append(k) or {"resident_gb": 2.0, "experts_gb": 17.7, "layers": 40},
    )
    rec = recommend(_gpu_hw(), _moe_model())  # must not raise
    assert rec.n_gpu_layers == 0
    assert not plan_calls, "moe_offload.plan() must not even be called when the backend is inactive"
