"""Fresh-install architecture: full stores, zero personal rows."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "config" / "templates" / "db"

EXPECTED_DBS = (
    "user.sqlite3",
    "agent.sqlite3",
    "system_index.sqlite3",
    "coding_memory.sqlite3",
)

# Content tables that must stay empty on a blank slate (schema-only install).
PERSONAL_TABLES = (
    ("user.sqlite3", "memories"),
    ("user.sqlite3", "conversation_turns"),
    ("user.sqlite3", "conversations"),
    ("user.sqlite3", "user_patterns"),
    ("user.sqlite3", "observations"),
    ("user.sqlite3", "session_summaries"),
    ("user.sqlite3", "learning_replay"),
    ("agent.sqlite3", "agent_dispatches"),
)

# Architecture tables that must exist after init (subset — full list is larger).
REQUIRED_TABLES = (
    ("user.sqlite3", "memories"),
    ("user.sqlite3", "memories_fts"),
    ("user.sqlite3", "kg_entities"),
    ("user.sqlite3", "kg_relations"),
    ("user.sqlite3", "news_articles"),
    ("user.sqlite3", "runtime_events"),
    ("system_index.sqlite3", "executables"),
    ("coding_memory.sqlite3", "coding_bug_fixes"),
    ("agent.sqlite3", "agent_dispatches"),
)


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {str(r[0]) for r in rows}


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    except sqlite3.Error:
        return -1


@pytest.fixture()
def fresh_install_env(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    db_dir = artifacts / "db"
    db_dir.mkdir(parents=True)
    install_root = tmp_path / "ELI_v2"
    install_root.mkdir()
    # Mirror frozen layout: templates live beside eli/ under project root.
    template_dest = install_root / "config" / "templates" / "db"
    template_dest.mkdir(parents=True)
    for src in TEMPLATES.glob("*.sqlite3"):
        import shutil

        shutil.copy2(src, template_dest / src.name)

    monkeypatch.setenv("ELI_PROJECT_ROOT", str(install_root))
    monkeypatch.setenv("ELI_DATA_DIR", str(artifacts))
    monkeypatch.setenv("ELI_DB_DIR", str(db_dir))
    monkeypatch.setenv("ELI_USER_DB", str(db_dir / "user.sqlite3"))
    monkeypatch.setenv("ELI_AGENT_DB", str(db_dir / "agent.sqlite3"))

    from eli.core import paths as cp

    for name in ("data_dir", "config_dir", "user_db_path", "agent_db_path", "project_root"):
        fn = getattr(cp, name, None)
        if fn is not None and hasattr(fn, "cache_clear"):
            fn.cache_clear()

    yield db_dir


def test_init_all_data_builds_full_architecture_blank_slate(fresh_install_env):
    from eli.core.init_data import init_all_data

    results = init_all_data()
    failed = [name for name, ok, _ in results if not ok]
    assert not failed, f"init steps failed: {failed}"

    db_dir: Path = fresh_install_env
    for name in EXPECTED_DBS:
        assert (db_dir / name).exists(), f"missing store: {name}"

    for db_name, table in REQUIRED_TABLES:
        db_path = db_dir / db_name
        assert table in _table_names(db_path), f"{db_name} missing table {table}"

    for db_name, table in PERSONAL_TABLES:
        db_path = db_dir / db_name
        with sqlite3.connect(db_path) as conn:
            assert _count(conn, table) == 0, f"{db_name}.{table} must be empty on fresh install"


def test_git_template_dbs_exist_and_are_schema_only():
    assert TEMPLATES.is_dir(), "config/templates/db must ship in git"
    names = {p.name for p in TEMPLATES.glob("*.sqlite3")}
    assert set(EXPECTED_DBS) <= names

    for db_name, table in PERSONAL_TABLES:
        db_path = TEMPLATES / db_name
        with sqlite3.connect(db_path) as conn:
            if table not in _table_names(db_path):
                pytest.skip(f"template {db_name} predates table {table}")
            assert _count(conn, table) == 0, (
                f"template {db_name}.{table} must not ship personal rows"
            )
