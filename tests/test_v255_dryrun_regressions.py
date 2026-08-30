"""Regression tests from v2.3.55 source-install dry-run."""
from __future__ import annotations

from eli.execution.router_enhanced import route
from eli.runtime.code_examiner import resolve_targets
from eli.runtime.deterministic_introspection import _explain_last_response, _last_trace


def test_memory_architecture_not_personal_memory_deep_explain():
    q = (
        "Explain exactly how your memory system works internally — "
        "which files, which DB tables, which functions."
    )
    out = route(q)
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out


def test_personal_memory_still_routes_deep_explain():
    q = "Explain my memory internally — what personal things do you store about me?"
    out = route(q)
    assert out["action"] in {"PERSONAL_MEMORY_DEEP_EXPLAIN", "PERSONAL_MEMORY_SUMMARY"}, out


def test_full_profile_dump_dont_summarise():
    from eli.execution.router_enhanced import _eli_is_full_profile_dump

    low = "what do you know about me from memory? give me everything, don't summarise."
    assert _eli_is_full_profile_dump(low)


def test_gui_file_audit_scopes_single_file():
    paths = resolve_targets("Audit your GUI file and tell me if anything is wired incorrectly.")
    assert len(paths) == 1
    assert paths[0].name == "eli_pro_audio_gui_v2_0.py"


def test_explain_last_response_reads_last_request_meta():
    class _Eng:
        _last_request_meta = {
            "response_text": "I am ELI, running Qwen locally.",
            "agents_used": ["orchestrator", "system"],
            "aggregated_confidence": 0.92,
            "confidence": 0.92,
        }

    text = _explain_last_response(_Eng())
    assert "I am ELI" in text
    assert "orchestrator" in text
    assert "0.92" in text or "92" in text


def test_last_trace_prefers_last_request_meta():
    class _Eng:
        _last_trace = {"stale": True}
        _last_request_meta = {"response_text": "fresh", "confidence": 0.8}

    assert _last_trace(_Eng()).get("response_text") == "fresh"
