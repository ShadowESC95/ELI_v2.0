"""Model identity disputes and compound phatic detection."""
from __future__ import annotations

from eli.cognition.correction_patterns import is_model_identity_dispute
from eli.execution.router_enhanced import route
from eli.kernel.engine import _is_brief_phatic_prompt as phatic
from eli.runtime import grounding_escalation as G


def test_story_and_you_good_is_phatic():
    assert phatic("What's the story? you good?")


def test_model_dispute_routes_runtime_status():
    r = route("What the fuck, no you are not, you are GLM!!!!!!!!")
    assert r["action"] == "RUNTIME_STATUS"
    assert r["meta"]["matched_by"] == "router.model_identity_dispute"


def test_model_dispute_not_web_factual():
    q = "What the fuck, no you are not, you are GLM!!!!!!!!"
    assert G.classify_factual(q) == (False, "none")
    assert is_model_identity_dispute(q)
