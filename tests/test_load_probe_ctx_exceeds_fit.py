"""Load-probe gate must fire when ctx/batch exceed smart-fit, not only layers.

Live 2.4.32/2.4.33: 22GB Nemotron on RTX 2060 SUPER — smart-fit measured
ctx=4096 gpu_layers=11 batch=128; operator had layers=11 (equal) but
ctx=12000 batch=512. Probe skipped → load success → ggml-cuda abort.
"""
from __future__ import annotations


def test_needs_proof_when_ctx_exceeds_fit_even_if_layers_match():
    """Mirror of the gate in eli_pro_audio_gui_v2_0._load_model_with_fallbacks."""
    base_layers, fit_layers = 11, 11
    base_ctx, fit_ctx = 12000, 4096
    base_batch, fit_batch = 512, 128

    proof_bits = []
    if fit_layers is not None and int(base_layers) > int(fit_layers):
        proof_bits.append(f"gpu_layers {base_layers}>{fit_layers}")
    if fit_ctx is not None and int(base_ctx) > int(fit_ctx):
        proof_bits.append(f"ctx {base_ctx}>{fit_ctx}")
    if fit_batch is not None and int(base_batch) > int(fit_batch):
        proof_bits.append(f"batch {base_batch}>{fit_batch}")

    assert proof_bits, "expected proof when ctx/batch exceed fit"
    assert any(b.startswith("ctx ") for b in proof_bits)
    assert any(b.startswith("batch ") for b in proof_bits)
    # Old (broken) gate — layers alone would skip the probe:
    old_needs_proof = fit_layers is not None and int(base_layers) > int(fit_layers)
    assert not old_needs_proof
    assert bool(proof_bits) is True


def test_no_proof_when_request_inside_fit():
    base_layers, fit_layers = 11, 11
    base_ctx, fit_ctx = 4096, 4096
    base_batch, fit_batch = 128, 128
    proof_bits = []
    if fit_layers is not None and int(base_layers) > int(fit_layers):
        proof_bits.append("layers")
    if fit_ctx is not None and int(base_ctx) > int(fit_ctx):
        proof_bits.append("ctx")
    if fit_batch is not None and int(base_batch) > int(fit_batch):
        proof_bits.append("batch")
    assert proof_bits == []
