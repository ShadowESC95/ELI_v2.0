"""get_live_gpu_telemetry() is the ONE place every caller should ask "what is
my GPU doing right now" instead of each maintaining its own nvidia-smi
wrapper. Confirmed in the field: at least eight separate call sites
independently shelled out to nvidia-smi, each with its own (each slightly
different, each separately buggy) handling of a broken/absent driver.
"""
import eli.core.hardware_profile as hwp


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_name": "", "gpu_vendor": "", "total_vram_mb": 0,
            "free_vram_mb": 0, "gpu_detection_uncertain": False}
    base.update(kw)
    return type("HW", (), base)()


def test_no_gpu_returns_honest_empty_result(monkeypatch):
    monkeypatch.setattr(hwp, "detect_hardware", lambda: _fake_hw())
    out = hwp.get_live_gpu_telemetry()
    assert out["ok"] is False
    assert out["total_mb"] is None


def test_nvidia_live_query_populates_full_telemetry(monkeypatch):
    monkeypatch.setattr(
        hwp, "detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER",
                          gpu_vendor="nvidia", total_vram_mb=8192, free_vram_mb=6963),
    )
    monkeypatch.setattr(hwp.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)

    class _Proc:
        returncode = 0
        stdout = "NVIDIA GeForce RTX 2060 SUPER, 8192, 1200, 6963, 12, 44, 24.5, 215.0, 595.91\n"
        stderr = ""
    monkeypatch.setattr(hwp.subprocess, "run", lambda *a, **k: _Proc())

    out = hwp.get_live_gpu_telemetry()
    assert out["ok"] is True
    assert out["vendor"] == "nvidia"
    assert out["util_pct"] == 12
    assert out["temp_c"] == 44
    assert out["used_mb"] == 1200
    assert out["driver"] == "595.91"
    assert out["live_probe_failed"] is False
    assert out["estimated"] is False


def test_broken_nvidia_driver_falls_back_to_estimate_and_flags_it(monkeypatch):
    """The field case: NVML "Driver/library version mismatch"."""
    monkeypatch.setattr(
        hwp, "detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER",
                          gpu_vendor="nvidia", total_vram_mb=8192, free_vram_mb=6963,
                          gpu_detection_uncertain=True),
    )
    monkeypatch.setattr(hwp.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)

    class _Proc:
        returncode = 18
        stdout = "Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 595.91\n"
        stderr = ""
    monkeypatch.setattr(hwp.subprocess, "run", lambda *a, **k: _Proc())

    out = hwp.get_live_gpu_telemetry()
    assert out["ok"] is True
    assert out["name"] == "NVIDIA GeForce RTX 2060 SUPER"
    assert out["total_mb"] == 8192
    assert out["live_probe_failed"] is True
    assert out["estimated"] is True
    assert out["util_pct"] is None
    assert out["temp_c"] is None


def test_amd_gets_live_vram_but_no_fabricated_utilization(monkeypatch):
    monkeypatch.setattr(
        hwp, "detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="AMD Radeon RX 7900 XTX",
                          gpu_vendor="amd", total_vram_mb=24576, free_vram_mb=22000),
    )
    monkeypatch.setattr(hwp.shutil, "which", lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None)

    class _Proc:
        returncode = 0
        stdout = ('{"card0": {"VRAM Total Memory (B)": "' + str(24 * 1024**3) +
                   '", "VRAM Total Used Memory (B)": "' + str(4 * 1024**3) + '"}}')
        stderr = ""
    monkeypatch.setattr(hwp.subprocess, "run", lambda *a, **k: _Proc())

    out = hwp.get_live_gpu_telemetry()
    assert out["ok"] is True
    assert out["vendor"] == "amd"
    assert out["total_mb"] == 24576
    assert out["used_mb"] == 4096
    assert out["free_mb"] == 20480
    assert out["util_pct"] is None
    assert out["temp_c"] is None


def test_amd_without_rocm_smi_still_reports_identity_from_detect_hardware(monkeypatch):
    monkeypatch.setattr(
        hwp, "detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="AMD Radeon RX 7900 XTX",
                          gpu_vendor="amd", total_vram_mb=24576, free_vram_mb=22000),
    )
    monkeypatch.setattr(hwp.shutil, "which", lambda name: None)
    out = hwp.get_live_gpu_telemetry()
    assert out["ok"] is True
    assert out["name"] == "AMD Radeon RX 7900 XTX"
    assert out["total_mb"] == 24576


def test_intel_igpu_has_no_live_tool_but_reports_identity(monkeypatch):
    monkeypatch.setattr(
        hwp, "detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="Intel Iris Xe Graphics",
                          gpu_vendor="intel", total_vram_mb=4096, free_vram_mb=3800),
    )
    out = hwp.get_live_gpu_telemetry()
    assert out["ok"] is True
    assert out["name"] == "Intel Iris Xe Graphics"
    assert out["util_pct"] is None
