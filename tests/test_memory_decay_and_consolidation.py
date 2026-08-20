"""Memory decay is age-based, and consolidation retires exact duplicates.

Both of these were nominally present and effectively inert on a live store:

  * `apply_weight_decay` multiplied the stored weight by a constant on each call,
    so the result tracked how often the function ran rather than how old the
    memory was. Its only caller fires on ~1% of responses, so a 441-memory live
    database still had weight=1.0 on every single row — 174 of them over a week
    old. `weight` carries 15% of the recall fusion score, so that term was a
    constant contributing no ranking signal.

  * Nothing ever merged duplicate memories. Reflection's dedupe guard was fixed
    (it now does an existence check rather than a relevance query), but the
    169 exact-text duplicates already on disk — 38% of the store, one insight
    repeated 28 times — stayed there.

These tests build their own database via `Memory(db_path=...)` rather than
redirecting the process-wide data dir: `paths.data_dir()` is lru_cached and
pointing it at a tmp_path leaks into every later test in the run.
"""
from __future__ import annotations

import time

import pytest

from eli.memory.memory import Memory


DAY = 86400.0


@pytest.fixture()
def mem(tmp_path):
    return Memory(db_path=str(tmp_path / "user.sqlite3"))


def _insert(mem, text, *, age_days=0.0, importance=0.5, tags="", weight=1.0):
    conn = mem._get_connection()
    try:
        ts = time.time() - age_days * DAY
        conn.execute(
            "INSERT INTO memories (text, tags, ts, timestamp, importance, weight) "
            "VALUES (?,?,?,?,?,?)",
            (text, tags, ts, ts, importance, weight),
        )
        rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # Mirror _store_memory_row: `memories` has no triggers, so the real store
        # path indexes FTS with an explicit INSERT. A test that skipped this would
        # be asserting against an empty index.
        conn.execute("INSERT INTO memories_fts(rowid, text, tags) VALUES (?,?,?)",
                     (rowid, text, tags))
        conn.commit()
        return rowid
    finally:
        conn.close()


def _weights(mem):
    conn = mem._get_connection()
    try:
        return {r[0]: r[1] for r in conn.execute("SELECT text, weight FROM memories")}
    finally:
        conn.close()


# ── decay ────────────────────────────────────────────────────────────────────

def test_decay_is_graded_by_age(mem):
    """The whole point: an older memory must end up lighter than a newer one."""
    _insert(mem, "fresh", age_days=8, importance=0.5)
    _insert(mem, "middling", age_days=60, importance=0.5)
    _insert(mem, "ancient", age_days=400, importance=0.5)

    mem.apply_weight_decay()
    w = _weights(mem)
    assert w["fresh"] > w["middling"] > w["ancient"], (
        f"decay must order by age, got {w}")


def test_decay_does_not_depend_on_how_often_it_runs(mem):
    """The original bug: weight fell further every call, so it measured call count."""
    _insert(mem, "old", age_days=90, importance=0.5)

    mem.apply_weight_decay()
    once = _weights(mem)["old"]
    for _ in range(25):
        mem.apply_weight_decay()
    many = _weights(mem)["old"]

    assert once == pytest.approx(many, abs=0.01), (
        f"running decay 26x must match running it once ({once} vs {many}); "
        "the old implementation compounded and would land near the floor")


def test_repeat_runs_report_no_work(mem):
    """A no-op run must say so, or 'rows updated' can never reveal a stuck decay."""
    _insert(mem, "old", age_days=90, importance=0.5)
    assert mem.apply_weight_decay() == 1
    assert mem.apply_weight_decay() == 0


def test_importance_slows_decay(mem):
    """Recall reinforces importance (+0.02/recall), so importance must buy survival."""
    _insert(mem, "ignored", age_days=120, importance=0.10)
    _insert(mem, "recalled", age_days=120, importance=0.80)

    mem.apply_weight_decay()
    w = _weights(mem)
    assert w["recalled"] > w["ignored"]


def test_high_importance_is_pinned(mem):
    """An explicitly important fact must not fade just by sitting on disk."""
    _insert(mem, "pinned", age_days=900, importance=0.95)
    mem.apply_weight_decay()
    assert _weights(mem)["pinned"] == 1.0


