"""'in depth' / 'deeper' / 'tell me more' are meant to catch short nudges continuing whatever ELI
just said ("be more in depth", "go deeper"). Unguarded, the same regex matched a fresh, standalone
question that happened to contain "in depth" ("give me an in depth response as to how you and your
codebase are doing") and routed it as a quick, evidence-free follow-up instead of a real answer —
from a live session, req-000001 and req-000002 of the 2.4.74 AppImage log.
"""
import os

os.environ.setdefault("ELI_TEST_MODE", "1")

from eli.runtime.control_contracts import is_identity_depth_followup, is_persona_self_knowledge_query
from eli.execution.router_enhanced import route

FRESH_QUESTIONS = [
    "Hey Eli, you doing lright in there? give me an in depth response as to how you and "
    "your codebase are doing, compared to over the last week or so",
    "Dude, that is most definitely not an in depth answer. So you are not aware of anything "
    "that happened over the last week? nothing in your logs ?",
]

SHORT_NUDGES = [
    "be more in depth",
    "go deeper",
    "more in depth please",
    "tell me more",
    "what else",
]


def test_fresh_questions_do_not_match_the_depth_followup_helpers():
    for msg in FRESH_QUESTIONS:
        assert not is_identity_depth_followup(msg), msg
        assert not is_persona_self_knowledge_query(msg), msg


def test_fresh_questions_are_not_routed_as_the_identity_depth_followup():
    for msg in FRESH_QUESTIONS:
        r = route(msg)
        assert r.get("meta", {}).get("matched_by") != "eli.followup.identity_depth", msg


def test_short_nudges_still_match():
    for msg in SHORT_NUDGES:
        assert is_identity_depth_followup(msg), msg
