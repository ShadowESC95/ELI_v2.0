"""Live session report (2026-10-02): the status bar said 'gpu=40' for a MoE model where
only ~1.97GB of the 19.71GB file is actually GPU-resident (experts stay in RAM regardless
of layer count) — "why does it say the full 40 GPU layers instead of 8 on GPU, the
remaining is on RAM" from the user directly. 40 is the real, correct layer count (every
layer's small core tensor IS on the GPU), but on its own it reads as "40 of 40 layers'
worth of memory is on the GPU", which is false for MoE. Both the live "Model ready"
status line and the Hardware Tuning panel's recommendation summary must state the real
GPU-resident GB alongside the layer count, not the layer count alone.

Qt-coupled GUI module, not directly executable in CI — verified at the source-text level,
matching this file's established pattern (see test_moe_gpu_layer_print_matches_what_loads.py).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py"


def test_model_ready_status_carries_a_moe_gb_note():
    src = GUI.read_text(encoding="utf-8")
    i = src.index('f"gpu={_gpu_disp}{_moe_note} "')
    around = src[max(0, i - 900):i + 100]
    assert "moe_offload" in around
    assert "plan_for_load" in around
    assert "resident_gb" in around
    assert "experts_gb" in around


def test_model_ready_note_is_blank_when_not_moe():
    """A dict-returning plan is the only thing that should add text — None must not
    crash the f-string or silently print a stale note from a prior model."""
    src = GUI.read_text(encoding="utf-8")
    i = src.index('f"gpu={_gpu_disp}{_moe_note} "')
    around = src[max(0, i - 900):i + 100]
    assert '_moe_note = ""' in around
    assert "if _moe_plan:" in around


def test_hardware_tuning_recommendation_summary_carries_a_moe_gb_note():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("_moe_note_rec = (")
    around = src[max(0, i - 400):i + 700]
    assert "moe_offload" in around
    assert "plan_for_load" in around
    assert "resident_gb" in around
    assert "experts_gb" in around
    assert "HW Profile (recommended)" in around


def test_neither_moe_lookup_can_crash_the_load_or_recommendation_path():
    """plan_for_load() does a live GPU/RAM probe — it must never be allowed to take
    down model loading or the recommendation panel if that probe fails."""
    src = GUI.read_text(encoding="utf-8")
    for anchor in ('f"gpu={_gpu_disp}{_moe_note} "', "_moe_note_rec = ("):
        i = src.index(anchor)
        j = src.rindex("plan_for_load", 0, i)
        block = src[j:j + 150]
        assert "except Exception" in block
