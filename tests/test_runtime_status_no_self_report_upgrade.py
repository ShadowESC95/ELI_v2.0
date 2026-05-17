from __future__ import annotations

from eli.kernel.engine import CognitiveEngine

RUNTIME_QUERY = (
    "Who are you and what are you actually running on right now — "
    "model, context size, GPU layers, everything."
)


def _assert_runtime_status_quick(out):
    """Quick mode returns deterministic evidence via canonical contract."""
    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert out.get("action") == "RUNTIME_STATUS"
    assert out.get("evidence_source") == "runtime_status_quick_canonical_contract"
    text = str(out.get("content") or out.get("response") or "")
    assert text.strip()
    assert "model" in text.lower()
    assert "context" in text.lower() or "ctx" in text.lower()
    assert "gpu" in text.lower()


def _assert_runtime_status_nonquick(out):
    """Non-Quick must route through V19 synthesis pipeline, never the V8 surface.
    In test mode (no GGUF) the pipeline correctly fails closed; in production
    it returns a synthesized answer mentioning runtime terms."""
    assert isinstance(out, dict)
    assert out.get("action") == "RUNTIME_STATUS"
    assert out.get("action") != "SELF_REPORT"
    assert out.get("evidence_source") != "runtime_status_grounded_dynamic_evidence_v8"
    assert str(out.get("source") or "").startswith("runtime_status_nonquick_full_pipeline")
    text = str(out.get("content") or out.get("response") or "")
    assert text.strip()
    # If synthesis succeeded (production), require runtime terms.
    if (out.get("report") or {}).get("synthesis_validated") is True:
        low = text.lower()
        assert "model" in low
        assert "context" in low or "ctx" in low
        assert "gpu" in low


def test_runtime_status_chain_of_thought_does_not_upgrade_to_self_report():
    eng = CognitiveEngine()
    _assert_runtime_status_nonquick(eng.process(RUNTIME_QUERY, reasoning_mode="chain_of_thought"))


def test_runtime_status_constitutional_does_not_upgrade_to_self_report():
    eng = CognitiveEngine()
    _assert_runtime_status_nonquick(eng.process(RUNTIME_QUERY, reasoning_mode="constitutional_ai"))


def test_runtime_status_self_consistency_does_not_upgrade_to_self_report():
    eng = CognitiveEngine()
    _assert_runtime_status_nonquick(eng.process(RUNTIME_QUERY, reasoning_mode="self_consistency"))


def test_runtime_status_quick_still_returns_runtime_status():
    eng = CognitiveEngine()
    _assert_runtime_status_quick(eng.process(RUNTIME_QUERY, reasoning_mode="quick"))
