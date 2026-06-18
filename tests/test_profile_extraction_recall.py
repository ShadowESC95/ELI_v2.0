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
    "User references a custom field-theory framework in research/simulation work.",
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


# ── Dynamic facts: recency refresh on reaffirmation + staleness aging ─────────
def test_reaffirmation_refreshes_recency(tmp_path):
    import sqlite3, time
    import eli.runtime.profile_extractor as PE
    db = tmp_path / "u.sqlite3"
    PE.ensure_profile_tables(db)
    con = sqlite3.connect(str(db)); cur = con.cursor()
    now = time.time()
    PE._insert_user_pattern(cur, "project.x", "User focuses on project X.", ts_value=now - 40 * 86400)
    con.commit()
    # Re-mention today → ts refreshed to ~now (not a no-op).
    PE._insert_user_pattern(cur, "project.x", "User focuses on project X.", ts_value=now)
    con.commit()
    ts = cur.execute("SELECT ts FROM user_patterns WHERE pattern_type='project.x'").fetchone()[0]
    con.close()
    assert abs(ts - now) < 5


def test_stale_volatile_dropped_stable_kept(tmp_path, monkeypatch):
    import sqlite3, time
    import eli.runtime.profile_extractor as PE
    import eli.runtime.personal_memory_clean_response as PM
    db = tmp_path / "u.sqlite3"
    PE.ensure_profile_tables(db)
    con = sqlite3.connect(str(db)); cur = con.cursor()
    now = time.time()
    old = now - 40 * 86400
    PE._insert_user_pattern(cur, "project.old", "User focuses on the image generator.", ts_value=old)
    PE._insert_user_pattern(cur, "project.cur", "User is actively debugging the memory system.", ts_value=now)
    PE._insert_user_pattern(cur, "preference.style", "User dislikes vague descriptions and wants concrete detail.", ts_value=old)
    PE._insert_user_pattern(cur, "research.science", "User references a custom field-theory framework in research/simulation work.", ts_value=old)
    con.commit(); con.close()
    monkeypatch.setattr(PM, "USER_DB", db)
    monkeypatch.setattr(PM, "AGENT_DB", tmp_path / "a.sqlite3")
    facts, _ = PM._collect_facts()
    blob = " | ".join(facts)
    assert "image generator" not in blob          # stale volatile project dropped
    assert "debugging the memory" in blob          # current project kept
    assert "dislikes vague" in blob                # stable preference kept regardless of age
    assert "field-theory" in blob                  # stable research framework kept
