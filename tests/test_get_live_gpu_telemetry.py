"""get_live_gpu_telemetry() is the one place every caller asks "what are my GPUs doing right now",
for every card, every vendor and every OS. Eight call sites used to run nvidia-smi themselves and
read its first line, so a second card, an AMD, Intel or Apple GPU, or a Windows machine without
nvidia-smi on PATH showed as one card or none.

Each source is read by one function, shared with detect_hardware(): nvidia-smi, the amdgpu driver's
own counters (Linux), rocm-smi, DXGI (Windows, any vendor), the IOAccelerator registry (macOS), and
llama.cpp's own device list for whatever the others leave out.
"""
import json
import os
import plistlib
import sys
import types

import pytest

import eli.core.hardware_profile as hp

GIB = 1024 ** 3
MIB = 1024 ** 2


def _hw(**kw):
    return hp.HardwareProfile(**kw)


@pytest.fixture
def machine(monkeypatch, quiet_gpu_sources):
    """quiet_gpu_sources, and detect_hardware() returning the profile a test passes."""
    def use(hw):
        monkeypatch.setattr(hp, "detect_hardware", lambda: hw)
    return use


def _run_returns(monkeypatch, returncode, stdout):
    monkeypatch.setattr(hp.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=""))


# ── no GPU ───────────────────────────────────────────────────────────────────

def test_a_cpu_only_machine_reports_no_gpu(machine):
    machine(_hw())
    out = hp.get_live_gpu_telemetry()
    assert out["ok"] is False and out["total_mb"] is None and out["devices"] == []
    assert hp.describe_gpus(out) == "unavailable"


# ── NVIDIA ───────────────────────────────────────────────────────────────────

def test_every_nvidia_card_is_read_and_summed(machine, monkeypatch):
    machine(_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER ×2", gpu_vendor="nvidia",
                total_vram_mb=16384, free_vram_mb=14000))
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: "/usr/bin/nvidia-smi")
    _run_returns(monkeypatch, 0,
                 "NVIDIA GeForce RTX 2060 SUPER, 8192, 1300, 6892, 61, 58, 95.5, 175.0, 595.99.02\n"
                 "NVIDIA GeForce RTX 2060 SUPER, 8192, 400, 7792, 4, 41, 12.0, 175.0, 595.99.02\n")
    out = hp.get_live_gpu_telemetry()
    assert out["name"] == "NVIDIA GeForce RTX 2060 SUPER ×2"
    assert (out["total_mb"], out["used_mb"], out["free_mb"]) == (16384, 1700, 14684)
    assert (out["util_pct"], out["temp_c"]) == (61, 58)          # the busiest card
    assert out["power_w"] == pytest.approx(107.5) and out["power_limit_w"] == pytest.approx(350.0)
    assert out["driver"] == "595.99.02" and out["live_probe_failed"] is False
    assert [d["free_mb"] for d in out["devices"]] == [6892, 7792]
    text = hp.describe_gpus(out)
    assert "GPU 0" in text and "GPU 1" in text and "7792 MiB free" in text


def test_nvidia_smi_messages_are_not_cards(monkeypatch):
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: "/usr/bin/nvidia-smi")
    _run_returns(monkeypatch, 0, "No devices were found\n")
    assert hp._nvidia_cards() is None


def test_a_broken_nvidia_driver_falls_back_to_the_estimate_and_says_so(machine, monkeypatch):
    """The field case: NVML "Driver/library version mismatch"."""
    machine(_hw(has_gpu=True, gpu_name="NVIDIA GeForce RTX 2060 SUPER", gpu_vendor="nvidia",
                total_vram_mb=8192, free_vram_mb=6963, gpu_detection_uncertain=True))
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: "/usr/bin/nvidia-smi")
    _run_returns(monkeypatch, 18, "Failed to initialize NVML: Driver/library version mismatch\n")
    out = hp.get_live_gpu_telemetry()
    assert out["ok"] is True and out["live_probe_failed"] is True and out["estimated"] is True
    assert (out["name"], out["total_mb"]) == ("NVIDIA GeForce RTX 2060 SUPER", 8192)
    assert out["util_pct"] is None and out["temp_c"] is None
    assert hp.gpu_label(out) == "NVIDIA GeForce RTX 2060 SUPER (estimated)"


# ── AMD on Linux: the amdgpu driver's counters, then rocm-smi ────────────────

