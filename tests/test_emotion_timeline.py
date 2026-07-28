"""Emotion timeline — persistence, baseline, and the proactive check-in gates.

Isolation: conftest points ELI_ARTIFACTS_DIR at the in-project .pytest_artifacts
tree, so these write to a throwaway user.sqlite3 and never touch the live store.
Each test clears the table first — run-length and baseline maths are counts, so
leftover rows from a sibling test would silently change the answer.
"""
import time

import pytest

from eli.cognition import emotion_timeline as et


def _clear():
    conn = et._connect()
    try:
        et._ensure(conn)
        conn.execute("DELETE FROM emotion_events")
        conn.commit()
    finally:
        conn.close()
    # The module dedupes identical consecutive reads; reset so tests are independent.
    et._last_key = ""
    et._last_key_ts = 0.0
    p = et._cooldown_path()
    if p.exists():
        p.unlink()


@pytest.fixture(autouse=True)
def clean_slate():
    _clear()
    yield
    _clear()


def _seed(emotion, n, *, user_id="u1", confidence=0.8, action="", prefix="turn"):
    """Write n reads, each with distinct text so the dedupe guard lets them through."""
    for i in range(n):
        assert et.record(emotion, expressed="calm", confidence=confidence,
                         source="fused", user_text=f"{prefix}-{emotion}-{i}",
                         user_id=user_id, eli_prior_action=action)
        time.sleep(0.002)  # keep ts strictly increasing


# ── Storage ───────────────────────────────────────────────────────────────────
def test_record_and_read_back():
    assert et.record("irritated", expressed="calm", confidence=0.7, source="text",
                     user_text="ugh this again", user_id="u1")
    rows = et.recent(limit=5, user_id="u1")
    assert len(rows) == 1
    assert rows[0]["detected"] == "irritated"
    assert rows[0]["valence"] == "negative"
    assert rows[0]["user_text"] == "ugh this again"


def test_dedupe_blocks_double_write_for_one_turn():
    """_build_enhanced_system can run twice per turn; the read must count once."""
    assert et.record("sad", user_text="same utterance", user_id="u1", confidence=0.8)
    assert not et.record("sad", user_text="same utterance", user_id="u1", confidence=0.8)
    assert len(et.recent(user_id="u1")) == 1


def test_empty_emotion_is_not_recorded():
    assert not et.record("", user_text="x", user_id="u1")
    assert et.recent(user_id="u1") == []


def test_reads_come_back_newest_first_within_one_second():
    for i, emo in enumerate(["calm", "happy", "sad"]):
        et.record(emo, user_text=f"t{i}", user_id="u1", confidence=0.8)
    rows = et.recent(user_id="u1")
    assert [r["detected"] for r in rows] == ["sad", "happy", "calm"]


def test_user_scoping():
    _seed("happy", 2, user_id="alice")
    _seed("sad", 3, user_id="bob")
    assert len(et.recent(user_id="alice")) == 2
    assert len(et.recent(user_id="bob")) == 3


# ── Valence ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("emotion,expected", [
    ("sad", "negative"), ("angry", "negative"), ("irritated", "negative"),
    ("happy", "positive"), ("joyful", "positive"), ("ecstatic", "positive"),
    ("neutral", "neutral"), ("calm", "neutral"), ("professional", "neutral"),
    ("something_unknown", "neutral"),
])
def test_valence_classification(emotion, expected):
    assert et.valence_of(emotion) == expected


# ── The check-in gates ────────────────────────────────────────────────────────
def test_single_spike_does_not_trigger_checkin():
    """One bad sentence is not a mood — this is the guard against nagging."""
    _seed("calm", 4)
    _seed("irritated", 1)
    a = et.assess(user_id="u1")
    assert a["state"] == "negative"
    assert a["run_length"] == 1
    assert not a["should_checkin"]
    assert "spike" in a["reason"]


def test_sustained_negative_run_triggers_checkin():
    _seed("irritated", et.SUSTAINED_MIN_READS)
    a = et.assess(user_id="u1")
    assert a["state"] == "negative"
    assert a["run_length"] >= et.SUSTAINED_MIN_READS
    assert a["dominant"] == "irritated"
    assert a["should_checkin"]


def test_sustained_positive_run_triggers_checkin():
    _seed("joyful", et.SUSTAINED_MIN_READS)
    a = et.assess(user_id="u1")
    assert a["state"] == "positive"
    assert a["should_checkin"]


