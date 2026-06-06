"""Memory ingestion + recall: durable biographical/project/research facts are
both extracted from conversation and surfaced in the clean personal-memory
report (not just response-preferences). Deterministic — no model."""
from __future__ import annotations
import pytest

from eli.runtime.personal_memory_clean_response import _extract_fact
from eli.runtime.profile_extractor import extract_patterns_from_text as _extract


# ── Recall: facts that used to be dropped by the narrow _FACT_PATTERNS ────────
@pytest.mark.parametrize("fact", [
    "User focuses on ELI cognition pipeline/orchestrator correctness.",
    "User is actively debugging ELI's SQLite-backed memory and recall system.",
    "User references a Ξ–χ–φ field framework in research/simulation work.",
    "User is interested in quantum gravity.",
    "User is a physicist.",
    "User studies/researches theoretical physics.",
])
def test_clean_response_surfaces_project_and_research_facts(fact):
    assert _extract_fact(fact) is not None


@pytest.mark.parametrize("noise", [
    '{"cmd": "fallout 4", "method": "gui_direct_exec", "name": "fallout 4"}',
    "Reflection (24h): conversation volume up",
    "HackerNews — top stories",
])
def test_clean_response_still_rejects_noise(noise):
    assert _extract_fact(noise) is None


# ── Extraction: high-precision biographical capture from first-person text ────
def _kinds(text):
    return {k for k, _ in _extract(text)}


def test_extract_role():
    assert "identity.role" in _kinds("I'm a physicist and inventor")
    assert "identity.role" in _kinds("i am an engineer")


def test_extract_interest_and_field():
    assert "interest.explicit" in _kinds("i'm really interested in quantum gravity")
    assert "research.field" in _kinds("my field is condensed matter")


def test_extract_explicit_remember():
    assert "user.explicit_note" in _kinds("remember that I prefer metric units")


@pytest.mark.parametrize("casual", [
    "i'm a bit confused about this",
    "i'm interested",
    "i am running the audit now",
])
def test_extraction_ignores_casual_chat(casual):
    assert not ({"identity.role", "interest.explicit", "research.field"} & _kinds(casual))
