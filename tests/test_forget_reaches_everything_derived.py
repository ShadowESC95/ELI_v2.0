"""Forgetting a memory removes it and what was made from it: index entries, claims, summaries, profile items, stances, graph, turns."""
import json
import sqlite3
import time

import pytest

from eli.memory.memory import Memory


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    return Memory(db_path=tmp_path / "user.sqlite3")


def _q(mem, sql, *a):
    c = sqlite3.connect(mem.db_path)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def _seed(mem):
    text = "I live in Lisbon and the spare key code is ORCHID-7319 for my sister Priya"
    rid = mem.store_memory(text, source="user")["id"]
    other = mem.store_memory("I prefer green tea with a slice of ginger every afternoon", source="user")["id"]
    child = mem.store_memory("Summary: the user has a spare key code ORCHID-7319", source="assistant", kind="summary")["id"]
    mem.link_derivation(child, [rid], "summary")
    from eli.cognition.stance_store import ensure_tables
    from eli.runtime.profile_extractor import ensure_profile_tables
    from eli.runtime.user_model import ensure_user_model_row
    ensure_profile_tables(mem.db_path)
    ensure_user_model_row("u", mem.db_path)
    mem.save_session_summary("s", "u", summary="They shared the key code ORCHID-7319 and Priya", turns_count=2)
    mem.save_session_summary("s2", "u", summary="They talked about tea and gardening", turns_count=2)
    c = sqlite3.connect(mem.db_path)
    ensure_tables(c.cursor())
    now = time.time()
    c.execute("insert into semantic (user_id, fact, evidence, evidence_count, created_at) values ('u', 'Has a spare key', ?, 1, ?)",
              (json.dumps([text]), now))
    c.execute("insert into semantic (user_id, fact, evidence, evidence_count, created_at) values ('u', 'Likes green tea', ?, 1, ?)",
              (json.dumps(["I prefer green tea with a slice of ginger every afternoon"]), now))
    c.execute("update user_model set brief = 'Key code ORCHID-7319 kept for Priya', dossier = 'Likes tea' where user_id = 'u'")
    c.execute("insert into eli_stances (topic, position) values ('key code', 'ORCHID-7319 is not to be shared')")
    c.execute("insert into conversation_turns (session_id, user_id, role, content, ts, timestamp) values ('s','u','user',?,?,?)", (text, now, now))
    c.commit()
    c.close()
    return rid, other, child, text


def test_forget_removes_the_memory_and_everything_made_from_it(mem):
    rid, other, child, text = _seed(mem)
    report = mem.forget([rid])
    assert report["memories"] == 2 and report["derived"] == 1
    assert report["claims"] >= 1 and report["semantic"] == 1 and report["summaries"] == 1
    assert report["profile"] == 1 and report["stances"] == 1 and report["turns"] == 1
    assert not _q(mem, "select id from memories where id in (?, ?)", rid, child)
    assert not _q(mem, "select child_id from memory_lineage")
    assert [r[0] for r in _q(mem, "select fact from semantic")] == ["Likes green tea"]
    assert [r[0] for r in _q(mem, "select summary from session_summaries")] == ["They talked about tea and gardening"]
    brief, dossier = _q(mem, "select brief, dossier from user_model")[0]
    assert not brief and dossier == "Likes tea"
    assert mem.claims_current() == []
    assert _q(mem, "select id from memories where id = ?", other)


def test_forget_leaves_unrelated_memories_and_can_be_repeated(mem):
    rid, other, _child, _text = _seed(mem)
    mem.forget([rid])
    again = mem.forget([rid])
    assert again["memories"] == 0
    assert mem.recall_memory("green tea ginger", limit=3)


def test_a_summary_of_a_fact_is_not_independent_evidence(mem):
    a = mem.store_memory("The lease starts in March according to the landlord letter", source="user")["id"]
    b = mem.store_memory("Summary of the letter: the lease starts in March", source="assistant", kind="summary")["id"]
    c = mem.store_memory("A second separate note says the lease starts in March", source="user")["id"]
    mem.link_derivation(b, [a], "summary")
    assert mem.lineage_root(b) == a
    assert mem.independent_sources([a, b]) == 1
    assert mem.independent_sources([a, b, c]) == 2


def test_forget_candidates_lists_what_would_go(mem):
    rid, *_ = _seed(mem)
    assert rid in [c["id"] for c in mem.forget_candidates("spare key code ORCHID-7319")]


def test_forget_erases_claim_payloads(mem):
    rid, _other, _child, _text = _seed(mem)

    # Verify that the test has source-linked claims to examine.
    before = _q(
        mem,
        "SELECT id FROM memory_claims WHERE source_memory_id = ?",
        rid,
    )

    assert before, "Fixture did not create any source-linked claims"

    mem.forget([rid])

    retained = _q(
        mem,
        """
        SELECT id, status, value, source_text
        FROM memory_claims
        WHERE source_memory_id = ?
          AND (
              COALESCE(value, '') <> ''
              OR COALESCE(source_text, '') <> ''
          )
        """,
        rid,
    )

    assert retained == [], (
        "Forgotten memory still has persisted claim content"
    )


