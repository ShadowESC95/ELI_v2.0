"""GPU detection must work on every OS, not just the one it was written on.

Reported: "the OS not recognising and using the GPU (this worked around 20/30
releases ago)". It is a real regression and it was one line.

`detect_hardware()` reads free VRAM from `nvidia-smi`. When that call fails --
which on Windows it routinely does, because the driver installs nvidia-smi into
System32 and the CUDA toolkit into its own directory, and neither is reliably
on PATH inside a frozen app -- the code fell through to a fallback gated on:

    if not hw.has_gpu and sys.platform.startswith("linux") and _nvidia_driver_loaded():

Every signal behind that gate is Linux-only (/proc/driver/nvidia,
/sys/module/nvidia, /sys/bus/pci). So off Linux there was NO fallback at all:
has_gpu stayed False, the smart loader sized 0 offloaded layers, and a working
card ran on CPU. The kernel-signal rewrite made Linux robust and silently left
Windows and macOS with nothing.
"""
import inspect
import re
import sys
from pathlib import Path

import pytest

from eli.core import hardware_profile as hp
from eli.core import startup_hardware_optimizer as sho


# ── nvidia-smi must be found by path, never by bare name ───────────────────
def test_nvidia_smi_resolver_exists():
    assert hasattr(hp, "nvidia_smi_path")


def test_resolver_checks_windows_install_locations():
    src = inspect.getsource(hp.nvidia_smi_path)
    assert "System32" in src, "does not look where the Windows driver puts it"
    assert "NVSMI" in src, "does not look where the CUDA toolkit puts it"


def test_detect_hardware_uses_the_resolver_not_a_bare_name():
    src = inspect.getsource(hp._detect_hardware_impl)
    assert "nvidia_smi_path()" in src
    assert '["nvidia-smi",' not in src, "still invokes nvidia-smi by bare name"


def test_startup_optimizer_uses_the_resolver_too():
    src = inspect.getsource(sho.detect_nvidia_gpus)
    assert "nvidia_smi_path" in src
    assert '"nvidia-smi",' not in src, "still invokes nvidia-smi by bare name"


# ── the fallback must not be Linux-only ────────────────────────────────────
def test_gpu_fallback_is_not_gated_to_linux_alone():
    """The exact defect: every fallback sat behind a linux-only condition."""
    src = inspect.getsource(hp._detect_hardware_impl)
    tail = src[src.index("_nvidia_driver_loaded()"):]
    assert "_windows_gpus()" in tail, "no Windows fallback after nvidia-smi fails"
    assert "_macos_gpus()" in tail, "no macOS fallback after nvidia-smi fails"


@pytest.mark.parametrize("fn", ["_windows_gpus", "_macos_gpus"])
def test_native_enumerators_exist_and_are_safe_off_platform(fn):
    """Each must no-op rather than raise on the wrong OS -- they run inside
    detect_hardware() on every start."""
    assert hasattr(hp, fn)
    assert getattr(hp, fn)() == [] or sys.platform in ("win32", "darwin")


def test_windows_enumeration_reads_64bit_vram():
    """WMI's AdapterRAM is signed 32-bit and saturates at 4 GB, so an 8 GB card
    reports ~4095 MB and the loader under-provisions it. The registry value is
    64-bit and correct."""
    src = inspect.getsource(hp._windows_gpus)
    assert "qwMemorySize" in src, "falls back to the 4 GB-capped AdapterRAM only"
    assert "Win32_VideoController" in src


def test_macos_handles_unified_memory():
    """Apple Silicon reports no discrete VRAM; a 0 there must not mean 'no GPU'."""
    src = inspect.getsource(hp._detect_hardware_impl)
    assert "darwin" in src and "ram_gb" in src


def test_startup_optimizer_falls_back_to_native_enumeration():
    src = inspect.getsource(sho.detect_gpus)
    assert "detect_native_gpus" in src, \
        "detect_other_gpus reads lspci/rocm-smi, neither of which exists off Linux"


