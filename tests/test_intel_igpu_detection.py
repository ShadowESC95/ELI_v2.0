"""Intel Iris Xe / UHD laptops must not be reported as 'no GPU'."""
from __future__ import annotations

from pathlib import Path

from eli.core import hardware_profile as hp


def test_intel_integrated_profile_fields():
    hw = hp.HardwareProfile(ram_gb=16.0, available_ram_gb=10.0)
    hp._apply_intel_integrated_profile(hw, "Intel Iris Xe Graphics")
    assert hw.has_gpu is True
    assert hw.gpu_vendor == "intel"
    assert hw.gpu_integrated is True
    assert hw.gpu_name == "Intel Iris Xe Graphics"
    assert hw.free_vram_mb > 0
    assert hw.total_vram_mb >= hw.free_vram_mb


def test_discrete_arc_device_ids_are_not_treated_as_igpu(tmp_path):
    dev = tmp_path / "0000:03:00.0"
    dev.mkdir()
    (dev / "vendor").write_text("0x8086", encoding="utf-8")
    (dev / "device").write_text("0x56a0", encoding="utf-8")  # Arc A770 family
    assert hp._intel_pci_device_is_discrete_arc(dev) is True


def test_integrated_intel_device_is_not_arc(tmp_path):
    dev = tmp_path / "0000:00:02.0"
    dev.mkdir()
    (dev / "vendor").write_text("0x8086", encoding="utf-8")
    (dev / "device").write_text("0x9a49", encoding="utf-8")  # typical Iris Xe
    assert hp._intel_pci_device_is_discrete_arc(dev) is False


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

    hw = hp.detect_hardware()
    assert hw.has_gpu is True
    assert hw.gpu_integrated is True
    assert "iris" in hw.gpu_name.lower()


def test_install_script_reports_intel_integrated():
    text = Path("install.sh").read_text(encoding="utf-8")
    assert "HAS_INTEL_IGPU" in text
    assert "Intel integrated" in text
    assert "GGML_VULKAN=on" in text
