from __future__ import annotations

from eli.kernel.engine import CognitiveEngine

RUNTIME_QUERY = (
    "Who are you and what are you actually running on right now — "
    "model, context size, GPU layers, everything."
)


def _visible(out):
    if isinstance(out, dict):
        return str(out.get("content") or out.get("response") or "")
    return str(out or "")


def test_runtime_status_quick_may_use_direct_dynamic_evidence():
    """Quick mode returns deterministic live runtime evidence via the
    canonical contract surface (Phase 2a moved this off the V8 marker)."""
    eng = CognitiveEngine()
    out = eng.process(RUNTIME_QUERY, reasoning_mode="quick")

    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert out.get("action") == "RUNTIME_STATUS"
    assert out.get("evidence_source") == "runtime_status_quick_canonical_contract"
    # synthesis_validated is None for Quick (no synthesis attempted).
    assert (out.get("synthesis_validated") in (None, False)) or (
        (out.get("report") or {}).get("synthesis_validated") in (None, False)
    )


def test_runtime_status_nonquick_does_not_become_self_report():
    eng = CognitiveEngine()

    for mode in ("chain_of_thought", "self_consistency", "tree_of_thoughts", "constitutional_ai"):
        out = eng.process(RUNTIME_QUERY, reasoning_mode=mode)

        assert isinstance(out, dict), mode
        assert out.get("action") == "RUNTIME_STATUS", mode
        assert out.get("action") != "SELF_REPORT", mode
        assert _visible(out).strip(), mode


def test_runtime_status_nonquick_does_not_use_hard_v8_surface():
    eng = CognitiveEngine()

    for mode in ("chain_of_thought", "self_consistency", "tree_of_thoughts", "constitutional_ai"):
        out = eng.process(RUNTIME_QUERY, reasoning_mode=mode)

        assert isinstance(out, dict), mode
        assert out.get("action") == "RUNTIME_STATUS", mode
        assert out.get("evidence_source") != "runtime_status_grounded_dynamic_evidence_v8", mode
