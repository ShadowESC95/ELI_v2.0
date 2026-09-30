"""The GUI's own load ladder logged a fallback the load never used.

Live from a real session on a 6667MB-free card with a 35B MoE model
(requested 40 layers):

    [GUI][LOAD] smart-fit measured 8 GPU layers as the fit for 6667MB free VRAM
    [GUI][LOAD] your settings exceed the measured fit (gpu_layers 40>8) — verifying...
    [LOAD_PROBE] timed out after 109s — treating as unproven
    [GUI][LOAD] attempt 2/12: smart-fit (ctx=12000 gpu_layers=8 batch=256)
    [GUI][LOAD] selected=smart-fit (ctx=12000 gpu_layers=41 batch=256)

Two different layer counts (8, then 41) for the rung the log calls "smart-fit". The 8 came from
sizing layers off the model's full file size on disk, which is wrong once expert offload is
active: only non-expert tensors go to GPU, so a much smaller "resident" size (moe_offload.plan()
already computes this, as resident_gb) is what actually governs the real VRAM fit.

An interim fix within the same session made the smart-fit rung's candidate layer count match
what an unconditional build-time override forced anyway — stopping the log from contradicting
itself, but not verifying the override was actually safe (see git history for that commit's
`_sf_layers = int(_moe_gui["layers"])` patch — now removed).

The real fix: `_sf_fit` (`unified_fit_config`) is now itself MoE-aware via a `moe_resident_gb`
kwarg, returning a genuinely VRAM-verified layer count (partial, or the `99` "all layers"
sentinel this codebase already uses everywhere for a full fit) — so there is nothing left to
correct after the call, and nothing left to force at Llama()-build time, since every candidate
the ladder produces (the operator's own request, or this fit's result) is already trustworthy.
"""
import pathlib

GUI = pathlib.Path(__file__).resolve().parents[1] / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py"


def _smart_fit_block():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("_sf_ctx, _sf_layers, _sf_batch = _sf_fit(")
    j = src.index('_add_attempt("smart-fit", _sf_ctx, _sf_layers, _sf_batch)', i)
    return src[i:j]


def test_moe_resident_gb_is_threaded_into_the_fit_call():
    block = _smart_fit_block()
    assert 'moe_resident_gb=(_moe_gui["resident_gb"] if _moe_gui else None)' in block


def test_no_post_hoc_layer_correction_remains():
    """The interim patch that rewrote _sf_layers AFTER the fit is gone — the fit itself is now
    correct, so a second correction on top of it would silently re-force full layers over an
    already-correct (possibly partial) answer."""
    block = _smart_fit_block()
    assert '_sf_layers = int(_moe_gui["layers"])' not in block


def test_no_build_time_override_remains():
    """The unconditional 'any candidate with layers>0 gets forced to the full MoE count' override
    is gone — every candidate reaching the Llama() build already carries a trustworthy number."""
    src = GUI.read_text(encoding="utf-8")
    assert 'int(_moe_gui["layers"]) + 1 if _moe_gui["layers"] else 999' not in src
    i = src.index('_cand_gpu_layers = int(_cand["n_gpu_layers"])')
    j = src.index("llama_kwargs: Dict[str, Any] = dict(", i)
    window = src[i:j]
    assert "_moe_gui" not in window


def test_the_post_fit_report_states_the_real_measured_outcome():
    """Once the fit has run, the GUI reports what was actually measured — fitted/total layers,
    resident_gb, experts_gb — not an assumed "will raise this to all N layers" outcome."""
    block = _smart_fit_block()
    assert "MoE fit:" in block
    assert "_moe_gui['resident_gb']" in block or '_moe_gui["resident_gb"]' in block
    assert "_moe_gui['experts_gb']" in block or '_moe_gui["experts_gb"]' in block
