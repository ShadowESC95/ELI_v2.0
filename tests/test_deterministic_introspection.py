"""Deterministic introspection — the diagnostic-action classifier.

classify_diagnostic_action maps a technical self-query ("what are you running",
"how many memories", "agent bus status") to a grounded diagnostic action, while
deliberately NOT swallowing persona questions ("who are you") or generative asks
("write a report about your agent bus" -> must route to doc-gen, not a status
dump). Pure regex logic. Runs in the normal suite.
"""
from __future__ import annotations

import pytest

from eli.runtime.deterministic_introspection import classify_diagnostic_action as clf


@pytest.mark.parametrize("text,expected", [
    ("what are you running on", "RUNTIME_STATUS"),
    ("show me the runtime status", "RUNTIME_STATUS"),
    ("how many memories do you have", "EXPLAIN_MEMORY_RUNTIME"),
    ("what's your reasoning mode", "REASONING_MODE_STATUS"),
    ("walk me through your cognition pipeline", "EXPLAIN_COGNITION_RUNTIME"),
    ("which agents contributed to your last response", "EXPLAIN_LAST_RESPONSE"),
    ("what's the status of your agent bus", "AGENTBUS_STATUS"),
    ("show me the orchestrator", "ORCHESTRATOR_STATUS"),
    ("what does the output governor do", "OUTPUT_GOVERNOR_STATUS"),
])
def test_classifies_technical_self_queries(text, expected):
    assert clf(text) == expected


def test_import_audit_needs_subject_and_request():
    assert clf("what is the status of your imports") == "IMPORT_AUDIT"
    assert clf("audit your virtual environment") == "IMPORT_AUDIT"


def test_generative_request_is_not_a_status_dump():
    # "write/generate a report about X" is a doc-gen task — must NOT be intercepted.
    assert clf("write a report about your agent bus") is None
    assert clf("generate a document about your cognition runtime") is None


def test_persona_and_empty_not_diagnostic():
    assert clf("who are you") is None          # persona question → LLM answers
    assert clf("") is None
    assert clf(None) is None
    assert clf("tell me a joke") is None


def test_reasoning_mode_vs_full_cognition():
    # "reasoning mode" alone → mode status; but with "cognition pipeline" → the fuller
    # cognition report (not the narrow mode status).
    assert clf("what reasoning mode are you in") == "REASONING_MODE_STATUS"
    assert clf("explain your reasoning mode and cognition runtime") == "EXPLAIN_COGNITION_RUNTIME"
