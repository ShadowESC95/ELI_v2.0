"""The World tab's memory_uncertainty awareness bar must be driven by a real
degradation, not just a manual test button.

`memory_uncertainty` was a real event type in `EliWorldAutonomyEngine`
(lowers memory_confidence, raises uncertainty/repair_pressure) rendered as a
live percentage bar, but the only place in the entire codebase that ever
fired it was a manual "Mark Memory Fog" button in the World panel itself --
no real memory-health code path drove it. This wires it to the actual
degradation this session found and fixed the silent-swallow half of: a
memory whose vector-index write failed is still stored (recoverable via
FTS5/LIKE) but will not surface in semantic recall until re-indexed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from eli.memory.memory import Memory
from eli.world import world_event_bus


@pytest.fixture()
def mem(tmp_path):
    m = Memory(db_path=tmp_path / "test_memory.sqlite3")
    m.init_db()
    return m


# ── world_event_bus.fire_memory_uncertainty_event ───────────────────────────
def test_fire_memory_uncertainty_event_uses_the_right_event_type(monkeypatch):
    calls = []
    monkeypatch.setattr(
        world_event_bus, "fire_world_event",
        lambda *a, **kw: calls.append((a, kw)),
    )

    world_event_bus.fire_memory_uncertainty_event("vector index write raised", memory_id=42)

    assert len(calls) == 1
    args, _ = calls[0]
    event_type, source, summary, payload = args
    assert event_type == "memory_uncertainty"
    assert payload["reason"] == "vector index write raised"
    assert payload["memory_id"] == 42


# ── store_memory() wiring ───────────────────────────────────────────────────
def test_vector_store_exception_fires_memory_uncertainty(mem, monkeypatch):
    fired = []
    monkeypatch.setattr(
        world_event_bus, "fire_memory_uncertainty_event",
        lambda reason, memory_id=None: fired.append((reason, memory_id)),
    )

    bad_vs = MagicMock()
    bad_vs.add.side_effect = RuntimeError("faiss index corrupt")
    monkeypatch.setattr(
        "eli.memory.vector_store.get_vector_store", lambda: bad_vs,
    )

    result = mem.store_memory("a fact that fails to vector-index", tags=["unit_verify"])

    assert result["ok"] is True, "the durable SQL write must still succeed"
    assert result["vector_indexed"] is False
    assert fired, "an exception during the vector-store write must fire memory_uncertainty"
    assert fired[0][0] == "vector index write raised"


def test_embedder_declining_to_index_fires_memory_uncertainty(mem, monkeypatch):
    fired = []
    monkeypatch.setattr(
        world_event_bus, "fire_memory_uncertainty_event",
        lambda reason, memory_id=None: fired.append((reason, memory_id)),
    )

    declining_vs = MagicMock()
    declining_vs.add.return_value = False  # ran cleanly, declined the write
    monkeypatch.setattr(
        "eli.memory.vector_store.get_vector_store", lambda: declining_vs,
    )

    result = mem.store_memory("a fact the embedder can't vectorise", tags=["unit_verify"])

    assert result["ok"] is True
    assert result["vector_indexed"] is False
    assert fired, "a clean but declined vector write must still fire memory_uncertainty"
    assert fired[0][0] == "embedder returned no vector"


def test_no_vector_store_configured_does_not_fire_memory_uncertainty(mem, monkeypatch):
    """No vector store at all (e.g. FAISS not installed) is a permanent,
    expected condition -- not a real-time degradation worth an uncertainty
    event."""
    fired = []
    monkeypatch.setattr(
        world_event_bus, "fire_memory_uncertainty_event",
        lambda reason, memory_id=None: fired.append((reason, memory_id)),
    )
    monkeypatch.setattr(
        "eli.memory.vector_store.get_vector_store", lambda: None,
    )

    result = mem.store_memory("a fact with no vector store available", tags=["unit_verify"])

    assert result["ok"] is True
    assert result["vector_indexed"] is False
    assert not fired, "no vector store configured at all must not fire memory_uncertainty"


def test_successful_index_does_not_fire_memory_uncertainty(mem, monkeypatch):
    fired = []
    monkeypatch.setattr(
        world_event_bus, "fire_memory_uncertainty_event",
        lambda reason, memory_id=None: fired.append((reason, memory_id)),
    )

    good_vs = MagicMock()
    good_vs.add.return_value = True
    monkeypatch.setattr(
        "eli.memory.vector_store.get_vector_store", lambda: good_vs,
    )

    result = mem.store_memory("a fact that indexes fine", tags=["unit_verify"])

    assert result["vector_indexed"] is True
    assert not fired
