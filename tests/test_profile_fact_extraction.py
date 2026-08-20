"""Durable user facts are captured from the session summary and accumulate.

The extraction funnel was the narrowest point in the whole memory system. On a
live machine 619 conversation turns and 441 memories produced **10**
user_patterns, 6 semantic facts and 27 KG entities — and everything downstream
inherits that, because promotion fans out from user_patterns.

Two causes, and neither was the promotion machinery:

  * `extract_patterns_from_text` matches about twenty fixed phrasings, and most
    emit a CANNED sentence — the same string whatever the user actually said — so
    hundreds of turns dedupe down to a handful of rows.
  * The LLM summariser already read the whole transcript, but the only things
    routed out of it were `project.current` and `preference.session`, both
    SINGLE-SLOT: deleted and rewritten every session, so they could never widen
    anything.

Facts now go to accumulating pattern types whose prefixes `_promote_to_semantic`
accepts, so a fact captured tonight reaches the semantic tier and the knowledge
graph without anything else changing.
"""
from __future__ import annotations

import sqlite3

import pytest

from eli.runtime import profile_extractor as PE


@pytest.fixture()
def cur(tmp_path):
    db = tmp_path / "user.sqlite3"
    PE.ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    yield con.cursor()
    con.commit()
    con.close()


def _patterns(cur):
    return [(r[0], r[1]) for r in cur.execute(
        "SELECT pattern_type, pattern_data FROM user_patterns").fetchall()]


# ── classification ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("line,expected", [
    ("User is called Jay by close colleagues", "identity.name"),
    ("User works as an independent physicist", "identity.role"),
    ("User lives in Dublin", "identity.location"),
    ("User researches entropy and coherence fields", "research.field"),
    ("User is building a solar-to-hydrogen prototype", "project.named"),
    ("User prefers assumptions challenged directly", "preference.stated"),
    ("User is interested in pulsed power electronics", "interest.explicit"),
])
def test_facts_route_to_promotable_types(line, expected):
    assert PE._fact_pattern_type(line) == expected


def test_unclassified_facts_are_still_kept():
    """Dropping a durable fact because no verb matched is worse than filing it
    under identity — which is a prefix the semantic promoter accepts."""
    t = PE._fact_pattern_type("User has two cats and a workshop in the garage")
    assert t == "identity.fact"
    assert t.startswith(PE._SEMANTIC_PATTERN_PREFIXES)


def test_every_route_target_reaches_the_semantic_tier():
    """If a route emitted a prefix _promote_to_semantic ignores, the fact would be
    captured and then silently stop at user_patterns."""
    for _pattern, ptype in PE._FACT_ROUTES:
        assert ptype.startswith(PE._SEMANTIC_PATTERN_PREFIXES), ptype
        assert not ptype.startswith(PE._SEMANTIC_PATTERN_EXCLUDE), ptype


def test_fact_types_are_not_single_valued():
    """Single-slot types are superseded on write. Facts must accumulate, or this
    change reproduces the exact bug it exists to fix."""
    accumulating = [t for _p, t in PE._FACT_ROUTES if t not in ("identity.name", "identity.role")]
    for t in accumulating:
        assert t not in PE._SINGLE_VALUED_PATTERNS, t
    assert "identity.fact" not in PE._SINGLE_VALUED_PATTERNS


# ── routing ──────────────────────────────────────────────────────────────────

def test_facts_are_written_as_separate_patterns(cur):
    n = PE._route_facts_to_patterns(cur, """
- User researches entropy and coherence fields
- User is building a solar-to-hydrogen electrolyser
- User is interested in pulsed power electronics
""")
    assert n == 3
    types = {t for t, _ in _patterns(cur)}
    assert {"research.field", "project.named", "interest.explicit"} <= types


def test_eli_talking_about_itself_is_not_a_user_fact(cur):
    """The live store was 38% ELI's own reflection telemetry. None of it is a
    fact about the user, and it must not reach the semantic tier."""
    n = PE._route_facts_to_patterns(cur, """
- ELI generated 4 artifacts this session
- User works on high-voltage pulsed power
- Reflection recorded a conversation volume of 12 messages
- The model failed to load with 33 gpu layers
""")
    assert n == 1
    assert len(_patterns(cur)) == 1
    assert "pulsed power" in _patterns(cur)[0][1]


