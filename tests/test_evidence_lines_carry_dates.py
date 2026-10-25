"""Evidence reaches the model with a date, weekday and age."""
import time

from eli.cognition.evidence_format import age_label, row_time, when_label

NOW = time.mktime(time.strptime("2026-09-25 12:00", "%Y-%m-%d %H:%M"))


def _ts(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))


def test_age_labels():
    assert age_label(_ts("2026-09-25 01:00"), NOW) == "today"
    assert age_label(_ts("2026-09-24 23:59"), NOW) == "yesterday"
    assert age_label(_ts("2026-09-20 09:00"), NOW) == "5 days ago"
    assert age_label(_ts("2026-09-04 09:00"), NOW) == "3 weeks ago"
    assert age_label(_ts("2026-05-01 09:00"), NOW).endswith("months ago")


def test_weekday_comes_from_the_timestamp():
    # 2026-08-24 was a Monday
    assert when_label(_ts("2026-08-24 19:01"), NOW).startswith("2026-08-24 Mon")


def test_a_month_old_quote_is_not_labelled_recent():
    label = when_label(_ts("2026-08-24 19:01"), NOW)
    assert "days ago" in label or "weeks ago" in label
    assert "today" not in label and "yesterday" not in label


def test_missing_time_gives_no_label():
    assert when_label(None) == "" and when_label(0) == "" and when_label("x") == ""


def test_row_time_prefers_the_event_time():
    assert row_time({"event_ts": 5.0, "ts": 9.0}) == 5.0
    assert row_time({"ts": 9.0}) == 9.0
    assert row_time({"timestamp": 7.0}) == 7.0
    assert row_time("nope") is None


def test_the_engine_prints_dates_on_ranked_hits_and_turns():
    import inspect
    from eli.kernel import engine as eng
    src = inspect.getsource(eng.CognitiveEngine.assemble_precise_context)
    assert "when_label" in src


def test_an_older_summary_says_which_night_it_meant():
    """A 15 October summary said "up late last night"; read on 20 October ELI said the user had been
    up late last night."""
    from eli.cognition.evidence_format import as_of, dated
    then, now = _ts("2026-10-15 18:24"), _ts("2026-10-20 11:02")
    out = dated("The user was up late (home well after midnight last night); today they are currently busy.", then, now)
    assert out.startswith("[Thu 15 Oct 18:24, 5 days ago]")
    assert "last night" not in out and "the night before Thu 15 Oct" in out
    assert "today" not in out and "currently" not in out
    assert as_of("today I feel fine", now - 60, now) == "today I feel fine"     # today's words are right as they are


def test_a_memory_stored_again_keeps_the_date_it_was_said():
    """A memory re-pinned on 24 Sep (ts) was said on 14 Sep (event_ts); the verified-memory block showed
    24 Sep, and ELI gave that as the day the user had said it."""
    from eli.memory.retrieval import TurnRetrievalResult
    from eli.memory.unified_retrieval import format_verified_memory_block
    said, stored = _ts("2026-09-14 13:22"), _ts("2026-09-24 13:10")
    hit = {"id": 1, "text": "my plans moved from saturday to monday", "ts": stored, "timestamp": stored,
           "event_ts": said, "importance": 0.8, "provenance_kind": "user_verbatim", "verification_status": "verified"}
    block = format_verified_memory_block(TurnRetrievalResult(semantic_hits=[hit]))
    assert "2026-09-14 13:22" in block and "2026-09-24" not in block


def test_a_fact_says_when_its_own_time_words_were_true(tmp_path):
    """A fact recorded on 16 Oct, "recently took a trip ... approximately two weeks ago", sat in the profile
    and the graph undated: five days later ELI asked how the drive was going."""
    import sqlite3
    from eli.cognition.user_info_builder import _categorise_semantic
    from eli.memory.knowledge_graph import KnowledgeGraph
    recorded = _ts("2026-10-16 19:41")
    fact = "User recently took a trip to the coast approximately two weeks ago."
    lines = [l for ls in _categorise_semantic([{"fact": fact, "tags": "identity.fact", "confidence": 0.8,
                                                "created_at": str(recorded)}]).values() for l in ls]
    assert lines == ["User shortly before Fri 16 Oct took a trip to the coast around 02 Oct 2026."]

    kg = KnowledgeGraph(db_path=tmp_path / "kg.sqlite3")
    kg.add_relation("User", "is", "currently driving to the coast", source="user")
    with sqlite3.connect(tmp_path / "kg.sqlite3") as c:
        c.execute("UPDATE kg_relations SET ts = ?", (recorded,))
    with sqlite3.connect(tmp_path / "kg.sqlite3") as c:
        c.execute("UPDATE kg_entities SET ts = ?", (recorded,))
    ctx = kg.context_for_prompt("what is the user doing")
    assert "User —[is]→ at the time (Fri 16 Oct) driving to the coast (as of 16 Oct 2026)" in ctx, ctx
    assert "currently" not in ctx