def test_low_confidence_run_does_not_trigger():
    _seed("sad", et.SUSTAINED_MIN_READS + 1, confidence=0.1)
    a = et.assess(user_id="u1")
    assert not a["should_checkin"]
    assert "confidence" in a["reason"]


def test_neutral_state_never_triggers():
    _seed("neutral", 6)
    a = et.assess(user_id="u1")
    assert a["state"] == "neutral"
    assert not a["should_checkin"]


def test_cooldown_blocks_a_second_checkin():
    _seed("angry", et.SUSTAINED_MIN_READS + 1)
    assert et.assess(user_id="u1")["should_checkin"]
    et.note_checkin("negative", "angry")
    a = et.assess(user_id="u1")
    assert not a["should_checkin"]
    assert "cooldown" in a["reason"]


def test_no_reads_is_reported_not_guessed():
    a = et.assess(user_id="nobody")
    assert not a["should_checkin"]
    assert a["state"] == ""
    assert "no reads" in a["reason"]


# ── Transition + antecedent ───────────────────────────────────────────────────
def test_transition_and_trigger_action_are_captured():
    """The whole point of 'was it something I did' — the action at the turn it turned."""
    _seed("calm", 3, action="CHAT")
    _seed("irritated", et.SUSTAINED_MIN_READS, action="OPEN_APP")
    a = et.assess(user_id="u1")
    assert a["transition"] == {"from": "neutral", "to": "negative"}
    assert a["trigger_action"] == "OPEN_APP"
    assert a["trigger_text"]


# ── Baseline ──────────────────────────────────────────────────────────────────
def test_baseline_is_not_credible_without_enough_history():
    _seed("happy", 3)
    b = et.baseline("u1")
    assert b["reads"] == 3
    assert not b["credible"]


def test_baseline_credible_and_dominant():
    _seed("calm", et.BASELINE_MIN_READS + 2)
    b = et.baseline("u1")
    assert b["credible"]
    assert b["dominant"] == "calm"
    assert b["negative_share"] == 0.0


def test_negative_run_is_unusual_for_a_normally_calm_user():
    _seed("calm", et.BASELINE_MIN_READS + 2, prefix="base")
    _seed("irritated", et.SUSTAINED_MIN_READS, prefix="now")
    a = et.assess(user_id="u1")
    assert a["baseline"]["credible"]
    assert a["unusual"]
    assert a["should_checkin"]


def test_negative_run_is_not_unusual_for_a_habitually_negative_user():
    """Someone whose baseline IS negative must not be flagged as a change."""
    _seed("irritated", et.BASELINE_MIN_READS + 2, prefix="base")
    a = et.assess(user_id="u1")
    assert a["baseline"]["credible"]
    assert not a["unusual"]


# ── Model-facing output ───────────────────────────────────────────────────────
def test_evidence_block_empty_when_no_checkin_warranted():
    _seed("calm", 2)
    assert et.evidence_block(user_id="u1") == ""


def test_evidence_block_states_measurement_and_delegates_wording():
    _seed("irritated", et.SUSTAINED_MIN_READS + 1, action="RUN_CMD")
    block = et.evidence_block(user_id="u1")
    assert block
    assert "irritated" in block
    # It must hand the decision to the model, not script a reply.
    assert "your own words" in block
    assert "Never quote these numbers" in block
    # And it must not contain a ready-made sentence for ELI to parrot.
    assert "You seem" not in block


def test_trend_line_reports_sequence_oldest_to_newest():
    for i, emo in enumerate(["calm", "irritated", "angry"]):
        et.record(emo, user_text=f"s{i}", user_id="u1", confidence=0.8)
        time.sleep(0.002)
    line = et.trend_line(user_id="u1")
    assert "calm → irritated → angry" in line


def test_trend_line_silent_on_all_neutral():
    _seed("neutral", 4)
    assert et.trend_line(user_id="u1") == ""


def test_trend_line_needs_more_than_one_read():
    _seed("sad", 1)
    assert et.trend_line(user_id="u1") == ""


# ── Kill switch ───────────────────────────────────────────────────────────────
def test_disabled_records_nothing_and_asserts_nothing(monkeypatch):
    monkeypatch.setenv("ELI_EMOTION_MEMORY", "0")
    assert not et.enabled()
    assert not et.record("angry", user_text="off", user_id="u1")
    assert et.recent(user_id="u1") == []
    a = et.assess(user_id="u1")
    assert not a["should_checkin"]
    assert a["reason"] == "disabled"
