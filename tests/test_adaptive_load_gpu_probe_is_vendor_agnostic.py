"""_eli_probe_gpu_vram() (the adaptive cold-load fallback's own GPU probe,
formerly _eli_probe_nvidia_vram) used to return an all-zero "probe failed"
result the moment nvidia-smi wasn't found or failed -- on every AMD/Intel/
Apple machine, and on any NVIDIA machine with a driver hiccup (NVML version
mismatch). A zero VRAM basis skips the VRAM-aware intermediate rungs of the
adaptive load retry ladder (_eli_build_adaptive_candidates), jumping straight
toward the CPU-only end of it regardless of how much VRAM the machine
actually had. Covers the fix: falls back to hardware_profile.detect_hardware(),
the same cross-vendor detection used everywhere else.
"""
import eli.cognition.gguf_inference as G


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_name": "", "total_vram_mb": 0, "free_vram_mb": 0}
    base.update(kw)
    return type("HW", (), base)()


def test_broken_nvidia_driver_falls_back_to_real_vram(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("nvidia-smi: Failed to initialize NVML: Driver/library version mismatch")
    monkeypatch.setattr(G._eli_adapt_subprocess, "run", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER",
                          total_vram_mb=8192, free_vram_mb=6963),
    )
    r = G._eli_probe_gpu_vram()
    assert r["ok"] is True
    assert r["total_mib"] == 8192
    assert r["free_mib"] == 6963


def test_amd_machine_gets_a_real_vram_basis_not_zero(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(G._eli_adapt_subprocess, "run", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="AMD Radeon RX 7900 XTX",
                          total_vram_mb=24576, free_vram_mb=22000),
    )
    r = G._eli_probe_gpu_vram()
    assert r["ok"] is True
    assert r["name"] == "AMD Radeon RX 7900 XTX"
    assert r["total_mib"] == 24576


def test_genuinely_no_gpu_still_reports_failed(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(G._eli_adapt_subprocess, "run", _raise)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    r = G._eli_probe_gpu_vram()
    assert r["ok"] is False
    assert r["total_mib"] == 0
