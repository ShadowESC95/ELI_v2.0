"""_eli_v14_gpu_line() feeds grounded evidence text about the
machine's own GPU -- and used to say "unavailable" unconditionally on every
AMD/Intel/Apple machine, and on any NVIDIA machine with a driver hiccup
(NVML version mismatch), even though hardware_profile.detect_hardware()
(used everywhere else) already knows the real card. Since this evidence gate
is what stops the LLM from confabulating an answer, starving it of real
info it could have had meant a genuinely honest "I don't know" on hardware
that was perfectly identifiable -- not a lie, but not the best available
truth either.
"""
import eli.runtime.deterministic_grounding_gate as g


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_name": "", "total_vram_mb": 0, "gpu_detection_uncertain": False}
    base.update(kw)
    return type("HW", (), base)()


def test_eli_v14_gpu_line_falls_back_when_nvidia_smi_fails(monkeypatch):
    import subprocess as sp

    def _raise(*a, **k):
        raise sp.CalledProcessError(18, ["nvidia-smi"])
    monkeypatch.setattr(g._eli_v14_subprocess, "check_output", _raise)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_name="AMD Radeon RX 7900 XTX", total_vram_mb=24576),
    )
    line = g._eli_v14_gpu_line()
    assert "AMD Radeon RX 7900 XTX" in line
    assert "24576" in line


def test_eli_v14_gpu_line_genuinely_no_gpu_still_says_unavailable(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(g._eli_v14_subprocess, "check_output", _raise)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    assert g._eli_v14_gpu_line() == "unavailable"
