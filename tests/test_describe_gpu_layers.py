"""Regression: raw gpu_layers values (notably the "offload everything" value: llama.cpp's -1, written
99 by earlier releases) were printed verbatim in multiple hardware-tuning panel
and startup-dialog strings, sitting right next to the real, much lower layer
count actually used for a MoE-fit model — producing exactly the "all kinds
of conflicting numbers" confusion a user reported live (99 in one line, 40 in
the next, no indication 99 wasn't a literal count). describe_gpu_layers() is
the single translator every user-facing gpu_layers string must go through.
"""
from __future__ import annotations

from eli.core import hardware_profile as hp


def test_describe_gpu_layers_translates_every_layer():
    """-1 is not a layer count; printing it reads as a number competing with the real one."""
    assert hp.describe_gpu_layers(-1) == "all layers"
    assert "-1" not in hp.describe_gpu_layers(-1)


def test_a_count_is_a_count_without_the_model_size():
    """120 can be a real count on a model of more layers: it is shown as it is."""
    assert hp.describe_gpu_layers(120) == "120"


def test_describe_gpu_layers_uses_total_layers_when_known():
    assert hp.describe_gpu_layers(-1, total_layers=40) == "all 40 layers"
    assert hp.describe_gpu_layers(99, total_layers=40) == "all 40 layers"
    assert hp.describe_gpu_layers(40, total_layers=40) == "all 40 layers"


def test_describe_gpu_layers_passes_through_a_real_partial_count():
    assert hp.describe_gpu_layers(40) == "40"
    assert hp.describe_gpu_layers(7) == "7"


def test_describe_gpu_layers_handles_none():
    assert hp.describe_gpu_layers(None) == "unset"


def test_describe_gpu_layers_zero_is_not_treated_as_sentinel():
    assert hp.describe_gpu_layers(0) == "0"
