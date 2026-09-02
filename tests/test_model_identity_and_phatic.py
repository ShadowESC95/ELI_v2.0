"""Model identity disputes and compound phatic detection."""
from __future__ import annotations

from eli.cognition.correction_patterns import is_correction_query, is_model_identity_dispute
from eli.execution.router_enhanced import route
from eli.kernel.engine import _is_brief_phatic_prompt as phatic
from eli.runtime import grounding_escalation as G


def test_story_and_you_good_is_phatic():
    assert phatic("What's the story? you good?")


def test_model_dispute_routes_runtime_status():
    r = route("What the fuck, no you are not, you are GLM!!!!!!!!")
    assert r["action"] == "RUNTIME_STATUS"
    assert r["meta"]["matched_by"] == "router.model_identity_dispute"


def test_what_is_your_model_routes_runtime_status():
    r = route("what is your model??")
    assert r["action"] == "RUNTIME_STATUS"
    assert "model" in r["meta"]["matched_by"]


def test_check_model_again_routes_runtime_status():
    r = route("no you are not you fucking clown!! check the model again!!!!")
    assert r["action"] == "RUNTIME_STATUS"


def test_why_did_you_lie_is_correction():
    assert is_correction_query("why did you lie earlier then ?")


def test_codebase_health_routes_runtime_audit():
    r = route("How is the codebase?")
    assert r["action"] == "RUNTIME_AUDIT"
    assert "codebase" in r["meta"]["matched_by"]


def test_codebase_health_long_preamble_routes_via_trailing_clause():
    msg = (
        "just another house call and check-in with you bud, still trying to "
        "iron out the kinks. How is the codebase?"
    )
    r = route(msg)
    assert r["action"] == "RUNTIME_AUDIT"
    assert "codebase" in r["meta"]["matched_by"]


def test_runtime_recheck_correction_routes_runtime_status():
    r = route("That is not true, check again")
    assert r["action"] == "RUNTIME_STATUS"
    assert r["meta"]["matched_by"] == "router.runtime_recheck_correction"


def test_runtime_recheck_not_biographical_dispute():
    from eli.cognition.correction_patterns import is_biographical_dispute
    assert not is_biographical_dispute("That is not true, check again")


def test_model_dispute_not_web_factual():
    q = "What the fuck, no you are not, you are GLM!!!!!!!!"
    assert G.classify_factual(q) == (False, "none")
    assert is_model_identity_dispute(q)
