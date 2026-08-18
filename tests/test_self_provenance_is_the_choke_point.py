"""One place decides what counts as ELI's own record-keeping.

Three times in two days the same defect shipped, each fixed separately:

  * reflection telemetry stored under a kind/source chosen to dodge the recall
    filter — 94% of everything ELI could recall about itself was its own failure
    counts, and a greeting came back "I'm a patch job, a walking glitch";
  * the insight synthesiser handed ten rows of "Proactive daemon started" and
    asked to reflect on its own recent activity — which it did, every 30
    minutes, all night;
  * the proactive daemon counting words from its own event log and reporting
    "afternoon (x11)" as the operator's foremost interest.

The fixes lived in four modules using four mechanisms: a source tuple in
memory.py, a category set in insight_synthesis.py, tag substrings in
proactive_daemon.py, a stopword list in reflection.py. Nothing connected them,
so a fourth instance was a matter of time — any new reader that asks a store
"what do I know" inherits the bug by default, because the default is to see
everything.

eli/core/self_provenance.py is now the choke point. These tests assert the call
sites consult it rather than carrying private copies, so the next reader that
forgets is a failing test rather than a shipped release.
"""
from __future__ import annotations

import inspect

import pytest

from eli.core import self_provenance as sp


# ── the predicate answers for every substrate ──────────────────────────────
@pytest.mark.parametrize("row", [
    {"category": "proactive_pattern_tick", "observation": '{"patterns": []}'},
    {"category": "runtime", "observation": "pattern_summary"},
    {"category": "system", "observation": "Proactive daemon started"},
    {"category": "world_autonomy", "observation": "[world_suggestion] SELF_IMPROVE"},
    {"category": "habit_detector", "observation": "Persona auto-overlay cleaned: pruned."},
    {"category": "anything", "observation": '{"patterns": [{"type": "topic_focus"}]}'},
])
def test_bookkeeping_observations_are_recognised(row):
    assert sp.is_bookkeeping_observation(row)
    assert sp.observation_text(row) == ""


def test_a_genuine_observation_is_not_bookkeeping():
    row = {"category": "habit_detector",
           "observation": "User analysed three PDFs in the QMSH project"}
    assert not sp.is_bookkeeping_observation(row)
    assert "QMSH" in sp.observation_text(row)


@pytest.mark.parametrize("row", [
    {"kind": "reflection", "text": "Reflection (24h): ..."},
    {"kind": "episodic", "text": "..."},
    {"source": "eli_reflection", "text": "Top topics: stop, glitchy"},
    {"source": "orchestrator", "text": "..."},
    {"tags": "reflection,auto", "text": "..."},
    {"tags": "session_summary", "text": "..."},
])
def test_bookkeeping_memories_are_recognised(row):
    assert sp.is_bookkeeping_memory(row)


def test_a_user_fact_is_not_bookkeeping():
    assert not sp.is_bookkeeping_memory(
        {"kind": "memory", "source": "user", "tags": "user_fact",
         "text": "my dog is called Biscuit"})


def test_world_autonomy_notes_stay_recallable_as_memories():
    """A deliberate asymmetry, recorded rather than lost in the merge: an
    autonomy note describes something that happened, so it remains a recallable
    memory even though it is not reflection material as an observation."""
    assert "eli_world" not in sp.MEMORY_SOURCES
    assert not sp.is_bookkeeping_memory(
        {"kind": "insight", "source": "eli_world", "tags": "eli_autonomy"})
    assert sp.is_bookkeeping_observation({"category": "world_autonomy"})


def test_meta_actions_are_recognised():
    assert sp.is_meta_action("SELF_REPORT")
    assert sp.is_meta_action("chat")
    assert not sp.is_meta_action("ANALYZE_PDF")


def test_auto_tags_are_recognised():
    assert sp.has_auto_tag("eli_insight,auto")
    assert sp.has_auto_tag("news")
    assert not sp.has_auto_tag("user_fact")


# ── the SQL form matches the Python form ───────────────────────────────────
def test_sql_fragment_binds_one_parameter_per_placeholder():
    sql, params = sp.memory_exclusion_sql(
        {"kind", "source", "tags", "text", "content"}, alias="m.")
    assert sql.count("?") == len(params)


def test_both_alias_forms_bind_the_same_parameters():
    """They were written out twice by hand and had to be kept in step."""
    cols = {"kind", "source", "tags", "text", "content"}
    _, p_aliased = sp.memory_exclusion_sql(cols, alias="m.")
    _, p_plain = sp.memory_exclusion_sql(cols, alias="")
    assert p_aliased == p_plain


def test_sql_excludes_every_kind_source_and_tag_the_predicate_knows():
    sql, params = sp.memory_exclusion_sql(
        {"kind", "source", "tags", "text", "content"}, alias="")
    for k in sp.MEMORY_KINDS:
        assert k in params
    for s in sp.MEMORY_SOURCES:
        assert s in params
    for marker in sp.MEMORY_TAG_MARKERS:
        assert f"'%{marker}%'" in sql
    assert str(sp.MEMORY_MAX_CHARS) in sql


