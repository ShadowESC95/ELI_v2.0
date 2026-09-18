"""self_status.py's own docstring claims "model/hardware-agnostic", but
_gpu() only ever called nvidia-smi and returned None on every AMD/Intel/
Apple/Qualcomm machine -- so the persona's real self-status (used so it
never has to invent a GPU temperature) silently had nothing to say about a
GPU that was genuinely there, on the majority of non-NVIDIA hardware ELI
ships to. Covers the fix: AMD gets a live rocm-smi VRAM reading, any other
vendor with no live telemetry tool falls back to detect_hardware()'s own
identity, and render_self_status_block() degrades each missing field
(temperature/utilization/used-VRAM) individually instead of assuming every
number is always present.
"""
import json

import eli.runtime.self_status as ss


def _fake_hw(**kw):
    base = {"has_gpu": False, "gpu_vendor": "", "gpu_name": "", "total_vram_mb": 0,
            "gpu_detection_uncertain": False}
    base.update(kw)
    return type("HW", (), base)()


def test_nvidia_path_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        ss, "_run",
        lambda cmd, timeout=2.0: (
            "NVIDIA GeForce RTX 2060 SUPER, 44, 11, 7493, 8192"
            if cmd[0] == "nvidia-smi" else ""
        ),
    )
    g = ss._gpu()
    assert g["name"] == "NVIDIA GeForce RTX 2060 SUPER"
    assert g["temp_c"] == 44
    assert g["vram_total_mb"] == 8192


def test_amd_gets_a_live_vram_reading_when_nvidia_smi_has_nothing(monkeypatch):
    monkeypatch.setattr(ss, "_run", lambda cmd, timeout=2.0: (
        json.dumps({"card0": {
            "VRAM Total Memory (B)": str(24 * 1024**3),
            "VRAM Total Used Memory (B)": str(4 * 1024**3),
        }}) if cmd[0] == "rocm-smi" else ""
    ))
    import shutil as _shutil
    monkeypatch.setattr(ss, "shutil", _shutil, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None)
    g = ss._gpu()
    assert g is not None
    assert g["name"] == "AMD GPU"
    assert g["vram_total_mb"] == 24576
    assert g["vram_used_mb"] == 4096
    assert g["temp_c"] is None


def test_intel_igpu_falls_back_to_hardware_profile_identity(monkeypatch):
    monkeypatch.setattr(ss, "_run", lambda cmd, timeout=2.0: "")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(
        "eli.core.hardware_profile.detect_hardware",
        lambda: _fake_hw(has_gpu=True, gpu_vendor="intel", gpu_name="Intel Iris Xe Graphics",
                          total_vram_mb=4096),
    )
    g = ss._gpu()
    assert g is not None
    assert "Intel Iris Xe Graphics" in g["name"]
    assert g["vram_total_mb"] == 4096
    assert g["temp_c"] is None
    assert g["util_pct"] is None


def test_genuinely_no_gpu_returns_none(monkeypatch):
    monkeypatch.setattr(ss, "_run", lambda cmd, timeout=2.0: "")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("eli.core.hardware_profile.detect_hardware", lambda: _fake_hw())
    assert ss._gpu() is None


def test_render_degrades_missing_fields_instead_of_crashing():
    """Old code did g['temp_c'] unconditionally -- a name-only/VRAM-only dict
    (AMD, or any identity-fallback vendor) would have raised KeyError."""
    st = {
        "uptime": "1h", "gpu": {
            "name": "Intel Iris Xe Graphics (estimated)",
            "temp_c": None, "util_pct": None, "vram_used_mb": None, "vram_total_mb": 4096,
        },
    }
    import eli.runtime.self_status as _ss
    original = _ss.get_self_status
    _ss.get_self_status = lambda: st
    try:
        out = _ss.render_self_status_block()
    finally:
        _ss.get_self_status = original
    assert "Intel Iris Xe Graphics" in out
    assert "4096 MB VRAM total" in out
    assert "None" not in out
