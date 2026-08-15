"""The semantic memory tier had four readers and no writer.

Found in a 2.1.86 log as a traceback ELI printed on every grounded-evidence build:

    sqlite3.OperationalError: no such table: semantic
      at engine._build_grounded_evidence_context

The table is read in four places — recall injects semantic facts FIRST on identity
questions with a +0.5 weight boost, and two status surfaces count them into
memory_entries / processed_memories. It was only ever created lazily inside
``MemorySystem.store_semantic()``, and that method had **zero callers anywhere in
the repo**. So the tier was never written, the table never existed, every read
threw, and the highest-priority slot in identity recall was permanently empty.

The write point is profile_extractor: it is already where a durable user fact is
committed, already dedupes, and already runs on real user turns.
"""
import sqlite3

import pytest

from eli.runtime import profile_extractor as pe


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "user.sqlite3"
    pe.ensure_profile_tables(path)
    conn = sqlite3.connect(str(path))
    yield conn, conn.cursor()
    conn.close()


def test_the_table_exists_from_first_boot(db):
    """A fresh profile must not have to wait for a write to have a schema."""
    _conn, cur = db
    assert pe._table_exists(cur, "semantic")


@pytest.mark.parametrize("ptype,fact", [
    ("identity.name", "User's name is Jason."),
    ("identity.role", "User is an independent physicist."),
    ("preference.tone", "Prefers direct, concise answers."),
    ("project.current", "Working on QMSH solar-to-hydrogen."),
    ("research.topic", "Entropy and coherence fields."),
    ("interest.games", "Plays Fallout and Oblivion."),
])
def test_durable_facts_are_promoted(db, ptype, fact):
    conn, cur = db
    pe._insert_user_pattern(cur, ptype, fact)
    conn.commit()
    stored = [r[0] for r in cur.execute("SELECT fact FROM semantic").fetchall()]
    assert fact in stored


@pytest.mark.parametrize("ptype,fact", [
    ("preference.session", "Session-scoped chatter"),
    ("mood.transient", "Seems tired today"),
    ("tone.humor", "Used a joke this turn"),
])
def test_transient_patterns_are_not_promoted(db, ptype, fact):
    """The tier is injected AHEAD of ordinary recall on identity questions.
    Filling it with per-session state would bury the facts it exists to surface."""
    conn, cur = db
    pe._insert_user_pattern(cur, ptype, fact)
    conn.commit()
    stored = [r[0] for r in cur.execute("SELECT fact FROM semantic").fetchall()]
    assert fact not in stored


def test_a_reaffirmed_fact_is_not_duplicated(db):
    conn, cur = db
    for _ in range(3):
        pe._insert_user_pattern(cur, "identity.name", "User's name is Jason.")
    conn.commit()
    n = cur.execute("SELECT COUNT(*) FROM semantic WHERE lower(fact)=lower(?)",
                    ("User's name is Jason.",)).fetchone()[0]
    assert n == 1


def test_promotion_carries_the_pattern_type_as_a_tag(db):
    """Readers filter on tags like 'user_fact'; the source type is kept too."""
    conn, cur = db
    pe._insert_user_pattern(cur, "identity.name", "User's name is Jason.")
    conn.commit()
    tags = cur.execute("SELECT tags FROM semantic LIMIT 1").fetchone()[0]
    assert "user_fact" in tags and "identity.name" in tags


def test_the_direct_api_also_dedupes(tmp_path, monkeypatch):
    """store_semantic() stays usable for callers holding a fact, and must not
    double-insert what the extractor already recorded."""
    from eli.memory.memory import Memory

    # Memory is a metaclass-managed singleton and closes the connection it hands
    # out, so the stub hands back a FRESH connection per call — which is what a
    # real pooled _get_connection does anyway. Dedupe therefore has to hold via
    # the file, not via a single live handle.
    path = tmp_path / "user.sqlite3"

    class _Stub:
        def _get_connection(self):
            return sqlite3.connect(str(path))

    store = Memory.__dict__["store_semantic"]
    stub = _Stub()

    assert store(stub, "User's name is Jason.") is True
    assert store(stub, "user's NAME is jason.") is False   # case-insensitive
    assert store(stub, "") is False
    assert store(stub, "   ") is False

    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM semantic").fetchone()[0] == 1
    finally:
        conn.close()
