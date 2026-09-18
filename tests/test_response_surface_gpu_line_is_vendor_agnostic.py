"""user_visible_response_surface._gpu_line() feeds text the user actually
sees, and used to say "unavailable" on every AMD/Intel/Apple machine, and on
any NVIDIA machine with a driver hiccup (NVML version mismatch), even though
hardware_profile.detect_hardware() (used everywhere else) already knows the
real card.
"""
import eli.runtime.user_visible_response_surface as u


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_name": "", "total_vram_mb": 0, "gpu_detection_uncertain": False}
    base.update(kw)
    return type("HW", (), base)()


def test_falls_back_when_nvidia_smi_fails(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("nvidia-smi: driver/library version mismatch")
    monkeypatch.setattr(u.subprocess, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER",
                          total_vram_mb=8192, gpu_detection_uncertain=True),
    )
    line = u._gpu_line()
    assert "NVIDIA GeForce RTX 2060 SUPER" in line
    assert "8192" in line


def test_amd_machine_gets_real_identity_not_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(u.subprocess, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="AMD Radeon RX 7900 XTX", total_vram_mb=24576),
    )
    assert "AMD Radeon RX 7900 XTX" in u._gpu_line()


def test_genuinely_no_gpu_still_says_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(u.subprocess, "check_output", _raise)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    assert u._gpu_line() == "unavailable"
