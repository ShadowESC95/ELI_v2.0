"""
Regression tests for the "what is my dog's name" recall failure.

Root cause (June 23rd, dog "Shadow"): a fact stated in passing ("Shadow (my
dog)") was written to the raw conversation_turns log but never promoted into any
durable store (memories / kg_entities), and:
  * the KG extractor had no pattern for possessive relationships ("my dog X"),
  * the raw-log recall fallback matched the whole question verbatim (so
    "%what is my dog's name%" never matched "...my dog Shadow"),
  * the KG context block truncated at 5 relations without query-awareness, and
  * demoted/contradicted name relations still leaked into context.

These tests lock in the fixes.
"""
import time
import pathlib

import pytest

from eli.memory.knowledge_graph import KnowledgeGraph, reset_knowledge_graph
from eli.memory.memory import Memory


@pytest.fixture
def kg(tmp_path):
    return KnowledgeGraph(db_path=tmp_path / "kg_test.sqlite3")


# ── KG possessive-relationship extraction ──────────────────────────────────

@pytest.mark.parametrize("text,predicate,name", [
    ("haha, i am going to explain darwinsim to Shadow (my dog), next", "has_dog", "Shadow"),
    ("my dog Shadow is very smart", "has_dog", "Shadow"),
    ("my dog's name is Rex", "has_dog", "Rex"),
    ("my dog is named Bella", "has_dog", "Bella"),
    ("Rex, my dog, ate the couch", "has_dog", "Rex"),
    ("my wife Sarah cooked dinner", "has_wife", "Sarah"),
    ("my son is called Tom", "has_son", "Tom"),
    ("my puppy Biscuit chewed a shoe", "has_dog", "Biscuit"),   # puppy -> dog
])
def test_kg_extracts_possessive_relationships(kg, text, predicate, name):
    kg.extract_from_memory(text, source="user")
    rels = {(r["predicate"], r["object"]) for r in (kg.query_entity("User") or {}).get("outbound", [])}
    assert (predicate, name) in rels, f"{text!r} -> missing {(predicate, name)}; got {rels}"


@pytest.mark.parametrize("text", [
    "my dog is barking",        # no capitalised name
    "i walked my dog today",    # no name at all
    "i really love my dog",
])
def test_kg_rejects_relationship_noise(kg, text):
    kg.extract_from_memory(text, source="user")
    rels = {(r["predicate"], r["object"]) for r in (kg.query_entity("User") or {}).get("outbound", [])}
    assert not any(p == "has_dog" for p, _ in rels), f"{text!r} wrongly extracted {rels}"


def test_kg_relationship_gated_to_trusted_source(kg):
    """Assistant/synthesised text must not poison the graph with relationships."""
    kg.extract_from_memory("my dog Shadow is a good boy", source="assistant")
    ent = kg.query_entity("User")
    rels = {(r["predicate"], r["object"]) for r in (ent or {}).get("outbound", [])}
    assert ("has_dog", "Shadow") not in rels


# ── KG context rendering: query-aware + retired-relation suppression ────────

def test_kg_context_is_query_aware(kg):
    # Bury the dog fact under many higher-volume "prefers" relations.
    for i in range(8):
        kg.extract_from_memory(f"user prefers thing{i}.", source="user")
    kg.extract_from_memory("my dog Shadow is my dog", source="user")
    ctx = kg.context_for_prompt("what is my dog's name")
    assert "Shadow" in ctx, f"dog fact crowded out of KG context:\n{ctx}"


def test_kg_context_suppresses_demoted_name(kg):
    # Two conflicting names: the older one is demoted and must not render.
    kg.extract_from_memory("my name is Jason", source="user")
    kg.extract_from_memory("my name is Sam", source="user")   # newer wins, Jason demoted
    ctx = kg.context_for_prompt("who am i, what is my name")
    assert "Sam" in ctx
    assert "Jason" not in ctx, f"retired name leaked into context:\n{ctx}"


# ── Raw-log recall fallback keys on the distinctive noun ────────────────────

def test_conversation_fallback_surfaces_passing_fact(tmp_path, monkeypatch):
    # Force sparse durable results so the conversation_turns fallback fires.
    import eli.memory.vector_store as vs
    monkeypatch.setattr(vs, "get_vector_store", lambda *a, **k: None)

    db = tmp_path / "user.sqlite3"
    mem = Memory(db_path=db)
    now = time.time()
    mem.add_conversation_turn("user", "haha explaining darwinism to Shadow (my dog), next")
    time.sleep(0.01)
    mem.add_conversation_turn("user", "what is the weather today")        # recent noise
    mem.add_conversation_turn("user", "remind me about my meeting tomorrow")

    res = mem.recall_memory("what is my dog's name", limit=5)
    texts = " || ".join((r.get("text") or "") for r in res)
    assert "Shadow" in texts, f"fallback failed to surface the dog turn: {texts}"


def test_conversation_fallback_prefers_distinctive_noun_over_recency(tmp_path, monkeypatch):
    import eli.memory.vector_store as vs
    monkeypatch.setattr(vs, "get_vector_store", lambda *a, **k: None)
    db = tmp_path / "user.sqlite3"
    mem = Memory(db_path=db)
    mem.add_conversation_turn("user", "my dog Shadow loves the park")
    # A more recent turn that only matches the generic word 'name'.
    mem.add_conversation_turn("user", "what was that restaurant name again")
    res = mem.recall_memory("what is my dog's name", limit=3)
    assert res, "no fallback results"
    assert "Shadow" in (res[0].get("text") or ""), \
        f"distinctive-noun turn should rank first, got {[r.get('text') for r in res]}"


# ── add_conversation_turn promotes passing facts into the KG ─────────────────

def test_add_conversation_turn_promotes_fact_to_kg(tmp_path):
    reset_knowledge_graph()   # isolated (points at ELI_ARTIFACTS_DIR=_pytest store)
    from eli.memory.knowledge_graph import get_knowledge_graph
    db = tmp_path / "user.sqlite3"
    mem = Memory(db_path=db)
    mem.add_conversation_turn("user", "my dog Rexington is a rescue")
    rels = {(r["predicate"], r["object"]) for r in (get_knowledge_graph().query_entity("User") or {}).get("outbound", [])}
    assert ("has_dog", "Rexington") in rels, f"promotion did not reach the KG; got {rels}"
    reset_knowledge_graph()
