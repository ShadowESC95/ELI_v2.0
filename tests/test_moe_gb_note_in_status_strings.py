"""Live session report (2026-10-02): the status bar said 'gpu=40' for a MoE model where only
~1.97GB of the 19.71GB file was GPU-resident — "why does it say the full 40 GPU layers instead of 8
on GPU, the remaining is on RAM". A layer count alone reads as "all of the model is on the GPU",
which is false when experts stay in RAM. The ready line and the Hardware Tuning summary say where
the experts are and what each card holds: both come from the load plan (eli/core/load_plan.py).
"""
from pathlib import Path

from eli.core.load_plan import Device, Plan

GUI = Path(__file__).resolve().parents[1] / "eli/gui/eli_pro_audio_gui_v2_0.py"


def _moe_plan(**kw):
    base = dict(model_path="qwen.gguf", n_ctx=60000, n_gpu_layers=41, n_batch=128, n_threads=6,
                cache_type_k="q8_0", cache_type_v="q8_0", flash_attn=True, split_mode=1, main_gpu=0,
                tensor_split=[18, 23], experts_in_ram=19, blocks=40,
                devices=[Device(0, "CUDA0", "RTX 2060 SUPER", 6589, 7783, False),
                         Device(1, "CUDA1", "RTX 2060 SUPER", 7689, 7786, False)],
                use_mb={0: 959.0, 1: 956.0}, measured=True)
    base.update(kw)
    return Plan(**base)


def test_the_plan_says_where_the_experts_are_and_what_each_card_holds():
    text = _moe_plan().describe()
    assert "40/40 layers on GPU + output" in text
    assert "experts of the first 19 layers in RAM" in text
    assert "CUDA0 RTX 2060 SUPER: uses 959 of 6589 MB free" in text and "CUDA1" in text


def test_a_dense_plan_mentions_no_experts():
    assert "experts" not in _moe_plan(experts_in_ram=None).describe()


def test_the_ready_line_and_the_tuning_summary_carry_the_plan():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def status_line(self)")
    assert "experts_in_ram" in src[i:i + 900]
    j = src.index('summary += f"  |  loaded: {_loaded_plan}"')
    assert '"load_plan"' in src[j - 400:j]
