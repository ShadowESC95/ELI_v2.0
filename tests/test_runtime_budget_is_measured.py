"""The CPU context ceiling scales with measured RAM and the model's own KV cost, not size bands.

A table here once picked ctx from {16384, 12288, 8192, 6144, 4096} by RAM band and disagreed with
the loader: on a live 2.3.0 launch it said ctx=12288 while the resident context was 10384.
"""
from eli.core import startup_hardware_optimizer as sho


def test_ctx_ceiling_scales_with_ram_rather_than_stepping():
    """More available RAM must raise the ceiling (model weight reserved first)."""
    small = sho._ctx_ceiling_for_ram(8, 1.8)
    mid = sho._ctx_ceiling_for_ram(16, 1.8)
    assert mid > small, "the ceiling did not move with RAM"
    large = sho._ctx_ceiling_for_ram(32, 1.8)
    assert large > mid


def test_a_heavier_model_gets_a_smaller_ceiling():
    """KV cost per token rises with layer count, so the ceiling must fall."""
    light = sho._ctx_ceiling_for_ram(16, 4.68)
    heavy = sho._ctx_ceiling_for_ram(16, 40.0)
    assert heavy < light


def test_the_ceiling_never_exceeds_the_training_window():
    """llama.cpp warns `n_ctx_seq > n_ctx_train`; beyond it quality degrades.

    The ceiling is bounded by the MODEL's own trained window, not by a constant
    — ELI runs 1B to 100B+, so a fixed cap would clamp a 128k model.
    """
    assert sho._ctx_ceiling_for_ram(1024, 4.68, 32768) <= 32768
    assert sho._ctx_ceiling_for_ram(1024, 4.68, 131072) <= 131072


def test_the_ceiling_has_a_floor():
    assert sho._ctx_ceiling_for_ram(0, 4.68) >= sho._MIN_CTX
    assert sho._ctx_ceiling_for_ram(-5, 4.68) >= sho._MIN_CTX


def test_ctx_ceiling_subtracts_model_weight_from_available_ram():
    """Low available RAM + multi-GB model must not over-estimate ctx ceiling."""
    tight = sho._ctx_ceiling_for_ram(4.7, 1.8, 32768)
    loose = sho._ctx_ceiling_for_ram(16, 1.8, 32768)
    assert tight < loose
    assert tight <= 4096, f"4.7GB free with 1.8GB model should stay modest, got {tight}"


def test_the_per_token_cost_is_the_loaders_own_measurement():
    """Not a constant invented in this module — an earlier draft did exactly
    that and implied an 18k context on an 8GB machine."""
    import inspect
    src = inspect.getsource(sho._ctx_ceiling_for_ram)
    assert "_kv_cache_mb" in src and "_layers_for_size" in src


def test_memory_that_cannot_be_read_is_unknown_not_invented(monkeypatch):
    """Two readers returned 8 GB (and "half of it free") for a machine they could not read."""
    import sys
    from eli.core import hardware_profile as hp
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(hp.sys, "platform", "an-os-with-no-reader")
    assert hp.system_ram_gib() == (0.0, 0.0)
    assert sho.detect_available_ram_gb() == 0.0
