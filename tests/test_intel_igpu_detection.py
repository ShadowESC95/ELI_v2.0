"""Integrated / unified-memory GPUs must not be reported as 'no GPU'."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from eli.core import hardware_profile as hp

requires_linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux sysfs PCI probes")


def test_intel_integrated_profile_fields():
    hw = hp.HardwareProfile(ram_gb=16.0, available_ram_gb=10.0)
    hp._apply_intel_integrated_profile(hw, "Intel Iris Xe Graphics")
    assert hw.has_gpu is True
    assert hw.gpu_vendor == "intel"
    assert hw.gpu_integrated is True
    assert hw.gpu_name == "Intel Iris Xe Graphics"
    assert hw.free_vram_mb > 0
    assert hw.total_vram_mb >= hw.free_vram_mb


def test_amd_apu_integrated_profile_fields():
    hw = hp.HardwareProfile(ram_gb=32.0, available_ram_gb=20.0)
    hp._apply_integrated_gpu_profile(hw, "AMD Radeon Graphics", "amd")
    assert hw.has_gpu is True
    assert hw.gpu_vendor == "amd"
    assert hw.gpu_integrated is True
    assert hw.free_vram_mb > 0


def test_apple_unified_memory_label():
    assert "Apple" in hp.integrated_gpu_label("Apple M2", "apple")
    assert hp.format_gpu_layers_status(
        0, fitted_layers=12, gpu_integrated=True, gpu_name="Apple M2", gpu_vendor="apple",
    ).endswith("CPU only)")


def test_integrated_name_heuristics():
    assert hp._is_integrated_gpu_name("Intel Iris Xe Graphics", "intel") is True
    assert hp._is_integrated_gpu_name("AMD Radeon Graphics", "amd") is True
    assert hp._is_discrete_gpu_name("NVIDIA GeForce RTX 2060 SUPER") is True
    assert hp._is_integrated_gpu_name("NVIDIA GeForce RTX 2060 SUPER") is False


@requires_linux
def test_discrete_arc_device_ids_are_not_treated_as_igpu(tmp_path):
    dev = tmp_path / "pci0000_03_00_0"
    dev.mkdir()
    (dev / "vendor").write_text("0x8086", encoding="utf-8")
    (dev / "device").write_text("0x56a0", encoding="utf-8")  # Arc A770 family
    assert hp._intel_pci_device_is_discrete_arc(dev) is True


@requires_linux
def test_integrated_intel_device_is_not_arc(tmp_path):
    dev = tmp_path / "pci0000_00_02_0"
    dev.mkdir()
    (dev / "vendor").write_text("0x8086", encoding="utf-8")
    (dev / "device").write_text("0x9a49", encoding="utf-8")  # typical Iris Xe
    assert hp._intel_pci_device_is_discrete_arc(dev) is False


@requires_linux
def test_detect_hardware_falls_back_to_intel_igpu(monkeypatch):
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: None)
    monkeypatch.setattr(hp, "_nvidia_driver_loaded", lambda: False)
    monkeypatch.setattr(hp, "_windows_gpus", lambda: [])
    monkeypatch.setattr(hp, "_macos_gpus", lambda: [])
    monkeypatch.setattr(
        hp,
        "_linux_intel_display_adapters",
        lambda: [("Intel Corporation Iris Xe Graphics", False)],
    )

    hp._DETECT_HW_CACHE = None
    hw = hp.detect_hardware(force=True)
    assert hw.has_gpu is True
    assert hw.gpu_integrated is True
    assert "iris" in hw.gpu_name.lower()


def test_install_script_reports_intel_integrated():
    text = Path("install.sh").read_text(encoding="utf-8")
    assert "HAS_INTEL_IGPU" in text
    assert "Intel integrated" in text
    assert "GGML_VULKAN=on" in text
    assert "_gpu_pipeline" in text


def test_qualcomm_integrated_profile_fields():
    hw = hp.HardwareProfile(ram_gb=32.0, available_ram_gb=24.0)
    hp._apply_integrated_gpu_profile(hw, "Qualcomm Adreno X1-85 GPU", "qualcomm")
    assert hw.has_gpu is True
    assert hw.gpu_vendor == "qualcomm"
    assert hw.gpu_integrated is True
    assert hw.free_vram_mb > 0


def test_qualcomm_name_heuristics():
    assert hp._is_integrated_gpu_name("Qualcomm Adreno X1-85 GPU", "qualcomm") is True
    assert "Adreno" in hp.integrated_gpu_label("Qualcomm Adreno X1-85 GPU", "qualcomm")
    assert hp.format_gpu_layers_status(
        0, fitted_layers=8, gpu_integrated=True,
        gpu_name="Qualcomm Adreno X1-85 GPU", gpu_vendor="qualcomm",
    ).endswith("CPU only)")


@requires_linux
def test_detect_hardware_falls_back_to_qualcomm_adreno(monkeypatch):
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: None)
    monkeypatch.setattr(hp, "_nvidia_driver_loaded", lambda: False)
    monkeypatch.setattr(hp, "_windows_gpus", lambda: [])
    monkeypatch.setattr(hp, "_macos_gpus", lambda: [])
    monkeypatch.setattr(hp, "_linux_intel_display_adapters", lambda: [])
    monkeypatch.setattr(
        hp,
        "_linux_qualcomm_display_adapters",
        lambda: ["Qualcomm Adreno X1-85 GPU"],
    )

    hp._DETECT_HW_CACHE = None
    hw = hp.detect_hardware(force=True)
    assert hw.has_gpu is True
    assert hw.gpu_integrated is True
    assert hw.gpu_vendor == "qualcomm"
    assert "adreno" in hw.gpu_name.lower()


def test_install_script_reports_qualcomm_integrated():
    text = Path("install.sh").read_text(encoding="utf-8")
    assert "HAS_QUALCOMM_IGPU" in text
    assert "Qualcomm Adreno" in text


def test_detect_hardware_is_cached(monkeypatch):
    calls = {"n": 0}

    def _fake_impl():
        calls["n"] += 1
        hw = hp.HardwareProfile()
        hp._apply_intel_integrated_profile(hw, "Intel Iris Xe Graphics")
        return hw

    monkeypatch.setattr(hp, "_detect_hardware_impl", _fake_impl)
    hp._DETECT_HW_CACHE = None
    a = hp.detect_hardware()
    b = hp.detect_hardware()
    assert calls["n"] == 1
    assert a.gpu_name == b.gpu_name
    c = hp.detect_hardware(force=True)
    assert calls["n"] == 2
    assert c.gpu_name == a.gpu_name


def test_recommend_igpu_reports_fitted_layers_when_backend_cpu_only(monkeypatch):
    monkeypatch.setattr(hp, "_llama_gpu_offload_available", lambda: False)
    hw = hp.HardwareProfile(
        ram_gb=16.0,
        available_ram_gb=10.0,
        has_gpu=True,
        gpu_integrated=True,
        gpu_vendor="intel",
        gpu_name="Intel Iris Xe Graphics",
        vulkan_available=True,
        free_vram_mb=1465,
        total_vram_mb=1489,
    )
    models = [{
        "name": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "path": "/tmp/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "size_bytes": 2_000_000_000,
        "size_gb": 2.0,
    }]
    rec = hp.recommend(hw, models)
    assert rec.n_gpu_layers > 0, "integrated GPU with ~1.4GB budget must report fitted layers"
    assert "fit" in " ".join(rec.reasoning).lower() or rec.n_gpu_layers > 0


def test_detect_available_ram_gb_positive():
    avail = __import__(
        "eli.core.startup_hardware_optimizer", fromlist=["detect_available_ram_gb"]
    ).detect_available_ram_gb()
    assert avail > 0


def test_cpu_ctx_ceiling_from_ram_scales_with_model():
    from eli.core.startup_hardware_optimizer import cpu_ctx_ceiling_from_ram
    small_model = cpu_ctx_ceiling_from_ram(2.0, train_ctx=32768)
    huge_model = cpu_ctx_ceiling_from_ram(40.0, train_ctx=32768)
    assert small_model >= 2048
    assert small_model >= huge_model  # bigger model footprint → smaller ctx ceiling


def test_runtime_cpu_only_honours_load_mode_and_offload_flag():
    assert hp.runtime_cpu_only({"load_mode": "CPU", "n_gpu_layers": 99}) is True
    assert hp.runtime_cpu_only({"gpu_offload_supported": False, "n_gpu_layers": 6}) is True
    assert hp.runtime_cpu_only({"effective": {"n_gpu_layers": 0}, "n_gpu_layers": 2}) is True
    assert hp.runtime_cpu_only({"n_gpu_layers": 4, "load_mode": "GPU"}) is False


def test_gpu_offload_unavailable_message_intel():
    msg = hp.gpu_offload_unavailable_message(
        gpu_vendor="intel", gpu_integrated=True, vulkan_available=True,
    )
    assert "Vulkan GPU pack" in msg
    assert "NVIDIA" not in msg


def test_resolve_gpu_for_allocate_falls_back_to_detect_hardware(monkeypatch):
    from eli.core import startup_hardware_optimizer as sho

    monkeypatch.setattr(sho, "detect_gpus", lambda: [])
    monkeypatch.setattr(
        hp,
        "detect_hardware",
        lambda **_: hp.HardwareProfile(
            has_gpu=True,
            gpu_integrated=True,
            gpu_vendor="intel",
            gpu_name="Intel Iris Xe",
            free_vram_mb=1400,
            total_vram_mb=1500,
        ),
    )
    gpu = sho.resolve_gpu_for_allocate()
    assert gpu is not None
    assert gpu.free_mb == 1400
    assert gpu.vendor == "intel"