def test_the_reflection_source_is_excluded():
    """The row that let 94% of recall become telemetry."""
    _, params = sp.memory_exclusion_sql({"kind", "source", "tags"}, alias="")
    assert "eli_reflection" in params


def test_missing_columns_degrade_to_a_valid_fragment():
    """Older databases lack kind/source/tags entirely."""
    sql, params = sp.memory_exclusion_sql(set(), alias="")
    assert sql.count("?") == len(params)
    assert "COALESCE(kind" not in sql


# ── the call sites must consult it ─────────────────────────────────────────
CALL_SITES = [
    ("eli.memory.memory", "memory_exclusion_sql"),
    ("eli.planning.insight_synthesis", "observation_text"),
    ("eli.planning.proactive_daemon", "has_auto_tag"),
    ("eli.runtime.reflection", "is_meta_action"),
]


@pytest.mark.parametrize("module_name,symbol", CALL_SITES)
def test_call_sites_import_from_the_choke_point(module_name, symbol):
    module = __import__(module_name, fromlist=["_"])
    src = inspect.getsource(module)
    assert "self_provenance" in src, f"{module_name} does not consult the choke point"
    assert symbol in src, f"{module_name} does not use {symbol}"


@pytest.mark.parametrize("module_name,_symbol", CALL_SITES)
def test_call_sites_do_not_redefine_the_vocabulary(module_name, _symbol):
    """A private copy is how the four mechanisms diverged in the first place."""
    module = __import__(module_name, fromlist=["_"])
    src = inspect.getsource(module)
    for banned in ("_PLUMBING_CATEGORIES =", "_PLUMBING_PREFIXES =",
                   "_AUTO_TAG_MARKERS =", "_noise_kinds =", "_noise_sources ="):
        assert banned not in src, f"{module_name} still defines {banned.strip(' =')}"


def test_the_module_has_no_heavy_imports():
    """It is imported from memory, planning and runtime — it must not drag the
    engine in behind it or create a cycle."""
    src = inspect.getsource(sp)
    for banned in ("from eli.kernel", "import eli.kernel",
                   "from eli.memory", "from eli.cognition"):
        assert banned not in src


# ── retention ──────────────────────────────────────────────────────────────
def test_bookkeeping_is_capped_far_below_genuine_observations():
    assert sp.observation_retention_limit("proactive_pattern_tick") == \
        sp.OBSERVATION_RETENTION_BOOKKEEPING
    assert sp.observation_retention_limit("habit_detector") == \
        sp.OBSERVATION_RETENTION_DEFAULT
    assert sp.OBSERVATION_RETENTION_BOOKKEEPING < sp.OBSERVATION_RETENTION_DEFAULT


def test_observations_stop_growing_without_bound():
    """The daemon appends one per tick forever and nothing ever removed one:
    a live store held 220 rows, 104 of them `proactive_pattern_tick`."""
    import sqlite3

    from eli.memory import get_memory
    from eli.memory.memory import _OBS_PRUNE_EVERY

    mem = get_memory()
    cap = sp.OBSERVATION_RETENTION_BOOKKEEPING
    for i in range(cap + 2 * _OBS_PRUNE_EVERY + 10):
        mem.add_observation("proactive_pattern_tick", '{"patterns": [], "ts": %d}' % i)

    con = sqlite3.connect(f"file:{mem.db_path}?mode=ro", uri=True)
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM observations "
            "WHERE LOWER(COALESCE(category,'')) = 'proactive_pattern_tick'"
        ).fetchone()[0]
    finally:
        con.close()
    # Pruning is throttled, so the count is bounded rather than exact.
    assert n <= cap + _OBS_PRUNE_EVERY, f"observations grew unbounded: {n}"


def test_pruning_keeps_the_newest_rows():
    import sqlite3

    from eli.memory import get_memory
    from eli.memory.memory import _prune_observations

    mem = get_memory()
    marker = "NEWEST-ROW-MARKER"
    mem.add_observation("proactive_pattern_tick", marker)
    conn = sqlite3.connect(str(mem.db_path))
    try:
        _prune_observations(conn, "proactive_pattern_tick")
        found = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE observation = ?", (marker,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert found == 1, "pruning discarded the most recent observation"


def test_pruning_never_evicts_another_category():
    """Per-category, so a flood of daemon ticks cannot push out a real one."""
    import sqlite3

    from eli.memory import get_memory
    from eli.memory.memory import _prune_observations

    mem = get_memory()
    mem.add_observation("habit_detector", "a genuine observation worth keeping")
    conn = sqlite3.connect(str(mem.db_path))
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM observations "
            "WHERE LOWER(COALESCE(category,'')) = 'habit_detector'"
        ).fetchone()[0]
        for _ in range(5):
            _prune_observations(conn, "proactive_pattern_tick")
        after = conn.execute(
            "SELECT COUNT(*) FROM observations "
            "WHERE LOWER(COALESCE(category,'')) = 'habit_detector'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert after == before
