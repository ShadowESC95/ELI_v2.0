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

def test_govern_output_cleans_ai_prefix():
    assert "As an AI assistant" not in govern_output("As an AI assistant, I will help you.")

def test_govern_output_strips_hr_phrases():
    assert "I'd be happy" not in govern_output("I'd be happy to help.").lower()
