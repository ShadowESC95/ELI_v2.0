"""_gpu_probe_from_nvidia_smi() used to return {} (no GPU info at all) on
every AMD/Intel/Apple machine, and on any NVIDIA machine with a driver
hiccup (NVML version mismatch), even though hardware_profile.detect_hardware()
(used everywhere else) already knows the real card.
"""
import eli.contracts.runtime_status as rs


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_name": "", "total_vram_mb": 0, "free_vram_mb": 0,
            "gpu_detection_uncertain": False}
    base.update(kw)
    return type("HW", (), base)()


def test_falls_back_when_nvidia_smi_fails(monkeypatch):
    import subprocess as sp

    def _raise(*a, **k):
        raise sp.CalledProcessError(18, ["nvidia-smi"])
    monkeypatch.setattr(sp, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER",
                          total_vram_mb=8192, free_vram_mb=6963, gpu_detection_uncertain=True),
    )
    probe = rs._gpu_probe_from_nvidia_smi()
    assert "NVIDIA GeForce RTX 2060 SUPER" in probe["name"]
    assert probe["total_mib"] == 8192


def test_amd_machine_gets_real_identity_not_empty_dict(monkeypatch):
    import subprocess as sp

    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(sp, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="AMD Radeon RX 7900 XTX",
                          total_vram_mb=24576, free_vram_mb=22000),
    )
    probe = rs._gpu_probe_from_nvidia_smi()
    assert probe["name"] == "AMD Radeon RX 7900 XTX"
    assert probe["total_mib"] == 24576


def test_genuinely_no_gpu_still_returns_empty(monkeypatch):
    import subprocess as sp

    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(sp, "check_output", _raise)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    assert rs._gpu_probe_from_nvidia_smi() == {}