def test_repeating_a_fact_does_not_duplicate_it(cur):
    text = "- User researches entropy and coherence fields"
    PE._route_facts_to_patterns(cur, text)
    PE._route_facts_to_patterns(cur, text)
    PE._route_facts_to_patterns(cur, text)
    assert len(_patterns(cur)) == 1


def test_bullet_markers_and_numbering_are_stripped(cur):
    PE._route_facts_to_patterns(cur, "1. User lives in Dublin\n* User studies physics\n")
    data = [d for _t, d in _patterns(cur)]
    assert all(not d[0].isdigit() and d[0] not in "-*•" for d in data), data


def test_empty_and_none_sections_write_nothing(cur):
    for text in ("", "none", "  ", "N/A", "not specified"):
        assert PE._route_facts_to_patterns(cur, text) == 0
    assert _patterns(cur) == []


def test_fragments_too_short_to_be_facts_are_skipped(cur):
    assert PE._route_facts_to_patterns(cur, "- ok\n- yes\n- 42\n") == 0


# ── the section is actually asked for and parsed ─────────────────────────────

def test_the_summary_parser_recognises_the_section():
    summary = (
        "SUMMARY: worked on the electrolyser.\n"
        "USER FACTS:\n- User is building a solar-to-hydrogen prototype\n"
        "CURRENT WORK: stack assembly\n"
    )
    sections = {m.group(1).upper().replace(" ", "_"): m.group(2).strip()
                for m in PE._SUMMARY_SECTION_RE.finditer(summary)}
    assert "USER_FACTS" in sections
    assert "solar-to-hydrogen" in sections["USER_FACTS"]
    assert sections["CURRENT_WORK"].startswith("stack assembly")


def test_the_model_is_asked_for_durable_facts_only():
    """The prompt must scope the section to the USER and to durable facts, or the
    model fills it with session mechanics."""
    import inspect
    src = inspect.getsource(PE._llm_summarise_session)
    assert "USER FACTS:" in src
    assert "durable" in src.lower()
    assert "ONLY from what the USER said" in src


def test_route_summary_writes_facts_end_to_end(cur):
    PE._route_summary_to_profile(cur, (
        "SUMMARY: a session.\n"
        "CURRENT WORK: building the electrolyser stack.\n"
        "USER FACTS:\n"
        "- User researches entropy and coherence fields\n"
        "- User is interested in pulsed power electronics\n"
    ))
    types = {t for t, _ in _patterns(cur)}
    assert "project.current" in types, "existing behaviour must be preserved"
    assert {"research.field", "interest.explicit"} <= types, "facts must be routed too"


# ── the canned-sentence problem ──────────────────────────────────────────────

def test_the_same_rule_on_different_statements_yields_different_rows():
    """Every preference rule emits a FIXED label. That is why hundreds of turns
    collapsed into ten rows: the string was byte-identical whatever the user
    said, so dedupe folded them all together. The label is kept (persona and
    proactive surfaces read it) but the user's own words are appended."""
    a = PE.extract_patterns_from_text("please be thorough")
    b = PE.extract_patterns_from_text(
        "I need you to be thorough about the electrolyser stack, the anode keeps failing")
    assert a and b
    assert a != b, "two different statements must not produce identical patterns"
    assert all("Said:" in d for _t, d in a + b)


def test_the_canned_label_survives_for_downstream_readers():
    got = dict(PE.extract_patterns_from_text("be meticulous please"))
    assert got["preference.detail"].startswith(
        "User prefers in-depth, meticulous, thorough responses.")


def test_evidence_is_absent_when_the_quote_is_too_short():
    assert PE._evidence("hi", None) == ""
    assert PE._evidence("", None) == ""


def test_evidence_does_not_start_or_end_mid_word():
    text = "I would really appreciate a thorough and complete answer to this question"
    import re as _re
    m = _re.search("thorough", text.lower())
    q = PE._evidence(text, m)
    assert q.startswith(' Said: "') and q.endswith('"')
    inner = q[len(' Said: "'):-1]
    assert inner in text, "the quote must be a verbatim span of what was said"
