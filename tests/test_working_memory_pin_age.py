"""_PinnedFact.ts (wall-clock pin time) was set on every fact and read
nowhere -- dead. restore() reset it to time.time() unconditionally, even
though persist() already writes the real original pin time to SQLite as
`saved_at`; restore()'s own SELECT just never asked for that column. So a
fact restored from yesterday's session reported itself as pinned seconds
ago, and there was no wall-clock staleness check at all -- only a turn-count
one (MAX_AGE_TURNS), which barely moves for a session chatted with rarely
over many real days.

Wired in: restore() now round-trips the real saved_at; context_block() and
summary() surface a fact's true age; _evict_stale() gained a wall-clock
backstop keyed on last_hit_ts (a NEW field, separate from ts -- last_hit_ts
tracks reaffirmation, ts is the immutable original pin time, so a fact
reaffirmed daily is never evicted just because it was first pinned a while
back).
"""
import time

from eli.cognition.working_memory import (
    MAX_AGE_SECONDS, WorkingMemory, _age_label,
)


def test_age_label_is_empty_for_a_fresh_pin():
    assert _age_label(60) == ""          # 1 minute
    assert _age_label(3 * 3600) == ""    # 3 hours, under the 4h floor


def test_age_label_shows_hours_then_days():
    assert "4h ago" in _age_label(4 * 3600)
    assert "23h ago" in _age_label(23 * 3600)
    assert "2d ago" in _age_label(50 * 3600)


def test_context_block_shows_age_for_an_old_pin_but_not_a_fresh_one():
    wm = WorkingMemory()
    wm.pin("Fresh fact", source="test")
    wm.pin("Old fact", source="test")
    wm._facts[wm._key("Old fact")].ts = time.time() - 3 * 86400  # 3 days old

    block = wm.context_block()
    assert "Fresh fact" in block
    assert "Old fact" in block
    fresh_line = [l for l in block.splitlines() if "Fresh fact" in l][0]
    old_line = [l for l in block.splitlines() if "Old fact" in l][0]
    assert "pinned" not in fresh_line
    assert "pinned 3d ago" in old_line


def test_restore_preserves_the_real_original_pin_time(tmp_path):
    db = tmp_path / "wm.sqlite3"
    wm1 = WorkingMemory()
    wm1.pin("A fact from a while ago", source="test", importance=0.9)
    real_pin_time = time.time() - 5 * 86400  # backdate it 5 days
    wm1._facts[wm1._key("A fact from a while ago")].ts = real_pin_time
    wm1.persist(str(db))

    wm2 = WorkingMemory()
    loaded = wm2.restore(str(db))
    assert loaded == 1
    restored = wm2._facts[wm2._key("A fact from a while ago")]
    assert abs(restored.ts - real_pin_time) < 2, (
        "restore() did not preserve the real original pin time"
    )


def test_summary_reports_age_seconds():
    wm = WorkingMemory()
    wm.pin("Something", source="test", importance=0.9)
    fact = wm._facts[wm._key("Something")]
    fact.ts = time.time() - 100
    s = wm.summary()
    entry = [f for f in s["facts"] if f["text"] == "Something"][0]
    assert entry["age_seconds"] >= 100
    assert entry["pinned_at"] == fact.ts


def test_wall_clock_eviction_catches_a_rarely_used_long_lived_session():
    """A fact whose LAST REFERENCE is older than MAX_AGE_SECONDS is evicted
    even though the turn counter (which only advances on real requests) has
    barely moved -- the exact gap a turn-only staleness check misses."""
    wm = WorkingMemory()
    wm.pin("Ancient unreferenced fact", source="test", importance=0.3)
    fact = wm._facts[wm._key("Ancient unreferenced fact")]
    fact.last_hit_ts = time.time() - (MAX_AGE_SECONDS + 3600)
    fact.last_hit_turn = wm._turn  # turn count says "just referenced"

    wm.advance_turn()  # triggers _evict_stale()

    assert wm._key("Ancient unreferenced fact") not in wm._facts


def test_touching_a_fact_refreshes_last_hit_ts_not_just_last_hit_turn():
    wm = WorkingMemory()
    wm.pin("Reaffirmed fact", source="test")
    fact = wm._facts[wm._key("Reaffirmed fact")]
    fact.last_hit_ts = time.time() - 1000
    old_ts = fact.last_hit_ts

    wm.pin("Reaffirmed fact", source="test")  # re-pin = touch()

    assert fact.last_hit_ts > old_ts


def test_a_fact_reaffirmed_recently_survives_even_if_first_pinned_long_ago():
    """ts (original pin) being old must not evict a fact whose last_hit_ts
    (last reaffirmation) is recent."""
    wm = WorkingMemory()
    wm.pin("Long-standing but active fact", source="test", importance=0.3)
    fact = wm._facts[wm._key("Long-standing but active fact")]
    fact.ts = time.time() - (MAX_AGE_SECONDS * 5)  # ancient original pin
    fact.last_hit_ts = time.time()                  # but touched just now

    wm.advance_turn()

    assert wm._key("Long-standing but active fact") in wm._facts