def _symlink(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:     # Windows without symlink rights
        pytest.skip(f"symlinks unavailable: {exc}")


def _pci(tmp_path, addr, vendor, **files):
    dev = tmp_path / "pci" / (addr.replace(":", "_") if os.name == "nt" else addr)   # Windows names have no ':'
    dev.mkdir(parents=True)
    if vendor:
        (dev / "vendor").write_text(vendor)
    for name, value in files.items():
        path = dev / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value))
    return dev


def _drm(tmp_path, monkeypatch, cards):
    """A /sys/class/drm with `cards`: {name: device directory}."""
    root = tmp_path / "drm"
    root.mkdir()
    for name, dev in cards.items():
        (root / name).mkdir()
        _symlink(root / name / "device", dev)
    monkeypatch.setattr(hp, "_DRM_ROOT", root)
    monkeypatch.setattr(hp.sys, "platform", "linux")


def test_the_linux_device_scan_finds_every_gpu_once(tmp_path, monkeypatch):
    amd = _pci(tmp_path, "0000:03:00.0", "0x1002")
    intel = _pci(tmp_path, "0000:00:02.0", "0x8086")
    adreno = tmp_path / "soc" / "ae00000.gpu"
    adreno.mkdir(parents=True)
    (tmp_path / "drivers" / "msm").mkdir(parents=True)
    _symlink(adreno / "driver", tmp_path / "drivers" / "msm")
    (adreno / "of_node").mkdir()
    (adreno / "of_node" / "compatible").write_bytes(b"qcom,adreno-43050c01\0qcom,adreno\0")
    _drm(tmp_path, monkeypatch, {"card0": amd, "card1": intel, "card2": adreno, "card3": amd})
    (tmp_path / "drm" / "card0-DP-1").mkdir()                       # a connector, not a device
    found = hp._linux_drm_gpus()
    assert [v for v, _ in found] == ["amd", "intel", "qualcomm"]
    monkeypatch.setattr(hp, "_lspci_name_for_pci_addr", lambda addr: "")
    assert hp._linux_soc_display_adapters() == [("qcom,adreno-43050c01", "qualcomm")]


def test_amd_cards_are_read_from_the_kernel_driver_without_rocm(tmp_path, monkeypatch):
    card = _pci(tmp_path, "0000:03:00.0", "0x1002", mem_info_vram_total=16 * GIB,
                mem_info_vram_used=1 * GIB, gpu_busy_percent=37,
                hwmon__hwmon3__temp1_input=54000, hwmon__hwmon3__power1_average=41_000_000,
                hwmon__hwmon3__power1_cap=203_000_000)
    apu = _pci(tmp_path, "0000:0c:00.0", "0x1002", mem_info_vram_total=64 * MIB, mem_info_vram_used=0)
    monkeypatch.setattr(hp, "detect_hardware", lambda: _hw(has_gpu=True, gpu_vendor="amd", gpu_name="AMD GPU",
                                                          total_vram_mb=16384, free_vram_mb=15000))
    monkeypatch.setattr(hp, "_lspci_name_for_pci_addr", lambda addr: "")
    monkeypatch.setattr(hp, "_llama_cpp_cards", lambda: None)
    _drm(tmp_path, monkeypatch, {"card0": card, "card1": apu})
    cards = hp._amd_cards()
    assert [c["integrated"] for c in cards] == [False, True]
    assert cards[1]["total_mb"] is None                     # an APU's memory is system memory
    out = hp.get_live_gpu_telemetry()
    assert (out["total_mb"], out["used_mb"], out["free_mb"]) == (16384, 1024, 15360)
    assert (out["util_pct"], out["temp_c"]) == (37, 54)
    assert out["power_w"] == pytest.approx(41.0) and out["power_limit_w"] == pytest.approx(203.0)
    assert len(out["devices"]) == 1                          # the APU is not where a model loads


def test_rocm_smi_reads_every_card_when_the_driver_counters_are_absent(machine, monkeypatch):
    machine(_hw(has_gpu=True, gpu_vendor="amd", gpu_name="AMD GPU", total_vram_mb=49152, free_vram_mb=40000))
    monkeypatch.setattr(hp.sys, "platform", "linux")
    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/bin/rocm-smi" if name == "rocm-smi" else None)
    data = {f"card{i}": {"VRAM Total Memory (B)": str(24 * GIB), "VRAM Total Used Memory (B)": str(used * GIB)}
            for i, used in enumerate((4, 2))}
    _run_returns(monkeypatch, 0, json.dumps(data))
    out = hp.get_live_gpu_telemetry()
    assert (out["total_mb"], out["used_mb"], out["free_mb"]) == (49152, 6144, 43008)
    assert out["util_pct"] is None and out["temp_c"] is None   # rocm-smi was not asked; nothing made up
    assert len(out["devices"]) == 2


