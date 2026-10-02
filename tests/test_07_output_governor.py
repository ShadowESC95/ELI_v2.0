import pytest
from eli.cognition.output_governor import validate_against_evidence, govern_output

def test_validate_against_evidence_ok():
    r = validate_against_evidence("The file /home/user/test.py exists.", "The file /home/user/test.py exists.")
    assert r["ok"] is True

def test_validate_against_evidence_fabricated_path():
    r = validate_against_evidence("I found /home/user/secret.txt", "No files mentioned.")
    assert r["ok"] is False
    assert "fabricated_path" in [v["kind"] for v in r["violations"]]

def test_validate_against_evidence_fabricated_runtime():
    # Use colon format to guarantee detection
    evidence = "context size: 4096"
    output = "context size: 16384"
    r = validate_against_evidence(output, evidence)
    assert r["ok"] is False
    assert "fabricated_runtime_value" in [v["kind"] for v in r["violations"]]

def test_validate_against_evidence_scaffolding():
    r = validate_against_evidence("1. Approach A\nCore Idea: ...\nFeasibility: 8/10", "")
    assert r["ok"] is False
    assert "scaffolding_leakage" in [v["kind"] for v in r["violations"]]

def test_validate_against_evidence_fabricated_reliability_percentage():
    """Live bug (2026-10-02): a META_DIAGNOSTIC answer stated '~51% success rate'
    for MEDIA_CONTROL. Nothing in the evidence packet computed that number —
    action_reliability() is never called from _meta_diagnostic_report. This is
    the figure check this validator already has; it just was not wired into
    the control-synthesis path that produced that answer (see engine.py's
    comment at the _validate_ctrl_evidence call site for the fix)."""
    ev = "route current_action META_DIAGNOSTIC agents_used orchestrator knowledge_graph"
    out = "My MEDIA_CONTROL agent has been unreliable recently (~51% success rate across recent runs)."
    r = validate_against_evidence(out, ev)
    assert r["ok"] is False
    assert "fabricated_figure" in [v["kind"] for v in r["violations"]]

def test_govern_output_cleans_ai_prefix():
    assert "As an AI assistant" not in govern_output("As an AI assistant, I will help you.")

def test_govern_output_strips_hr_phrases():
    assert "I'd be happy" not in govern_output("I'd be happy to help.").lower()
