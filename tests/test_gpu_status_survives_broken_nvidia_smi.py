"""Reported: ELI couldn't answer "what is my GPU?" or "what are your settings"
-- not because it lied, but because a single live nvidia-smi failure (NVML
"Driver/library version mismatch") made _gpu_status_report() bail out with
just the raw error text, before it ever reached the runtime_snapshot section
(context/gpu_layers/batch/threads) that has nothing to do with nvidia-smi at
all. So a question about LOADED SETTINGS got "not specified in the evidence"
for a reason entirely unrelated to the question asked.

hardware_profile.detect_hardware() already has kernel-level fallbacks for
exactly this nvidia-smi failure (see test_gpu_vram_estimates_scale_with_real_hardware.py)
-- this file covers _gpu_status_report() actually using them instead of
independently re-implementing (and failing at) its own nvidia-smi call.
"""
import json

import eli.execution.executor_enhanced as ex

SNAPSHOT = {
    "provider": "gguf", "model_name": "Qwen_Qwen3-8B-Q4_K_M.gguf",
    "n_ctx": 12000, "n_gpu_layers": 32, "n_threads": 10, "n_batch": 128,
}


class _BrokenProc:
    returncode = 18
    stdout = ("Failed to initialize NVML: Driver/library version mismatch\n"
               "NVML library version: 595.91\n")
    stderr = ""


def _setup(monkeypatch, tmp_path, *, snapshot=None):
    if snapshot is not None:
        (tmp_path / "runtime_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

    class _Paths:
        artifacts_dir = tmp_path
    monkeypatch.setattr(ex, "get_paths", lambda: _Paths())
    monkeypatch.setattr(ex.subprocess, "run", lambda *a, **k: _BrokenProc())


def test_loaded_settings_still_reported_when_nvidia_smi_is_broken(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT)
    rep = ex._gpu_status_report()
    assert "context: 12000" in rep["content"]
    assert "GPU-layer parameter: 32" in rep["content"]
    assert "batch: 128" in rep["content"]
    assert "CPU threads: 10" in rep["content"]


def test_ok_is_true_when_there_is_genuinely_grounded_content(monkeypatch, tmp_path):
    """A live-probe failure is not the same as having nothing to say -- ok
    must reflect whether the report is USABLE, not whether nvidia-smi ran."""
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT)
    rep = ex._gpu_status_report()
    assert rep["ok"] is True


def test_gpu_name_falls_back_to_hardware_profile_not_raw_error_text(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: type("HW", (), {
            "has_gpu": True, "gpu_name": "NVIDIA GeForce RTX 2060 SUPER",
            "gpu_vendor": "nvidia",
            "total_vram_mb": 8192, "gpu_detection_uncertain": True,
        })(),
    )
    rep = ex._gpu_status_report()
    assert "NVIDIA GeForce RTX 2060 SUPER" in rep["content"]
    assert "8192" in rep["content"]
    # The raw NVML text is still surfaced as the reason, but must not be the
    # ONLY thing said about the GPU.
    assert "Driver/library version mismatch" in rep["content"]


def test_no_snapshot_and_no_gpu_is_still_honest_not_silent(monkeypatch, tmp_path):
    """Genuinely nothing known: ok=False is correct here, but content must
    still say so plainly rather than an empty/unhelpful string."""
    _setup(monkeypatch, tmp_path, snapshot=None)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: type("HW", (), {"has_gpu": False, "gpu_vendor": ""})(),
    )
    rep = ex._gpu_status_report()
    assert rep["ok"] is False
    assert "No GPU detected" in rep["content"]


# ── ELI ships to AMD/Intel/Apple/Qualcomm machines, not only NVIDIA ones ───
# _gpu_status_report() used to call nvidia-smi unconditionally regardless of
# the real vendor, so a non-NVIDIA user got an nvidia-specific error message
# implying they should have had nvidia-smi in the first place.

def test_intel_igpu_never_touches_nvidia_smi(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: type("HW", (), {
            "has_gpu": True, "gpu_name": "Intel Iris Xe Graphics",
            "gpu_vendor": "intel", "total_vram_mb": 4096,
            "gpu_detection_uncertain": False,
        })(),
    )
    called = {"n": 0}
    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("nvidia-smi must not be invoked for a non-NVIDIA vendor")
    monkeypatch.setattr(ex.subprocess, "run", _boom)
    rep = ex._gpu_status_report()
    assert called["n"] == 0
    assert "Intel Iris Xe Graphics" in rep["content"]
    assert "nvidia" not in rep["content"].lower()
    assert "context: 12000" in rep["content"]


def test_amd_gets_a_live_vram_reading_via_rocm_smi(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: type("HW", (), {
            "has_gpu": True, "gpu_name": "AMD Radeon RX 7900 XTX",
            "gpu_vendor": "amd", "total_vram_mb": 24576,
            "gpu_detection_uncertain": False,
        })(),
    )
    monkeypatch.setattr(ex.shutil, "which", lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None)

    class _RocmProc:
        returncode = 0
        stdout = json.dumps({
            "card0": {
                "VRAM Total Memory (B)": str(24 * 1024**3),
                "VRAM Total Used Memory (B)": str(4 * 1024**3),
            }
        })
        stderr = ""

    monkeypatch.setattr(ex.subprocess, "run", lambda *a, **k: _RocmProc())
    rep = ex._gpu_status_report()
    assert rep["ok"] is True
    assert "AMD Radeon RX 7900 XTX" in rep["content"]
    assert "used" in rep["content"].lower()
    assert "not queried on AMD" in rep["content"]
    assert "context: 12000" in rep["content"]


def test_amd_without_rocm_smi_still_reports_identity(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: type("HW", (), {
            "has_gpu": True, "gpu_name": "AMD Radeon RX 7900 XTX",
            "gpu_vendor": "amd", "total_vram_mb": 24576,
            "gpu_detection_uncertain": False,
        })(),
    )
    monkeypatch.setattr(ex.shutil, "which", lambda name: None)
    rep = ex._gpu_status_report()
    assert "AMD Radeon RX 7900 XTX" in rep["content"]
    assert "24576" in rep["content"]