# ── the frozen-app path (what a downloaded exe actually runs) ──────────────
def test_gpu_pack_resolves_nvidia_smi_by_path():
    src = Path("packaging/pyinstaller/eli_gpu_pack.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "def _smi(" in code, "gpu pack has no path resolver"
    assert 'shutil.which("nvidia-smi")' in code, "resolver should still try PATH first"
    assert code.count('smi = shutil.which("nvidia-smi")') == 0, \
        "gpu pack still looks up nvidia-smi by bare name"


def test_gpu_pack_can_read_a_driver_version_off_linux():
    """/proc/driver/nvidia does not exist on Windows; without a registry read the
    driver version was unknowable and no CUDA build could be selected."""
    src = Path("packaging/pyinstaller/eli_gpu_pack.py").read_text(encoding="utf-8")
    assert "DriverVersion" in src and "win32" in src


# ── live sanity on whatever machine runs the suite ─────────────────────────
def test_detect_hardware_reports_consistently():
    hw = hp.detect_hardware()
    assert hw.cpu_threads >= 1
    if hw.has_gpu:
        assert hw.gpu_name, "GPU reported with no name"
        assert hw.free_vram_mb > 0, "GPU reported with no usable VRAM"
        assert hw.free_vram_mb <= hw.total_vram_mb, "free VRAM exceeds total"


# ── "no GPU" vs "couldn't check": confirmed negative and probe failure must
# not collapse into the same has_gpu=False with no way to tell them apart.
# Every vendor probe failure used to be silently indistinguishable from a
# genuinely GPU-less machine, so a probe timeout/missing-tool/permission
# error got reported to the user with the same confidence as a verified "no
# GPU here" — the worst failure mode for a product whose pitch is honest,
# grounded local intelligence. ─────────────────────────────────────────────
def test_confirmed_no_gpu_is_not_marked_uncertain(monkeypatch):
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: None)
    monkeypatch.setattr(hp, "_nvidia_driver_loaded", lambda: False)
    monkeypatch.setattr(hp, "_windows_gpus", lambda: [])
    monkeypatch.setattr(hp, "_macos_gpus", lambda: [])
    monkeypatch.setattr(hp, "_linux_intel_display_adapters", lambda: [])
    monkeypatch.setattr(hp, "_linux_qualcomm_display_adapters", lambda: [])
    monkeypatch.setattr(hp, "_linux_gpu_pci_device_present", lambda: False)
    monkeypatch.setattr(sys, "platform", "linux")

    hw = hp._detect_hardware_impl()
    assert hw.has_gpu is False
    assert hw.gpu_detection_uncertain is False, (
        "a genuinely GPU-less machine must not be flagged uncertain"
    )
    assert hw.gpu_name == "CPU only"


def test_probe_failure_with_real_gpu_present_is_marked_uncertain(monkeypatch):
    """A GPU PCI device exists (kernel sees it) but every vendor-specific probe
    above failed to characterize it -- this must NOT be reported the same way
    as a confirmed GPU-less machine."""
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: None)
    monkeypatch.setattr(hp, "_nvidia_driver_loaded", lambda: False)
    monkeypatch.setattr(hp, "_windows_gpus", lambda: [])
    monkeypatch.setattr(hp, "_macos_gpus", lambda: [])
    monkeypatch.setattr(hp, "_linux_intel_display_adapters", lambda: [])
    monkeypatch.setattr(hp, "_linux_qualcomm_display_adapters", lambda: [])
    monkeypatch.setattr(hp, "_linux_gpu_pci_device_present", lambda: True)
    monkeypatch.setattr(sys, "platform", "linux")

    hw = hp._detect_hardware_impl()
    assert hw.has_gpu is False, "still safe to default to no-offload when uncertain"
    assert hw.gpu_detection_uncertain is True, (
        "a real GPU PCI device that no probe could characterize must be "
        "flagged uncertain, not silently reported as 'no GPU'"
    )
    assert hw.gpu_name != "CPU only", (
        "an uncertain detection must not use the same label as a confirmed negative"
    )


def test_gpu_detection_uncertain_defaults_false_and_round_trips_to_dict():
    hw = hp.HardwareProfile()
    assert hw.gpu_detection_uncertain is False
    assert hp.HardwareProfile(gpu_detection_uncertain=True).to_dict()["gpu_detection_uncertain"] is True
