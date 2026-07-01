"""Memory evidence — the grounded bundle the introspection surfaces read from.

collect_memory_evidence assembles a typed bundle of memory hits for a query (or an
inferred one); build_memory_evidence_text renders it. Both must degrade gracefully
(structured result, never a crash) when the store is empty/unavailable. Runs in the
normal suite against the isolated test DB.
"""
from __future__ import annotations

import pytest

from eli.runtime import memory_evidence as me


def test_infer_current_query_is_str():
    assert isinstance(me.infer_current_query(), str)


def test_collect_bundle_shape():
    b = me.collect_memory_evidence(query="what do you know about me", limit=5)
    assert isinstance(b, dict)
    assert b.get("ok") is True
    assert b.get("kind") == "memory_evidence_bundle"
    assert isinstance(b.get("items"), list)
    assert isinstance(b.get("count"), int)
    assert b["count"] == len(b["items"])


def test_collect_with_no_query_still_structured():
    b = me.collect_memory_evidence(query="", limit=3)
    assert isinstance(b, dict) and isinstance(b.get("items"), list)


def test_build_evidence_text_is_str():
    txt = me.build_memory_evidence_text(limit=5, query="anything")
    assert isinstance(txt, str)


def test_limit_is_respected():
    b = me.collect_memory_evidence(query="test", limit=2)
    assert len(b["items"]) <= 2
