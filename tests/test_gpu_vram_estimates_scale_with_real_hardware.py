"""Reported: GPU layer counts crashed on a machine whose nvidia-smi was broken
(NVML "Driver/library version mismatch" after a driver update with no reboot)
-- the RTX 2060 SUPER's real ~7.75GB VRAM fell back to a flat 4096MB guess,
roughly halving every GPU layer count. A table of NVIDIA and Intel Arc models and
their factory memory replaced the flat guess, and was still a guess: every card
missing from it, every later model and every variant got a wrong figure.

Now a card whose memory no source reports keeps its name, its memory is left
unknown and flagged uncertain, and llama.cpp measures it before a load
(eli/core/load_plan.py). The unified-memory share scales with the RAM actually
available, with no floor or ceiling of ELI's own.
"""
from eli.core import hardware_profile as hwp


def test_no_table_of_cards_stands_in_for_a_reading():
    for name in ("_NVIDIA_VRAM_MB_BY_MODEL", "_nvidia_vram_mb_from_model_name",
                 "_INTEL_ARC_VRAM_MB_BY_MODEL", "_intel_arc_vram_mb_from_name"):
        assert not hasattr(hwp, name), name


def test_a_card_whose_memory_is_unread_is_still_planned_for(monkeypatch):
    """No free figure: the card's total stands for it, flagged uncertain, and the plan reads it."""
    hw = hwp.HardwareProfile()
    assert hwp._apply_cards(hw, [{"name": "Intel Arc A770", "vendor": "intel", "integrated": False,
                                  "total_mb": None, "free_mb": None}])
    assert hw.has_gpu and hw.gpu_detection_uncertain and hw.free_vram_mb == 0
    monkeypatch.setattr(hwp, "_llama_gpu_offload_available", lambda: True)
    monkeypatch.delenv("ELI_FORCE_GPU_LAYERS", raising=False)
    assert hwp.effective_use_gpu_layers(hw)


def test_nvidia_gpu_model_from_proc_reads_information_file(tmp_path, monkeypatch):
    gpu_dir = tmp_path / "gpus" / "0000:01:00.0"
    gpu_dir.mkdir(parents=True)
    (gpu_dir / "information").write_text(
        "Model: \t\t NVIDIA GeForce RTX 2060 SUPER\nIRQ: \t\t 133\n",
        encoding="utf-8",
    )
    real_path = hwp.Path

    def _fake_path(p, *a, **k):
        if str(p) == "/proc/driver/nvidia/gpus":
            return real_path(tmp_path / "gpus")
        return real_path(p, *a, **k)

    monkeypatch.setattr(hwp, "Path", _fake_path)
    name = hwp._nvidia_gpu_model_from_proc()
    assert name == "NVIDIA GeForce RTX 2060 SUPER"


def test_integrated_vram_budget_scales_with_ram_not_capped_at_8gb():
    """The regression: a unified-memory machine with far more than 8GB RAM
    used to get the identical 8192MB ceiling as a small laptop iGPU."""
    small_free, small_total = hwp._estimate_integrated_vram_mb(ram_gb=16.0, available_ram_gb=12.0)
    big_free, big_total = hwp._estimate_integrated_vram_mb(ram_gb=128.0, available_ram_gb=100.0)
    assert big_total > 8192, "a 128GB unified-memory machine must not be capped at 8GB"
    assert big_total > small_total, "more available RAM must yield a bigger shared-VRAM budget"
    assert big_free <= big_total


def test_integrated_vram_budget_matches_cpu_ram_budget_basis():
    """Same fraction-of-available-RAM basis as cpu_ram_budget_mb -- the two
    must not diverge in scale for the same machine."""
    avail_gb = 64.0
    free_mb, _total_mb = hwp._estimate_integrated_vram_mb(ram_gb=96.0, available_ram_gb=avail_gb)
    cpu_budget_mb = hwp.cpu_ram_budget_mb(avail_gb)
    assert free_mb == cpu_budget_mb


def test_a_small_device_gets_its_own_share_not_a_floor():
    """A floor of 512 MB free and 2 GB total promised a phone with 1 GB available more than it had."""
    free_mb, total_mb = hwp._estimate_integrated_vram_mb(ram_gb=2.0, available_ram_gb=1.0)
    assert 0 < free_mb < 1024 and total_mb == free_mb
    assert hwp.cpu_ram_budget_mb(0.25) < 256
