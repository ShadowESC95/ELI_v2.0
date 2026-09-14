"""Regression: do not volunteer stale plans into unrelated turns."""
from __future__ import annotations

from eli.cognition.personal_context_gate import (
    asks_about_stored_personal_context,
    continuity_guard_block,
    extract_current_user_plan,
    looks_like_travel_or_schedule,
    strip_focus_lines_from_brief,
    strip_recalled_projects_from_profile_text,
)


def test_gpu_rant_does_not_count_as_personal_context():
    assert not asks_about_stored_personal_context(
        "you are not running 24 gpu layers you dipshit, that has changed!!"
    )
    assert not asks_about_stored_personal_context(
        "you need to stop referring to previous sessions as much as you do"
    )


def test_explicit_plan_questions_are_personal_context():
    assert asks_about_stored_personal_context("what are my plans tomorrow?")
    assert asks_about_stored_personal_context("do you remember my schedule?")
    assert asks_about_stored_personal_context("what do you know about me?")


def test_continuity_guard_present_unless_asked():
    guard = continuity_guard_block("how many gpu layers?")
    assert guard is not None
    assert "GPU layer" in guard
    assert continuity_guard_block("what are my plans?") is None


def test_extract_current_user_plan_galway_pickup():
    plan = extract_current_user_plan(
        "i am collecting colin in galway then bringing him back to wexford"
    )
    assert plan
    assert "colin" in plan.lower()
    assert "galway" in plan.lower()


def test_strip_focus_and_recalled_projects():
    brief = (
        "USER MODEL: Jay — prefers blunt\n"
        "Currently focused on: collect Colin Saturday in Wexford.\n"
        "Interests: GPUs.\n"
        "Goals: ship ELI.\n"
    )
    stripped = strip_focus_lines_from_brief(brief)
    assert "Currently focused" not in stripped
    assert "Goals:" not in stripped
    assert "Interests:" in stripped

    profile = (
        "Name: Jay\n"
        "Recalled past topics (previous sessions — not current request):\n"
        "  - Collect Colin in Wexford Saturday\n"
        "Recalled research areas (previous sessions):\n"
        "  - field theory\n"
        "Preferences:\n"
        "  - blunt\n"
    )
    cleaned = strip_recalled_projects_from_profile_text(profile)
    assert "Collect Colin" not in cleaned
    assert "field theory" not in cleaned
    assert "Name: Jay" in cleaned
    assert "blunt" in cleaned


def test_travel_schedule_detector():
    assert looks_like_travel_or_schedule("Collecting Colin in Galway tomorrow")
    assert not looks_like_travel_or_schedule("Debugging the memory system")


def test_travel_stale_faster_than_general_project(tmp_path, monkeypatch):
    import sqlite3
    import time
    import eli.runtime.profile_extractor as PE
    import eli.runtime.personal_memory_clean_response as PM

    db = tmp_path / "u.sqlite3"
    PE.ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    now = time.time()
    # 5 days old travel should drop (3d travel TTL); 5-day coding project stays (7d).
    PE._insert_user_pattern(
        cur,
        "project.trip",
        "User is collecting Colin in Galway tomorrow.",
        ts_value=now - 5 * 86400,
    )
    PE._insert_user_pattern(
        cur,
        "project.cur",
        "User is actively debugging the memory system.",
        ts_value=now - 5 * 86400,
    )
    con.commit()
    con.close()
    monkeypatch.setattr(PM, "USER_DB", db)
    monkeypatch.setattr(PM, "AGENT_DB", tmp_path / "a.sqlite3")
    facts, _ = PM._collect_facts()
    blob = " | ".join(facts)
    assert "Colin" not in blob
    assert "debugging the memory" in blob
