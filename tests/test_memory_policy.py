"""The rules for what is stored, how strong it stays, and what is archived."""
import math

from eli.memory import policy as P

DAY = 86400.0
NOW = 1_800_000_000.0


# ── origin ────────────────────────────────────────────────────────────────
def test_the_live_misfiled_rows_are_classified_correctly():
    assert P.classify_origin("eli_reflection", "insight", ["eli_insight", "auto"]) == P.ORIGIN_TELEMETRY
    # the reflection aggregate that was stored with the default source
    assert P.classify_origin("user", "memory", ["reflection", "auto"],
                             "Reflection (24h): Top topics: self, buddy") == P.ORIGIN_TELEMETRY
    assert P.classify_origin("news_synthesis", "news_reflection", []) == P.ORIGIN_NEWS
    assert P.classify_origin("session_end", "reflection", []) == P.ORIGIN_TELEMETRY
    assert P.classify_origin("awareness", "system", []) == P.ORIGIN_TELEMETRY
    assert P.classify_origin("assistant", "memory", []) == P.ORIGIN_ELI
    assert P.classify_origin("executor", "memory", []) == P.ORIGIN_TOOL


def test_what_the_user_said_is_the_user_s():
    assert P.classify_origin("user", "memory", [], "my cat is called Biscuit") == P.ORIGIN_USER
    assert P.classify_origin("conversation", "fact", []) == P.ORIGIN_USER
    assert P.classify_origin("working_memory", "fact", ["working_memory", "user_explicit"]) == P.ORIGIN_USER
    assert P.classify_origin("assistant", "memory", ["user_confirmed"]) == P.ORIGIN_USER


def test_only_the_users_words_are_evidence_about_the_user():
    assert P.counts_as_evidence_about_user(P.ORIGIN_USER)
    for o in (P.ORIGIN_ELI, P.ORIGIN_TELEMETRY, P.ORIGIN_NEWS, P.ORIGIN_TOOL):
        assert not P.counts_as_evidence_about_user(o)


def test_tallies_are_not_embedded():
    assert not P.wants_vector_index(P.ORIGIN_TELEMETRY)
    assert P.wants_vector_index(P.ORIGIN_USER)


# ── identity of a statement ──────────────────────────────────────────────
def test_text_key_ignores_case_and_punctuation():
    assert P.text_key("No, no -- I am your father!") == P.text_key("no no i am your FATHER")
    assert P.text_key("a") != P.text_key("b")
    assert P.text_key("   ") == ""


# ── strength ─────────────────────────────────────────────────────────────
def _s(days, imp=0.6, origin=P.ORIGIN_USER, seen=1, rec=0, half=30.0, pinned=False):
    return P.strength(NOW, NOW - days * DAY, imp, origin, seen, rec, half, pinned)


def test_strength_is_full_now_and_falls_with_time():
    assert _s(0) == 1.0
    assert _s(10) > _s(60) > _s(400)
    assert _s(10_000) == P.MIN_WEIGHT


def test_it_is_a_pure_function_of_its_inputs():
    assert _s(45) == _s(45)


def test_importance_slows_forgetting():
    assert _s(90, imp=0.9) > _s(90, imp=0.2)


def test_use_slows_forgetting():
    assert _s(90, seen=5) > _s(90)
    assert _s(90, rec=6) > _s(90)


def test_derived_rows_fade_faster_than_the_users_words():
    assert _s(30, origin=P.ORIGIN_TELEMETRY) < _s(30, origin=P.ORIGIN_NEWS) < _s(30, origin=P.ORIGIN_USER)


def test_important_user_facts_never_fade():
    assert _s(5000, imp=0.95) == 1.0
    assert _s(5000, pinned=True) == 1.0
    # importance alone doesn't pin ELI's own statements
    assert _s(5000, imp=0.95, origin=P.ORIGIN_TELEMETRY) < 1.0


def test_half_life_is_derived_from_usage():
    assert P.adaptive_half_life_days([1] * 20) == P.DEFAULT_HALF_LIFE_DAYS
    assert P.adaptive_half_life_days([14] * 20) > P.adaptive_half_life_days([1] * 20)
    assert P.adaptive_half_life_days([400] * 20) == P.MAX_HALF_LIFE_DAYS
    assert P.adaptive_half_life_days([1, 2]) == P.DEFAULT_HALF_LIFE_DAYS   # too little history
    assert math.isclose(P.adaptive_half_life_days([14] * 20), 30 * math.sqrt(14), rel_tol=1e-6)


# ── archive ──────────────────────────────────────────────────────────────
def test_nothing_the_user_said_is_ever_archived():
    assert not P.should_archive(P.ORIGIN_USER, 0.05, 0, 0.1)


def test_faded_unused_derived_rows_are_archived():
    assert P.should_archive(P.ORIGIN_TELEMETRY, 0.06, 0, 0.5)
    assert P.should_archive(P.ORIGIN_NEWS, P.ARCHIVE_WEIGHT, 0, 0.4)


def test_used_or_important_derived_rows_stay():
    assert not P.should_archive(P.ORIGIN_TELEMETRY, 0.06, 2, 0.5)
    assert not P.should_archive(P.ORIGIN_TELEMETRY, 0.06, 0, 0.9)
    assert not P.should_archive(P.ORIGIN_TELEMETRY, 0.5, 0, 0.5)


# ── merging duplicates ───────────────────────────────────────────────────
def test_a_merge_keeps_the_first_date_and_counts_every_sighting():
    m = P.merge_group([
        {"ts": 100.0, "seen_count": 1, "importance": 0.6},
        {"ts": 300.0, "seen_count": 2, "importance": 0.9, "recall_count": 3, "last_recalled": 250.0},
        {"ts": 200.0, "importance": 0.5},
    ])
    assert m["event_ts"] == 100.0
    assert m["last_seen"] == 300.0
    assert m["seen_count"] == 4
    assert m["importance"] == 0.9
    assert m["recall_count"] == 3 and m["last_recalled"] == 250.0