def test_forget_preserves_independent_same_topic_summary(mem):
    rid, _other, _child, _text = _seed(mem)

    # Independent conversation summary.
    # Shares names with the forgotten memory but not its secret.
    independent = "Priya enjoyed a weekend in Lisbon"

    mem.save_session_summary(
        "independent-session",
        "u",
        summary=independent,
        turns_count=1,
    )

    # Verify the independent information exists before deletion.
    before = [
        row[0]
        for row in _q(
            mem,
            "SELECT summary FROM session_summaries",
        )
    ]

    assert independent in before

    # Forget the original memory containing the private key code.
    mem.forget([rid])

    remaining = [
        row[0]
        for row in _q(
            mem,
            "SELECT summary FROM session_summaries",
        )
    ]

    assert independent in remaining, (
        "Forgetting deleted an independent summary "
        "because it shared names with the forgotten memory"
    )


def test_forget_preserves_independently_supported_claim(mem):
    from eli.memory import claims

    first = mem.store_memory(
        "My preferred coding font is Fira Code.",
        source="user",
    )["id"]

    second = mem.store_memory(
        "I independently confirm that Fira Code is my coding font.",
        source="user",
    )["id"]

    assert first != second

    conn = sqlite3.connect(mem.db_path)

    try:
        a = claims.record(
            conn,
            "audit_coding_font",
            "Fira Code",
            source_memory_id=first,
            source_text="My preferred coding font is Fira Code.",
            root_id=first,
        )

        b = claims.record(
            conn,
            "audit_coding_font",
            "Fira Code",
            source_memory_id=second,
            source_text="Independent confirmation of Fira Code.",
            root_id=second,
        )

        assert a == b

        roots = json.loads(
            conn.execute(
                "SELECT source_roots FROM memory_claims WHERE id = ?",
                (a,),
            ).fetchone()[0]
        )

        assert set(roots) == {first, second}
        conn.commit()

    finally:
        conn.close()

    # Forget only the first source.
    mem.forget([first])

    remaining = _q(
        mem,
        """
        SELECT source_roots, source_text
        FROM memory_claims
        WHERE relation = 'audit_coding_font'
        """
    )

    assert remaining, (
        "Forgetting one source deleted a claim "
        "supported by an independent source"
    )

    roots_after = json.loads(remaining[0][0])

    assert second in roots_after
    assert first not in roots_after

    assert "My preferred coding font is Fira Code." not in (
        remaining[0][1] or ""
    )


def test_forget_second_support_preserves_original_claim(mem):
    from eli.memory import claims

    first = mem.store_memory(
        "My coding font is Fira Code.",
        source="user",
    )["id"]

    second = mem.store_memory(
        "I confirm that Fira Code is my coding font.",
        source="user",
    )["id"]

    conn = sqlite3.connect(mem.db_path)

    try:
        claims.record(
            conn,
            "audit_font_secondary",
            "Fira Code",
            source_memory_id=first,
            source_text="My coding font is Fira Code.",
            root_id=first,
        )

        claims.record(
            conn,
            "audit_font_secondary",
            "Fira Code",
            source_memory_id=second,
            source_text="Independent confirmation.",
            root_id=second,
        )

        conn.commit()
    finally:
        conn.close()

    mem.forget([second])

    rows = _q(
        mem,
        """
        SELECT source_memory_id, source_roots, source_text
        FROM memory_claims
        WHERE relation = 'audit_font_secondary'
        """
    )

    assert len(rows) == 1

    source_id, roots_json, source_text = rows[0]

    assert source_id == first
    assert json.loads(roots_json) == [first]
    assert source_text == "My coding font is Fira Code."


def test_forget_takes_a_summary_of_the_conversation_it_was_said_in(mem):
    """Names shared with the forgotten words are enough when the summary sums up the conversation they were said in."""
    rid, *_ = _seed(mem)
    mem.save_session_summary("s", "u", summary="Priya is moving to Lisbon in spring", turns_count=2)
    mem.forget([rid])
    assert "Priya is moving to Lisbon in spring" not in [r[0] for r in _q(mem, "select summary from session_summaries")]


def test_forget_takes_a_summary_without_a_conversation_record(mem):
    """No turns table to say where it was said: a summary that holds the forgotten code still goes."""
    rid = mem.store_memory("The locker combination is TULIP-4482", source="user")["id"]
    mem.save_session_summary("x", "u", summary="They noted locker combination TULIP-4482", turns_count=1)
    c = sqlite3.connect(mem.db_path)
    c.execute("drop table if exists conversation_turns")
    c.commit()
    c.close()
    assert mem.forget([rid])["summaries"] == 1
