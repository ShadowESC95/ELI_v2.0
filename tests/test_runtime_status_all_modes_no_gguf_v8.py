from __future__ import annotations

from eli.kernel.engine import CognitiveEngine

RUNTIME_QUERY = (
    "Who are you and what are you actually running on right now — "
    "model, context size, GPU layers, everything."
)


def test_runtime_status_modes_keep_action_boundary():
    """All modes preserve action=RUNTIME_STATUS and emit non-empty text.
    Per V19 spec, Quick may return deterministic evidence (ok=True) while
    Non-Quick must synthesize via LLM — under test mode where no GGUF is
    loaded the Non-Quick path correctly fails closed (ok=False, but still
    a structured RUNTIME_STATUS dict with non-empty content)."""
    eng = CognitiveEngine()

    for mode in ("quick", "chain_of_thought", "self_consistency", "tree_of_thoughts", "constitutional_ai"):
        out = eng.process(RUNTIME_QUERY, reasoning_mode=mode)

        assert isinstance(out, dict), mode
        assert out.get("action") == "RUNTIME_STATUS", mode

        text = str(out.get("content") or out.get("response") or "")
        assert text.strip(), mode

        if mode == "quick":
            assert out.get("ok") is True, mode


def test_only_quick_uses_direct_evidence_nonquick_uses_v19_pipeline():
    """Quick uses the canonical runtime-status contract surface; Non-Quick
    routes through the V19 full-pipeline synthesis middleware (per spec,
    Non-Quick must never return raw evidence packets verbatim)."""
    eng = CognitiveEngine()

    quick = eng.process(RUNTIME_QUERY, reasoning_mode="quick")
    nonquick = eng.process(RUNTIME_QUERY, reasoning_mode="chain_of_thought")

    assert quick.get("evidence_source") == "runtime_status_quick_canonical_contract"
    assert nonquick.get("action") == "RUNTIME_STATUS"
    assert nonquick.get("evidence_source") != "runtime_status_grounded_dynamic_evidence_v8"
    # Non-Quick must take the V19 synthesis path (success or fail-closed).
    assert str(nonquick.get("source") or "").startswith("runtime_status_nonquick_full_pipeline")
