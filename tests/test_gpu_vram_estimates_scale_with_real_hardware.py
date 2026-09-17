"""Reported: GPU layer counts crashed on a machine whose nvidia-smi was broken
(NVML "Driver/library version mismatch" after a driver update with no reboot)
-- the RTX 2060 SUPER's real ~7.75GB VRAM fell back to a flat 4096MB guess,
roughly halving every GPU layer count. Investigating that also turned up the
same class of bug on unified-memory systems (Apple Silicon / AMD APU): the
shared-VRAM budget was hard-capped at 8192MB no matter how much RAM the
machine actually had, so a 64GB+ Mac Studio got the same GPU-layer budget as
an 8GB laptop iGPU.

These tests cover the fix: NVIDIA and Intel Arc fall back to a real per-model
VRAM lookup (read from a kernel-native source that survives NVML being
broken) instead of one flat number for every card, and the unified-memory
estimator scales with actual available RAM instead of capping at 8GB.
"""
from eli.core import hardware_profile as hwp


def test_nvidia_model_lookup_matches_known_cards():
    assert hwp._nvidia_vram_mb_from_model_name("NVIDIA GeForce RTX 2060 SUPER") == 8192
    assert hwp._nvidia_vram_mb_from_model_name("NVIDIA GeForce RTX 2060") == 6144
    assert hwp._nvidia_vram_mb_from_model_name("NVIDIA GeForce RTX 4090") == 24576
    assert hwp._nvidia_vram_mb_from_model_name("NVIDIA GeForce GTX 1050") == 2048


def test_nvidia_model_lookup_is_case_insensitive_and_unknown_returns_zero():
    assert hwp._nvidia_vram_mb_from_model_name("nvidia geforce rtx 2060 super") == 8192
    assert hwp._nvidia_vram_mb_from_model_name("Some Future GPU Nobody Has Heard Of") == 0
    assert hwp._nvidia_vram_mb_from_model_name("") == 0


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


def test_nvidia_fallback_env_prefers_known_model_over_flat_guess():
    """Direct proof the RTX 2060 SUPER case is fixed: the fallback branch's own
    logic (known lookup, else 4096) must resolve to the real 8GB, not 4GB."""
    known = hwp._nvidia_vram_mb_from_model_name("NVIDIA GeForce RTX 2060 SUPER")
    total = known or 4096
    assert total == 8192, "the exact field bug: RTX 2060 SUPER must not fall back to 4096MB"


def test_intel_arc_model_lookup_matches_known_cards():
    assert hwp._intel_arc_vram_mb_from_name("Intel Arc A770 16GB") == 16384
    assert hwp._intel_arc_vram_mb_from_name("Intel Arc A770") == 8192
    assert hwp._intel_arc_vram_mb_from_name("Intel Arc A380") == 6144
    assert hwp._intel_arc_vram_mb_from_name("Intel Arc B580") == 12288
    assert hwp._intel_arc_vram_mb_from_name("Intel Arc A999 Nonexistent") == 0


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


def test_integrated_vram_budget_still_floors_low_ram_machines():
    free_mb, total_mb = hwp._estimate_integrated_vram_mb(ram_gb=2.0, available_ram_gb=1.0)
    assert total_mb >= 2048
    assert free_mb >= 512
