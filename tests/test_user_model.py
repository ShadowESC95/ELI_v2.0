"""Continuous User Model + light onboarding — fully offline (temp DB + fake broker)."""
import sqlite3
import pytest

from eli.runtime.profile_extractor import ensure_profile_tables, _insert_user_pattern
from eli.runtime import user_model as um
from eli.onboarding import interview as iv


@pytest.fixture(autouse=True)
def _clean_onboarding_state():
    # The onboarding state file is global — never let it leak into other tests.
    iv.clear_onboarding_state()
    yield
    iv.clear_onboarding_state()


@pytest.fixture
def db(tmp_path, monkeypatch):
    p = tmp_path / "user.sqlite3"
    ensure_profile_tables(p)
    # Force a true blank slate: no stored name.
    monkeypatch.setattr("eli.kernel.state.get_user_name", lambda default="", user_id=None: "")
    return p


def _seed(db, ptype, data):
    con = sqlite3.connect(str(db)); cur = con.cursor()
    _insert_user_pattern(cur, ptype, data); con.commit(); con.close()


def test_blank_slate_brief_is_onboarding_nudge(db):
    assert um.get_user_brief(turn_count=0, db_path=db).startswith("ONBOARDING")
    assert um.get_user_brief(turn_count=9, db_path=db) == ""   # stops nudging later
    assert um.read_user_model(db_path=db)["is_seeded"] is False


def test_seeded_patterns_render_a_brief(db):
    _seed(db, "identity.role", "User is a physicist.")
    _seed(db, "preference.style", "User prefers terse, direct answers.")
    brief = um.get_user_brief(turn_count=0, db_path=db)
    assert "USER MODEL" in brief and "physicist" in brief and "terse" in brief
    assert um.read_user_model(db_path=db)["is_seeded"] is True


def test_synthesize_consolidates_with_fake_broker(db):
    _seed(db, "project.current", "Tuning a scalar-field simulation.")

    class FakeBroker:
        gguf_ready = True
        def infer(self, prompt, system="", max_tokens=0, temperature=0, top_p=0,
                  background=False, retry=True):
            return "A physicist focused on scalar-field simulation tuning; prefers terse answers."

    assert um.synthesize_user_model(db_path=db, broker=FakeBroker()) is True
    m = um.read_user_model(db_path=db)
    assert m["is_seeded"] and "scalar-field" in m["dossier"]
    assert "scalar-field" in m["current_focus"][0]
    # the per-turn read is now the stored brief (single SELECT)
    assert "USER MODEL" in um.get_user_brief(db_path=db)


def test_synthesize_degrades_without_broker(db):
    _seed(db, "identity.role", "User is an engineer.")
    assert um.synthesize_user_model(db_path=db, broker=None) is True   # heuristic fallback
    assert um.read_user_model(db_path=db)["dossier"]  # non-empty heuristic dossier


def test_onboarding_flow_seeds_and_finishes(db, monkeypatch):
    captured = {}
    monkeypatch.setattr("eli.kernel.state.set_user_name", lambda n: captured.__setitem__("name", n))
    iv.clear_onboarding_state()
    # substantive task passes straight through
    assert iv.onboarding_intercept("fix this failing import in my module", db_path=db) is None
    assert not iv.is_onboarding_active()
    # light opener begins it
    assert "call you" in iv.onboarding_intercept("hey", db_path=db).lower()
    assert iv.is_onboarding_active()
    assert "work on" in iv.onboarding_intercept("Alex", db_path=db).lower()
    assert "terse" in iv.onboarding_intercept("physics", db_path=db).lower()
    done = iv.onboarding_intercept("terse and direct", db_path=db)
    assert "baseline" in done.lower() and not iv.is_onboarding_active()
    assert captured.get("name") == "Alex"
    rows = dict(sqlite3.connect(str(db)).execute(
        "select pattern_type, pattern_data from user_patterns").fetchall())
    assert "identity.role" in rows and "preference.style" in rows
    iv.clear_onboarding_state()


def test_onboarding_skip_clears(db):
    iv.clear_onboarding_state()
    iv.onboarding_intercept("hi", db_path=db)
    assert iv.is_onboarding_active()
    msg = iv.onboarding_intercept("skip", db_path=db)
    assert "pick it up" in msg.lower() and not iv.is_onboarding_active()
    iv.clear_onboarding_state()


def test_user_model_row_is_user_scoped(db):
    _seed(db, "identity.role", "User is a physicist.")
    um.synthesize_user_model(user_id="alice", db_path=db, broker=None)
    # the synthesized ROW for alice exists; bob has no row of his own
    assert um._read_row("alice", db_path=db) is not None
    assert um._read_row("bob", db_path=db) is None
