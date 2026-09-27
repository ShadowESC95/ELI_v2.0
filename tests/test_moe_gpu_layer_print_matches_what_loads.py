"""The startup dialog printed 'GPU-layer load parameter: 7' and, further down the same log,
'selected=smart-fit (ctx=... gpu_layers=41 batch=...)' for the same load — two different numbers
for what looked like the same thing, with no explanation, because the early print used the
pre-MoE layer count. The print now says when MoE expert offload will raise it.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_early_print_explains_a_moe_bump():
    src = (ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    i = src.index("GPU-layer load parameter")
    around = src[max(0, i - 400):i + 200]
    assert "_moe_gui" in around and "will raise this to all" in around