def test_amd_without_any_live_source_still_reports_what_detection_found(machine):
    machine(_hw(has_gpu=True, gpu_vendor="amd", gpu_name="AMD Radeon RX 7900 XTX",
                total_vram_mb=24576, free_vram_mb=22000))
    out = hp.get_live_gpu_telemetry()
    assert out["ok"] is True and out["name"] == "AMD Radeon RX 7900 XTX" and out["total_mb"] == 24576


# ── Windows, any vendor: DXGI ────────────────────────────────────────────────

def test_a_dedicated_card_is_used_before_the_integrated_one():
    hw = _hw(ram_gb=32.0, available_ram_gb=24.0)
    assert hp._apply_cards(hw, [
        {"name": "Intel(R) UHD Graphics 770", "vendor": "intel", "integrated": True, "total_mb": 16000, "free_mb": 15000},
        {"name": "NVIDIA GeForce RTX 4060 Laptop GPU", "vendor": "nvidia", "integrated": False,
         "total_mb": 8188, "free_mb": 7100},
    ])
    assert (hw.gpu_name, hw.gpu_vendor, hw.gpu_integrated, hw.free_vram_mb) == (
        "NVIDIA GeForce RTX 4060 Laptop GPU", "nvidia", False, 7100)
    assert [g["name"] for g in hw.gpus] == ["Intel(R) UHD Graphics 770", "NVIDIA GeForce RTX 4060 Laptop GPU"]


def test_a_card_with_no_free_figure_is_flagged_not_guessed():
    """It took four fifths of the card; what the desktop holds is unknown, and the plan reads it."""
    hw = _hw()
    hp._apply_cards(hw, [{"name": "AMD Radeon RX 6600", "vendor": "amd", "integrated": False,
                          "total_mb": 8192, "free_mb": None}])
    assert hw.total_vram_mb == 8192 and hw.free_vram_mb == 8192 and hw.gpu_detection_uncertain


def test_a_laptop_with_only_integrated_graphics_uses_the_os_figure():
    hw = _hw(ram_gb=16.0, available_ram_gb=10.0)
    hp._apply_cards(hw, [{"name": "Intel(R) Iris(R) Xe Graphics", "vendor": "intel", "integrated": True,
                          "total_mb": 8000, "free_mb": 7600}])
    assert hw.has_gpu and hw.gpu_integrated and hw.free_vram_mb == 7600


def test_dxgi_is_only_asked_on_windows():
    if os.name != "nt":
        assert hp._windows_dxgi_adapters() is None


@pytest.mark.skipif(os.name != "nt", reason="DXGI exists only on Windows")
def test_dxgi_lists_this_machines_adapters():
    """Every COM call DXGI enumeration makes, on a real Windows: a GPU-less runner has only the
    software renderer, which is listed when asked for."""
    adapters = hp._windows_dxgi_adapters(software=True)
    assert adapters, "DXGI returned no adapter at all"
    for a in adapters:
        assert a["name"] and a["vendor"] and a["total_mb"] is not None
        assert a["free_mb"] is None or a["free_mb"] >= 0


# ── macOS: the IOAccelerator registry ────────────────────────────────────────

def test_macos_reads_apple_silicon_and_amd_cards(monkeypatch):
    monkeypatch.setattr(hp.sys, "platform", "darwin")
    monkeypatch.setattr(hp.shutil, "which", lambda name: "/usr/sbin/ioreg" if name == "ioreg" else None)
    entries = [
        {"IOClass": "AGXAcceleratorG14X", "model": "Apple M2 Pro",
         "PerformanceStatistics": {"Device Utilization %": 12, "In use system memory": 2 * GIB}},
        {"IOClass": "AMDRadeonX6000_AMDNavi21GraphicsAccelerator", "model": b"AMD Radeon Pro W6800X\x00",
         "PerformanceStatistics": {"vramFreeBytes": 30 * GIB, "vramUsedBytes": 2 * GIB,
                                   "Device Utilization %": 5, "Temperature(C)": 48}},
    ]
    raw = plistlib.dumps(entries)
    monkeypatch.setattr(hp.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=raw))
    apple, amd = hp._macos_accelerators()
    assert (apple["name"], apple["vendor"], apple["integrated"]) == ("Apple M2 Pro", "apple", True)
    assert apple["used_mb"] == 2048 and apple["total_mb"] is None and apple["util_pct"] == 12
    assert (amd["name"], amd["vendor"], amd["integrated"]) == ("AMD Radeon Pro W6800X", "amd", False)
    assert (amd["total_mb"], amd["free_mb"], amd["temp_c"]) == (32768, 30720, 48)


