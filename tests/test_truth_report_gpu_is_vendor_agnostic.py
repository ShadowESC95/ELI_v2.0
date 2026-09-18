"""runtime_truth_report()'s "gpu" field came only from _nvidia_info(), which
returned {"available": False} on every AMD/Intel/Apple/Qualcomm machine the
moment nvidia-smi wasn't found or failed -- the same class of bug fixed in
self_status.py and executor_enhanced.py's GPU_STATUS. Covers the fix: a
non-NVIDIA machine (or NVIDIA with a broken driver) falls back to
detect_hardware()'s cross-vendor identity instead of just claiming
unavailable.
"""
import subprocess

import eli.runtime.truth_report as tr


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_vendor": "", "gpu_name": "", "total_vram_mb": 0,
            "gpu_detection_uncertain": False}
    base.update(kw)
    return type("HW", (), base)()


def test_nvidia_path_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        tr.subprocess, "check_output",
        lambda *a, **k: "NVIDIA GeForce RTX 2060 SUPER, 8192, 6963, 595.91\n",
    )
    info = tr._nvidia_info()
    assert info["available"] is True
    assert info["name"] == "NVIDIA GeForce RTX 2060 SUPER"


def test_amd_machine_no_longer_reports_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("no such file: nvidia-smi")
    monkeypatch.setattr(tr.subprocess, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_vendor="amd", gpu_name="AMD Radeon RX 7900 XTX",
                          total_vram_mb=24576),
    )
    info = tr._nvidia_info()
    assert info["available"] is True
    assert info["name"] == "AMD Radeon RX 7900 XTX"
    assert info["vendor"] == "amd"
    assert "nvidia_smi_error" in info


def test_broken_nvidia_driver_falls_back_to_identity(monkeypatch):
    """nvidia-smi exists but exits non-zero (NVML mismatch) -- subprocess.check_output
    raises CalledProcessError; must not just say unavailable when
    detect_hardware() still knows the real card."""
    def _raise(*a, **k):
        raise subprocess.CalledProcessError(18, ["nvidia-smi"])
    monkeypatch.setattr(tr.subprocess, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_vendor="nvidia", gpu_name="NVIDIA GeForce RTX 2060 SUPER",
                          total_vram_mb=8192, gpu_detection_uncertain=True),
    )
    info = tr._nvidia_info()
    assert info["available"] is True
    assert info["name"] == "NVIDIA GeForce RTX 2060 SUPER"
    assert info["estimated"] is True


def test_genuinely_no_gpu_still_reports_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("no such file: nvidia-smi")
    monkeypatch.setattr(tr.subprocess, "check_output", _raise)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    info = tr._nvidia_info()
    assert info["available"] is False
