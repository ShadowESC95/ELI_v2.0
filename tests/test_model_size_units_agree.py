"""hardware_profile.discover_models() computed a model's size as bytes / 1e9 (decimal
GB) while moe_offload.plan_for_load() — used at actual load time — computes the same
file's size as bytes / 1024**3 (binary GiB), both labelled "GB". For a real ~19.71 GiB
model file this printed as 19.71GB at load time but 21.17GB during the earlier
hardware-tuning pass, and every MoE resident/experts split computed from the tuning-pass
figure (mixture-of-experts model size, ~19.05GB of experts) then disagreed with the one
computed from the load-time figure (~17.74GB) for the identical file — the same
real-world fact reported as two different numbers depending on which code path measured
it first. Every other size hardware_profile.py itself reports (free_vram_mb,
total_vram_mb) already uses the binary base; discover_models() now matches it and
moe_offload.py's own stat()-based math, instead of being the odd one out.
"""
from __future__ import annotations

from eli.core import hardware_profile, moe_offload
from tests._sparse import sparse_file


def test_discover_models_uses_the_same_binary_base_as_moe_offload(tmp_path):
    model_file = tmp_path / "model.gguf"
    sparse_file(model_file, 2 * 1024 ** 3)  # exactly 2 GiB st_size; sparse, so no real disk or RAM used

    models = hardware_profile.discover_models(models_dir=tmp_path)
    assert len(models) == 1
    from_discover = models[0]["size_gb"]

    from_moe_offload = model_file.stat().st_size / (1024 ** 3)

    assert from_discover == from_moe_offload == 2.0


def test_discover_models_no_longer_reports_decimal_gb():
    """A file just over 19 GiB previously reported as ~21GB (decimal); it must now
    report as ~19GB (binary), matching what the loader actually measures.
    """
    from pathlib import Path
    import math

    size_bytes = int(19.71 * 1024 ** 3)
    decimal_gb = size_bytes / 1e9
    binary_gib = size_bytes / (1024 ** 3)

    assert not math.isclose(decimal_gb, binary_gib, rel_tol=0.01), (
        "sanity check: decimal GB and binary GiB must actually differ for this fixture"
    )
    # The bug: discover_models() used to compute decimal_gb here; it must now compute
    # binary_gib, matching moe_offload.py.
    assert round(binary_gib, 2) == 19.71