@pytest.mark.skipif(sys.platform != "darwin", reason="ioreg exists only on macOS")
def test_ioreg_answers_on_this_mac():
    cards = hp._macos_accelerators()
    assert cards is None or isinstance(cards, list)


def test_what_a_vendor_tool_leaves_out_comes_from_llama_cpp(machine, monkeypatch):
    """Apple's registry gives no total for unified memory; Metal's working-set figure does."""
    machine(_hw(has_gpu=True, gpu_vendor="apple", gpu_integrated=True, gpu_name="Apple M2 Pro",
                total_vram_mb=12000, free_vram_mb=11000))
    monkeypatch.setattr(hp.sys, "platform", "darwin")
    monkeypatch.setattr(hp, "_macos_accelerators", lambda: [
        {"index": 0, "name": "Apple M2 Pro", "vendor": "apple", "integrated": True, "total_mb": None,
         "free_mb": None, "used_mb": 2048.0, "util_pct": 12.0, "temp_c": None, "power_w": None,
         "power_limit_w": None}])
    monkeypatch.setattr(hp, "_llama_cpp_cards", lambda: [
        {"index": 0, "name": "Apple M2 Pro", "total_mb": 21845, "free_mb": 19797, "used_mb": 2048}])
    out = hp.get_live_gpu_telemetry()
    assert (out["total_mb"], out["free_mb"], out["used_mb"], out["util_pct"]) == (21845, 19797, 2048, 12)


# ── every status surface reads the same telemetry ────────────────────────────

_AMD = {"ok": True, "name": "AMD Radeon RX 7900 XTX", "vendor": "amd", "estimated": False,
        "live_probe_failed": False, "total_mb": 24576, "free_mb": 22000, "used_mb": 2576,
        "util_pct": None, "temp_c": None, "driver": None, "devices": [{"index": 0}]}


def test_every_status_surface_shows_a_non_nvidia_gpu(monkeypatch):
    from eli.contracts import runtime_status
    from eli.runtime import self_status, truth_report
    monkeypatch.setattr(hp, "get_live_gpu_telemetry", lambda: dict(_AMD))
    assert truth_report._gpu_info()["name"] == "AMD Radeon RX 7900 XTX"
    assert truth_report._gpu_info()["memory_total_mib"] == 24576
    assert runtime_status._gpu_probe()["total_mib"] == 24576
    assert self_status._gpu()["vram_used_mb"] == 2576
    assert "AMD Radeon RX 7900 XTX" in hp.describe_gpus(dict(_AMD))
    # grounded evidence and replies print the same line: each had its own nvidia-smi call that
    # said "unavailable" on every other vendor and on an NVIDIA driver mismatch
    from eli.runtime import deterministic_grounding_gate, user_visible_response_surface
    assert deterministic_grounding_gate._describe_gpus is hp.describe_gpus
    assert user_visible_response_surface._describe_gpus is hp.describe_gpus


def test_the_gpu_line_lists_every_card():
    line = hp.describe_gpus({"ok": True, "devices": [
        {"index": 0, "name": "Card A", "total_mb": 8192, "free_mb": 7000},
        {"index": 1, "name": "Card B", "total_mb": 16384, "free_mb": 15000}]})
    assert line.startswith("2 GPUs") and "Card A" in line and "Card B" in line


def test_every_status_surface_says_no_gpu_on_a_cpu_only_machine(monkeypatch):
    from eli.contracts import runtime_status
    from eli.runtime import self_status, truth_report
    monkeypatch.setattr(hp, "get_live_gpu_telemetry", lambda: {"ok": False})
    assert truth_report._gpu_info() == {"available": False}
    assert runtime_status._gpu_probe() == {}
    assert self_status._gpu() is None
    assert hp.describe_gpus({"ok": False}) == "unavailable"
