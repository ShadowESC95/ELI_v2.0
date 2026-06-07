"""Multi-stage grounded document pipeline (eli/runtime/report_pipeline.py).

Deterministic — the inference is a stub `ask`; tests the staging (plan → sections
→ review→revise), the confidence-driven deepen-retry on thin evidence, degenerate
retry, and the kill switch.
"""
from __future__ import annotations

import eli.runtime.report_pipeline as RP


def _staged_ask():
    calls = {"n": 0, "prompts": []}

    def ask(prompt, system=None, max_tokens=1500, temperature=0.4):
        calls["n"] += 1
        calls["prompts"].append((system or "") + " || " + prompt)
        s = (system or "").lower()
        if "planner" in s:
            return "1. Background\n2. Mechanism\n3. Implications"
        if "reviewer" in s:
            return "- section 2 is thin\n- add specifics from the evidence"
        if "revising" in s:
            return ("# Topic\n\n## Background\nGrounded content referencing netguard.\n\n"
                    "## Mechanism\nDetails.\n\n## Implications\nClose.")
        return "## Section\n" + ("Substantive grounded body referencing the evidence. " * 8)

    return ask, calls


def test_pipeline_runs_plan_sections_review():
    ask, calls = _staged_ask()
    r = RP.generate_document("upgrades to ELI", ask=ask, evidence="EVIDENCE: real stuff " * 20,
                             doc_type="document", target_words=900)
    assert r["ok"]
    assert r["sections"] == ["Background", "Mechanism", "Implications"]
    # 1 outline + 3 sections + 1 critique + 1 revise = 6
    assert calls["n"] == 6
    assert r["text"].count("##") >= 3


def test_thin_evidence_triggers_deepen_retry():
    ask, _ = _staged_ask()
    fired = {"v": False}

    def deepen():
        fired["v"] = True
        return ("EVIDENCE: netguard fail-closes at the socket; bus has 14 agents. " * 6,
                ["file_code", "blueprints"])

    r = RP.generate_document("x", ask=ask, evidence="", doc_type="document",
                             target_words=900, deepen_cb=deepen)
    assert r["ok"] and fired["v"]  # thin evidence → deeper tiers re-gathered


def test_degenerate_section_is_retried():
    state = {"first": True}

    def ask(prompt, system=None, max_tokens=1500, temperature=0.4):
        s = (system or "").lower()
        if "planner" in s:
            return "1. Only"
        if "reviewer" in s:
            return ""  # no critique → keep draft
        # first section call returns degenerate, retry returns real content
        if "writing one section" in s:
            if state["first"]:
                state["first"] = False
                return "-"
            return "## Only\n" + ("Real content. " * 20)
        return "## Only\n" + ("Real content. " * 20)

    r = RP.generate_document("x", ask=ask, evidence="e" * 300, doc_type="document", target_words=500)
    assert r["ok"] and "Real content" in r["text"]


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("ELI_DOC_PIPELINE", "0")
    assert RP.enabled() is False
