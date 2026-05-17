from __future__ import annotations

from pathlib import Path

from eli.kernel.engine import CognitiveEngine

RUNTIME_QUERY = (
    "Who are you and what are you actually running on right now — "
    "model, context size, GPU layers, everything."
)


def test_bad_top_direct_guard_is_absent():
    src = Path("eli/kernel/engine.py").read_text(encoding="utf-8", errors="replace")
    assert "ELI_ENGINE_TOP_RUNTIME_STATUS_DIRECT_V10" not in src


def test_v19_middleware_is_quick_direct_nonquick_synthesize():
    """V8 inline middleware was removed in Phase 2b and replaced by the
    V19 RUNTIME_STATUS_NONQUICK_FULL_PIPELINE inline middleware. The new
    surface contract: Quick may return deterministic evidence; Non-Quick
    routes through executor evidence + LLM synthesis + validation."""
    src = Path("eli/kernel/engine.py").read_text(encoding="utf-8", errors="replace")
    start = src.index("ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1 ===")
    end = src.index("END ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1")
    block = src[start:end]

    # Quick branch returns deterministic canonical evidence directly.
    assert "_mw_rs_is_quick" in block
    assert "_mw_rs_quick_direct" in block
    # Non-Quick branch gathers evidence then synthesizes via LLM.
    assert "_mw_rs_call_runtime_status" in block
    assert "_mw_rs_synthesize" in block

    # V8 deletion sentinel proves the dead middleware was removed.
    assert "ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8_DELETED_PHASE2B" in src


def test_nonquick_runtime_status_not_self_report_and_not_direct_surface():
    eng = CognitiveEngine()
    out = eng.process(RUNTIME_QUERY, reasoning_mode="constitutional_ai")

    assert isinstance(out, dict)
    assert out.get("action") == "RUNTIME_STATUS"
    assert out.get("action") != "SELF_REPORT"
    assert out.get("evidence_source") != "runtime_status_grounded_dynamic_evidence_v8"
