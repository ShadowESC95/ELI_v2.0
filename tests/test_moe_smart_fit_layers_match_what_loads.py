"""The GUI's own load ladder logged a fallback the load never used.

Live from a real session on a 6667MB-free card with a 35B MoE model
(requested 40 layers):

    [GUI][LOAD] smart-fit measured 8 GPU layers as the fit for 6667MB free VRAM
    [GUI][LOAD] your settings exceed the measured fit (gpu_layers 40>8) — verifying...
    [LOAD_PROBE] timed out after 109s — treating as unproven
    [GUI][LOAD] attempt 2/12: smart-fit (ctx=12000 gpu_layers=8 batch=256)
    [GUI][LOAD] selected=smart-fit (ctx=12000 gpu_layers=41 batch=256)

Two different layer counts (8, then 41) for the rung the log calls "smart-fit".
The 8 came from `unified_fit_config()`, which sizes layers off the model's
full file size on disk. That is the wrong number once expert offload is
active: only non-expert tensors go to the GPU, so layer COUNT is not what
buys back VRAM for a MoE model, and the Llama() build a few hundred lines
below unconditionally forces every candidate's layer count back up to the
MoE plan's full count. The 8 was never going to be used — it just cost a
109s probe timeout on the "gpu_layers 40>8" comparison it produced, and then
lied about what rung actually got selected.

`eli/cognition/gguf_inference.py` (the canonical loader) and
`hardware_profile.recommend()` both decide the MoE layer count BEFORE
computing/reporting anything derived from it. This GUI file has its own
separate, duplicated load ladder that didn't get the same ordering.
"""
import pathlib

GUI = pathlib.Path(__file__).resolve().parents[1] / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py"


def _smart_fit_block():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("_sf_ctx, _sf_layers, _sf_batch = _sf_fit(")
    j = src.index('_add_attempt("smart-fit", _sf_ctx, _sf_layers, _sf_batch)', i)
    return src[i:j]


def test_moe_correction_runs_before_the_fit_is_logged():
    block = _smart_fit_block()
    correction = block.index('_sf_layers = int(_moe_gui["layers"])')
    first_log = block.index('log.debug(\n                            f"[GUI][LOAD] smart-fit (post-init')
    assert correction < first_log, (
        "the MoE layer correction must run before the fit is logged, or the "
        "log keeps reporting a fallback that will never be used"
    )


def test_moe_correction_runs_before_the_needs_proof_comparison():
    src = GUI.read_text(encoding="utf-8")
    block = _smart_fit_block()
    correction_offset = src.index(block) + block.index('_sf_layers = int(_moe_gui["layers"])')
    proof_bits = src.index('_proof_bits.append(\n                    f"gpu_layers')
    assert correction_offset < proof_bits, (
        "the needs-proof check compares _base_layers against the naive "
        "pre-MoE fit unless the correction runs first — that is what "
        "produced the spurious 'gpu_layers 40>8' 109s probe timeout"
    )


def test_moe_correction_only_fires_when_smart_fit_kept_any_gpu_layers():
    """Mirrors the later Llama()-build override's own guard (`_cand_gpu_layers > 0`):
    a smart-fit result of 0 layers means even the reduced non-expert tensors
    didn't fit, and must stay a real CPU fallback, not get forced back to
    every layer."""
    block = _smart_fit_block()
    assert "if _moe_gui and _sf_layers > 0:" in block


def test_moe_correction_matches_the_build_time_override():
    """The value written here must be the pre-`+1` layer count the later
    override applies, so the two agree instead of drifting into a second
    pair of mismatched numbers."""
    src = GUI.read_text(encoding="utf-8")
    assert 'int(_moe_gui["layers"]) + 1 if _moe_gui["layers"] else 999' in src
    block = _smart_fit_block()
    assert '_sf_layers = int(_moe_gui["layers"])' in block
