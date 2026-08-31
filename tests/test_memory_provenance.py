"""Memory provenance tier — verified vs hypothesis storage and recall."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from eli.runtime.memory_provenance import (
    HYPOTHESIS,
    VERIFIED,
    filter_grounding_hits,
    is_explicit_memory_audit_query,
    resolve_write_provenance,
)


def test_auto_extract_writes_as_hypothesis():
    status, prov = resolve_write_provenance(
        source="user", tags=["preference", "auto_extracted"],
    )
    assert status == HYPOTHESIS
    assert prov == "auto_extract"


def test_user_verbatim_writes_as_verified():
    status, prov = resolve_write_provenance(source="user", tags=["preference"])
    assert status == VERIFIED
    assert prov == "user_verbatim"


def test_filter_grounding_hits_excludes_hypothesis():
    hits = [
        {"id": 1, "text": "verified fact", "verification_status": "verified"},
        {"id": 2, "text": "guess", "verification_status": "hypothesis"},
        {"id": 3, "text": "legacy", "tags": "auto_extracted,preference"},
    ]
    out = filter_grounding_hits(hits)
    assert len(out) == 1
    assert out[0]["id"] == 1


def test_explicit_memory_audit_query():
    assert is_explicit_memory_audit_query("what do you remember about me")
    assert not is_explicit_memory_audit_query("hey buddy how are you")


def test_store_auto_extract_persists_hypothesis_tier(tmp_path, monkeypatch):
    """Auto-extracted facts are stored as hypothesis, not verified grounding."""
    db = tmp_path / "user.sqlite3"
    monkeypatch.setenv("ELI_TEST_MODE", "1")

    from eli.memory.memory import Memory

    mem = Memory(db_path=str(db))
    mem.store_memory(
        "I prefer dark mode for coding",
        tags=["preference"],
        source="user",
    )
    mem.store_memory(
        "i am a developer working on eli",
        tags=["identity", "auto_extracted"],
        source="user",
    )

    conn = mem._get_connection()
    try:
        verified_row = conn.execute(
            "SELECT verification_status, provenance_kind FROM memories "
            "WHERE text LIKE '%dark mode%'",
        ).fetchone()
        hypothesis_row = conn.execute(
            "SELECT verification_status, provenance_kind FROM memories "
            "WHERE text LIKE '%developer%'",
        ).fetchone()
    finally:
        conn.close()

    assert verified_row[0] == VERIFIED
    assert hypothesis_row[0] == HYPOTHESIS
    assert hypothesis_row[1] == "auto_extract"
