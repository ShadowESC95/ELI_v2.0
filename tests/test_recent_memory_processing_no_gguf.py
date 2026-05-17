from __future__ import annotations

from eli.kernel.engine import CognitiveEngine


PROMPT = "What memories have you been processing lately?"


def _assert_recent_memory_result(out, *, quick: bool):
    assert isinstance(out, dict)
    assert out.get("action") == "MEMORY_STATUS"
    assert isinstance(out.get("content"), str)
    assert out.get("content")

    report = out.get("report") or {}
    assert report.get("gguf_used") in {False, None}
    if report.get("process_override") is not None:
        assert report.get("process_override") in {
            "recent_memory_processing_primary_middleware_v4",
            "recent_memory_processing_primary_middleware_v5",
        }

    if quick:
        assert out.get("ok") is True
        assert out.get("evidence_source") in {
            "recent_memory_processing_quick_direct_clean_v3",
            "recent_memory_processing_quick_direct_clean_v5",
        }
        assert report.get("quick_direct_allowed") is True
    else:
        assert out.get("evidence_source") in {
            "recent_memory_processing_nonquick_grounded_no_gguf_v4",
            "recent_memory_processing_sqlite_clean_v2",
            "recent_memory_processing_grounded_no_gguf_v5",
        } or str(out.get("evidence_source") or "").startswith("recent_memory_processing_")
        assert report.get("quick_direct_allowed") is False
        # V4 succeeded deterministically without GGUF. V5 fails closed if
        # non-Quick synthesis cannot be completed.
        if out.get("ok") is True:
            assert report.get("synthesis_validated") is True
        else:
            assert report.get("synthesis_validated") is False
            assert report.get("direct_telemetry_returned") is False


def test_recent_memory_processing_quick_no_gguf():
    eng = CognitiveEngine()
    out = eng.process(PROMPT, reasoning_mode="quick")
    _assert_recent_memory_result(out, quick=True)


def test_recent_memory_processing_nonquick_no_gguf():
    eng = CognitiveEngine()
    for mode in ("chain_of_thought", "self_consistency"):
        out = eng.process(PROMPT, reasoning_mode=mode)
        _assert_recent_memory_result(out, quick=False)
