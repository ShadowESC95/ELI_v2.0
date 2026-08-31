"""User-claim validator — blocks unattested user biography in CHAT output."""
from __future__ import annotations

from eli.cognition.user_claim_validator import (
    extract_user_attribution_sentences,
    validate_user_claims_against_evidence,
)


def test_wild_night_claim_is_unsafe_without_evidence():
    out = (
        "Hey buddy, I was thinking back to that time you mentioned waking up late "
        "after a wild night."
    )
    verdict = validate_user_claims_against_evidence(out, evidence="")
    assert verdict["unsafe"] is True
    assert "verified memory" in verdict["sanitized"].lower()


def test_wild_night_claim_allowed_when_evidenced():
    evidence = "User: I had a wild night last week and woke up late."
    out = "You mentioned waking up late after a wild night last week."
    verdict = validate_user_claims_against_evidence(out, evidence=evidence)
    assert not verdict.get("unsafe")
    assert not verdict.get("violations")


def test_casual_chat_without_user_claims_passes():
    out = "Chilling sounds good. Sorting out the codebase is a solid plan."
    verdict = validate_user_claims_against_evidence(out, evidence="")
    assert verdict["ok"] is True
    assert verdict["sanitized"] == out


def test_extract_finds_been_through_claim():
    claims = extract_user_attribution_sentences(
        "Feels like you've been through quite a bit lately."
    )
    assert any(c["kind"] == "life_event" for c in claims)
