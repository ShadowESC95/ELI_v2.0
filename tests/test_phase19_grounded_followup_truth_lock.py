from __future__ import annotations

from eli.kernel.engine import _eli_phase19_rebind_grounded_followup
from eli.runtime.control_contracts import output_violates_evidence
from eli.cognition.output_governor import validate_against_evidence


class _DummyEngine:
    _last_request_meta = {
        "request_id": "req-audit-1",
        "route_action": "RUNTIME_AUDIT",
        "result_action": "RUNTIME_AUDIT",
        "action": "RUNTIME_AUDIT",
        "evidence_used": True,
        "grounded": True,
    }


def _chat_intent():
    return {
        "action": "CHAT",
        "args": {"message": "placeholder"},
        "confidence": 0.85,
        "meta": {"matched_by": "chat.long_question_guard"},
    }


def test_phase19_rebinds_exact_line_followup_to_prior_grounded_action():
    result = _eli_phase19_rebind_grounded_followup(
        _DummyEngine(),
        "what are the exact lines of the duplicates, can you fix it?",
        _chat_intent(),
    )
    assert result["action"] == "RUNTIME_AUDIT"
    assert result["meta"]["grounded_followup"] is True
    assert result["meta"]["allow_chat_without_evidence"] is False
    assert result["meta"]["task_family"] == "grounded_audit"


def test_phase19_rebinds_challenge_followup_to_prior_grounded_action():
    result = _eli_phase19_rebind_grounded_followup(
        _DummyEngine(),
        "are you lieing to me?",
        _chat_intent(),
    )
    assert result["action"] == "RUNTIME_AUDIT"
    assert result["meta"]["grounded_followup_kind"] == "challenge"


def test_phase19_leaves_unrelated_chat_as_chat():
    result = _eli_phase19_rebind_grounded_followup(
        _DummyEngine(),
        "how was your evening?",
        _chat_intent(),
    )
    assert result["action"] == "CHAT"


def test_phase19_control_truth_lock_rejects_wrong_line_numbers():
    evidence = "FAIL router_enhanced.py\n  - line 4422 route also defined at lines [631, 4422]"
    output = "The duplicates are at lines 42 and 56."
    assert output_violates_evidence(output, evidence) is True


def test_phase19_control_truth_lock_allows_evidenced_line_numbers():
    evidence = "FAIL router_enhanced.py\n  - line 4422 route also defined at lines [631, 4422]"
    output = "The duplicate route definitions are reported at lines 631 and 4422."
    assert output_violates_evidence(output, evidence) is False


def test_phase19_control_truth_lock_rejects_fake_edit_claims():
    evidence = "Runtime audit only. No code edit action occurred."
    output = "I'll delete the duplicate now."
    assert output_violates_evidence(output, evidence) is True


def test_phase19_output_governor_rejects_wrong_line_numbers():
    evidence = "FAIL router_enhanced.py\n  - line 4422 route also defined at lines [631, 4422]"
    verdict = validate_against_evidence(
        "The duplicates are at lines 42 and 56.",
        evidence,
        mode="strip_silent",
    )
    assert verdict["unsafe"] is True
    assert any(v["kind"] == "fabricated_line_reference" for v in verdict["violations"])


def test_phase19_output_governor_rejects_fake_mutation_claims():
    verdict = validate_against_evidence(
        "I'll delete the duplicate now.",
        "Runtime audit evidence only; no mutation executor action occurred.",
        mode="strip_silent",
    )
    assert verdict["unsafe"] is True
    assert any(v["kind"] == "unsupported_mutation_claim" for v in verdict["violations"])
