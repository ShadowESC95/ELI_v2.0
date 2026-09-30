"""A captured preferred name must not depend on persona.auto.txt's "User Preferences"
section — persona_updater.update_auto_sections() rebuilds that file from a fixed section
set that never includes user preferences, silently erasing anything written there."""
import sqlite3

import pytest

from eli.runtime.profile_extractor import _insert_user_pattern, ensure_profile_tables


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "user.sqlite3"
    ensure_profile_tables(path)
    con = sqlite3.connect(str(path))
    yield con
    con.close()


def test_preferred_name_is_stored_as_a_single_valued_pattern(db):
    cur = db.cursor()
    assert _insert_user_pattern(cur, "identity.preferred_name", "User prefers to be called Jay.",
                                provenance="user_explicit")
    db.commit()
    rows = db.execute(
        "SELECT pattern_data FROM user_patterns WHERE lower(pattern_type)=lower(?)",
        ("identity.preferred_name",),
    ).fetchall()
    assert rows and "Jay" in rows[0][0]


def test_a_persona_auto_txt_rebuild_does_not_touch_it(db, tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_PERSONA_AUTO_FILE", str(tmp_path / "persona.auto.txt"))
    cur = db.cursor()
    _insert_user_pattern(cur, "identity.preferred_name", "User prefers to be called Jay.",
                         provenance="user_explicit")
    db.commit()

    # Simulate persona_updater's real section set — it never includes "User Preferences"
    # (persona_updater.py:418-436) — this is the exact rebuild that used to wipe the name.
    from eli.cognition.persona import update_auto_sections
    update_auto_sections({"Runtime Persona Notes": "some other content"})

    rows = db.execute(
        "SELECT pattern_data FROM user_patterns WHERE lower(pattern_type)=lower(?)",
        ("identity.preferred_name",),
    ).fetchall()
    assert rows and "Jay" in rows[0][0]


def test_correcting_the_name_supersedes_not_accumulates(db):
    cur = db.cursor()
    _insert_user_pattern(cur, "identity.preferred_name", "User prefers to be called Jay.",
                         provenance="user_explicit")
    db.commit()
    _insert_user_pattern(cur, "identity.preferred_name", "User prefers to be called James.",
                         provenance="user_explicit")
    db.commit()
    rows = db.execute(
        "SELECT pattern_data FROM user_patterns WHERE lower(pattern_type)=lower(?)",
        ("identity.preferred_name",),
    ).fetchall()
    assert len(rows) == 1
    assert "James" in rows[0][0]