def test_decay_respects_the_floor(mem):
    """Nothing is ever deleted or zeroed by decay — it bottoms out at min_weight."""
    _insert(mem, "prehistoric", age_days=100000, importance=0.0)
    mem.apply_weight_decay(min_weight=0.05)
    assert _weights(mem)["prehistoric"] == pytest.approx(0.05)


def test_recent_memories_are_left_alone(mem):
    """older_than_days still gates which rows are eligible at all."""
    _insert(mem, "today", age_days=0.5, importance=0.5)
    mem.apply_weight_decay(older_than_days=7)
    assert _weights(mem)["today"] == 1.0


# ── consolidation ────────────────────────────────────────────────────────────

def test_consolidation_merges_exact_duplicates(mem):
    _insert(mem, "User model — current focus: physics", importance=0.60, tags="a")
    _insert(mem, "User model — current focus: physics", importance=0.99, tags="b")
    _insert(mem, "User model — current focus: physics", importance=0.55, tags="a,c")
    _insert(mem, "something else entirely", importance=0.5)

    result = mem.consolidate_memories()
    assert result["groups"] == 1
    assert result["removed"] == 2

    conn = mem._get_connection()
    try:
        rows = conn.execute(
            "SELECT text, importance, tags FROM memories "
            "WHERE text LIKE 'User model%'").fetchall()
        assert len(rows) == 1, "duplicates must collapse to one canonical row"
        assert rows[0][1] == pytest.approx(0.99), "survivor keeps the group's best importance"
        assert set(rows[0][2].split(",")) == {"a", "b", "c"}, "tags are unioned"
        assert conn.execute(
            "SELECT COUNT(*) FROM memories").fetchone()[0] == 2, "non-duplicate survives"
    finally:
        conn.close()


def test_consolidation_keeps_the_most_recent_timestamp(mem):
    """A repeated observation is a reaffirmed one and should rank as recent."""
    _insert(mem, "repeated fact", age_days=30, importance=0.5)
    _insert(mem, "repeated fact", age_days=1, importance=0.4)

    mem.consolidate_memories()
    conn = mem._get_connection()
    try:
        ts = conn.execute("SELECT timestamp FROM memories").fetchone()[0]
    finally:
        conn.close()
    age_days = (time.time() - ts) / DAY
    assert age_days < 2, f"survivor should carry the newest timestamp, looks {age_days:.1f}d old"


def test_dry_run_changes_nothing(mem):
    _insert(mem, "dup", importance=0.5)
    _insert(mem, "dup", importance=0.5)

    result = mem.consolidate_memories(dry_run=True)
    # Two identical rows collapse to one, so exactly one row is removed.
    assert result["removed"] == 1 and result["dry_run"] is True

    conn = mem._get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
    finally:
        conn.close()


def test_consolidation_is_idempotent(mem):
    _insert(mem, "dup", importance=0.5)
    _insert(mem, "dup", importance=0.5)
    mem.consolidate_memories()
    assert mem.consolidate_memories()["removed"] == 0


def test_fts_follows_consolidation(mem):
    """memories_fts is content-backed; a stale row there resurrects a deleted memory
    in keyword recall, which is the half of hybrid retrieval FTS5 now serves."""
    for _ in range(4):
        _insert(mem, "duplicated insight about reactors", importance=0.5)

    mem.consolidate_memories()
    conn = mem._get_connection()
    try:
        n_mem = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        # COUNT(*) on an external-content FTS table just reads the content table,
        # so it can never reveal a stale index. Query the index itself.
        hit_ids = [r[0] for r in conn.execute(
            "SELECT rowid FROM memories_fts WHERE memories_fts MATCH 'reactors'")]
        live_ids = {r[0] for r in conn.execute("SELECT id FROM memories")}
    finally:
        conn.close()
    assert n_mem == 1
    assert len(hit_ids) == 1, (
        f"keyword recall returned {len(hit_ids)} hits for one surviving memory — "
        "the FTS index kept entries for the deleted rows")
    assert set(hit_ids) <= live_ids, (
        f"FTS returned rowids {hit_ids} that no longer exist in memories")


def test_empty_text_is_not_treated_as_a_duplicate_group(mem):
    """Blank rows are all 'equal' to each other and must not be merged together."""
    _insert(mem, "", importance=0.5)
    _insert(mem, "   ", importance=0.5)
    assert mem.consolidate_memories()["removed"] == 0
