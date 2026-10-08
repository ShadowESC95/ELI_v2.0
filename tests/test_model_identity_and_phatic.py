"""Model identity disputes and compound phatic detection."""
from __future__ import annotations

from eli.cognition.correction_patterns import is_correction_query, is_model_identity_dispute
from eli.execution.router_enhanced import route
from eli.kernel.engine import _is_brief_phatic_prompt as phatic
from eli.runtime import grounding_escalation as G
from eli.kernel.engine import _said_about_the_user


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


# A complaint that says "you are not ..." is not the user disputing which model is loaded.
#
# Live: "...but you are not properly searching for fucking songs i asked for!!" matched the
# model-identity dispute and got the runtime status dump instead of an answer.
SESSION = ("Why the fuck did you not open spotify when i asked you to, but you can apparently just play one "
           "fucking song/resume on spotify, but you are not properly searching for fucking songs i asked for!!")


def test_complaints_about_what_eli_did_are_not_model_disputes():
    for text in (SESSION, "you are not listening", "that's not what i said", "you're not even trying"):
        assert not is_model_identity_dispute(text), text


def test_real_model_disputes_still_are():
    for text in ("you're not GLM", "you are not running qwen", "check the model again", "wrong model",
                 "you're not using the model I picked", "no you're not"):
        assert is_model_identity_dispute(text), text


def test_the_session_complaint_is_chat_not_a_status_dump():
    from eli.kernel.engine import _mw_rs_is_runtime_status_question
    assert not _mw_rs_is_runtime_status_question(SESSION)


def test_what_eli_said_about_itself_is_not_about_the_user():
    # "Why do you say that?" after this asked ELI what it meant; it apologised for implying
    # something about the user's caffeine intake.
    assert not _said_about_the_user(
        "Feels like I've had a bit more caffeine than usual. What's on your agenda for the evening?")
    assert _said_about_the_user("You mentioned feeling groggy earlier, and you said you slept badly.")
