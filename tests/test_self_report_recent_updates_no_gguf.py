from __future__ import annotations

from eli.kernel.engine import CognitiveEngine


PROMPT = "What updates and checks have you performed as of late?"


def _assert_self_report_result(out, *, quick: bool):
    assert isinstance(out, dict)
    assert out.get("action") == "SELF_REPORT"
    assert isinstance(out.get("content"), str)
    assert out.get("content")

    report = out.get("report") or {}
    assert report.get("gguf_used") in {False, None}
    if report.get("process_override") is not None:
        assert report.get("process_override") in {
            "self_report_recent_updates_primary_middleware_v4",
            "self_report_recent_updates_primary_middleware_v5",
        }

    if quick:
        assert out.get("ok") is True
        assert "Grounded ELI self-report" in out.get("content")
        assert out.get("evidence_source") in {
            "self_report_recent_updates_quick_direct_v4",
            "self_report_recent_updates_quick_direct_v5",
        }
        assert report.get("quick_direct_allowed") is True
    else:
        assert out.get("evidence_source") in {
            "self_report_recent_updates_nonquick_grounded_no_gguf_v4",
            "self_report_recent_updates_git_runtime",
            "self_report_recent_updates_grounded_no_gguf_v5",
        } or str(out.get("evidence_source") or "").startswith("self_report_recent_updates_")
        assert report.get("quick_direct_allowed") is False
        # V4 succeeded deterministically without GGUF. V5 fails closed if
        # non-Quick synthesis cannot be completed.
        if out.get("ok") is True:
            assert "Grounded ELI self-report" in out.get("content")
            assert report.get("synthesis_validated") is True
        else:
            assert report.get("synthesis_validated") is False
            assert report.get("direct_telemetry_returned") is False


def test_self_report_recent_updates_quick_no_gguf():
    eng = CognitiveEngine()
    out = eng.process(PROMPT, reasoning_mode="quick")
    _assert_self_report_result(out, quick=True)


def test_self_report_recent_updates_nonquick_no_gguf():
    eng = CognitiveEngine()
    for mode in ("chain_of_thought", "self_consistency"):
        out = eng.process(PROMPT, reasoning_mode=mode)
        _assert_self_report_result(out, quick=False)
