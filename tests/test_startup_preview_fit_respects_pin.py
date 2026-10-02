"""Live session report (2026-10-02): the Hardware Tuning preview line showed
"gpu=all layers" right next to the real load's "gpu=10, 2.0GB actually on GPU"
— looked like a contradiction. gpu_layers=10 was the user's own prior pin
(user_gpu_layers is a hard ceiling in smart_fit_config, by design), but the
preview's unified_fit_config call never passed it, so it always showed the
uncapped fit.

Fixed: the preview now passes the resolved pin as user_gpu_layers (same
function the real loader uses to resolve it), and appends a note when the pin
is below what would otherwise fit.

Qt-coupled GUI module, not directly executable in CI — verified at the
source-text level (established pattern, see
test_moe_gpu_layer_print_matches_what_loads.py).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STARTUP = ROOT / "eli/gui/panels/startup.py"


def _preview_fit_block() -> str:
    src = STARTUP.read_text(encoding="utf-8")
    i = src.index("_fit_line = \"\"")
    j = src.index("if not _hw.has_gpu:", i)
    return src[i:j]


def test_preview_looks_up_the_same_pin_the_real_loader_uses():
    block = _preview_fit_block()
    assert "from eli.core.runtime_settings import pinned_gpu_layers_for_model" in block
    assert "pinned_gpu_layers_for_model(" in block


def test_capped_fit_call_passes_the_pin():
    block = _preview_fit_block()
    i = block.index("_fc, _fl, _fb = unified_fit_config(")
    j = block.index(")", i)
    assert "user_gpu_layers=_pin" in block[i:j]


def test_uncapped_fallback_call_passes_none_to_show_true_headroom():
    block = _preview_fit_block()
    i = block.index("_uc_fc, _uc_fl, _uc_fb = unified_fit_config(")
    j = block.index(")", i)
    assert "user_gpu_layers=None" in block[i:j]


def test_note_only_appears_when_pin_is_below_the_uncapped_fit():
    block = _preview_fit_block()
    i = block.index("if _uc_fl > _fl:")
    j = block.index("except Exception", i)
    assert "pinned to" in block[i:j]
    assert "would fit" in block[i:j]
