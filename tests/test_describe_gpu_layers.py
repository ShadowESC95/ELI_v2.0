"""Regression: raw gpu_layers values (notably llama.cpp's 99 "offload
everything" sentinel) were printed verbatim in multiple hardware-tuning panel
and startup-dialog strings, sitting right next to the real, much lower layer
count actually used for a MoE-fit model — producing exactly the "all kinds
of conflicting numbers" confusion a user reported live (99 in one line, 40 in
the next, no indication 99 wasn't a literal count). describe_gpu_layers() is
the single translator every user-facing gpu_layers string must go through.
"""
from __future__ import annotations

from eli.core import hardware_profile as hp


def test_describe_gpu_layers_translates_the_sentinel():
    """The raw digit itself must never reach the user — the whole point of
    this function is that 99 is not a real layer count, so printing "99"
    anywhere, even annotated, still reads as a number competing with the
    real one shown elsewhere in the same panel."""
    assert hp.describe_gpu_layers(99) == "all layers"
    assert "99" not in hp.describe_gpu_layers(99)


def test_describe_gpu_layers_translates_anything_at_or_above_99():
    assert hp.describe_gpu_layers(120) == "all layers"
    assert "120" not in hp.describe_gpu_layers(120)


def test_describe_gpu_layers_uses_total_layers_when_known():
    assert hp.describe_gpu_layers(99, total_layers=40) == "all 40 layers"
    assert hp.describe_gpu_layers(40, total_layers=40) == "all 40 layers"


def test_describe_gpu_layers_passes_through_a_real_partial_count():
    assert hp.describe_gpu_layers(40) == "40"
    assert hp.describe_gpu_layers(7) == "7"


def test_describe_gpu_layers_handles_none():
    assert hp.describe_gpu_layers(None) == "unset"


def test_describe_gpu_layers_zero_is_not_treated_as_sentinel():
    assert hp.describe_gpu_layers(0) == "0"
