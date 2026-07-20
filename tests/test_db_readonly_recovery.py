"""Regression: portable ELI must initialise on WAL-hostile filesystems and self-heal
a store left unwritable by a root/sudo run.

Reported by a user on Arch (issue: portable Linux install extracted under
~/Downloads): every store backed by user.sqlite3 failed with "attempt to write a
readonly database" while system_index / coding_memory / agent in the SAME directory
initialised fine, and the GUI then died with a raw sqlite3 traceback.

Root cause: the failing stores all run ``PRAGMA journal_mode=WAL``; the passing ones
use the default rollback journal. WAL needs shared-memory + POSIX locking that
NTFS/exFAT/FAT and network mounts do not provide, so WAL returns SQLITE_READONLY
there while rollback-journal writes work fine in the very same folder — which is why
the ext4-backed AppImage worked but the ~/Downloads portable extract did not.

Fix: ``eli.core.sqlite_util.apply_pragmas`` tries WAL and falls back to DELETE when
the filesystem rejects it. A secondary self-heal handles a read-only file / stale
root-owned sidecars left by a sudo run.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "config" / "templates" / "db"


class _WalHostileConnection(sqlite3.Connection):
    """A connection that rejects WAL exactly like NTFS/exFAT/a network mount."""

    def execute(self, sql, *args, **kwargs):  # type: ignore[override]
        norm = sql.lower().replace(" ", "")
        if "journal_mode=wal" in norm:
            raise sqlite3.OperationalError("attempt to write a readonly database")
        return super().execute(sql, *args, **kwargs)


@pytest.fixture
def wal_hostile(monkeypatch):
    """Make every sqlite3.connect in the process reject WAL."""
    real = sqlite3.connect

    def fake(*a, **k):
        k["factory"] = _WalHostileConnection
        return real(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", fake)
    return real


def test_apply_pragmas_falls_back_to_delete_on_wal_hostile_fs(wal_hostile):
    from eli.core.sqlite_util import apply_pragmas

    db = Path(tempfile.mkdtemp()) / "t.sqlite3"
    conn = sqlite3.connect(str(db))
    mode = apply_pragmas(conn, db_path=str(db), synchronous="NORMAL")
    assert mode == "delete"
    # Must remain fully functional after the fallback.
    conn.execute("CREATE TABLE t(x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1


def test_apply_pragmas_keeps_wal_on_healthy_fs():
    from eli.core.sqlite_util import apply_pragmas

    db = Path(tempfile.mkdtemp()) / "t.sqlite3"
    conn = sqlite3.connect(str(db))
    assert apply_pragmas(conn, db_path=str(db), synchronous="NORMAL") == "wal"


def test_memory_open_survives_wal_hostile_fs(wal_hostile, tmp_path):
    """The exact traceback frame Node hit: _open_memory_db → PRAGMA WAL."""
    from eli.memory.memory import _open_memory_db

    db = tmp_path / "user.sqlite3"
    conn = _open_memory_db(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    conn.execute("CREATE TABLE t(x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()


def _seed(tmp_path: Path) -> Path:
    db = tmp_path / "user.sqlite3"
    shutil.copy(TEMPLATES / "user.sqlite3", db)
    return db


def _write(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS _probe(x)")
        conn.execute("INSERT INTO _probe VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def test_templates_ship_without_wal_sidecars():
    """No template may ship in WAL mode — that is what created the sidecars."""
    for template in sorted(TEMPLATES.glob("*.sqlite3")):
        conn = sqlite3.connect(str(template))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert mode.lower() == "delete", f"{template.name} ships in {mode} mode"
        for suffix in ("-wal", "-shm"):
            assert not Path(str(template) + suffix).exists()


def test_recovers_from_unwritable_sidecars(tmp_path):
    """The reported failure: sidecars the current user cannot write."""
    db = _seed(tmp_path)
    for suffix in ("-wal", "-shm"):
        side = Path(str(db) + suffix)
        side.write_bytes(b"")
        side.chmod(0o444)

    from eli.memory.memory import _open_memory_db

    conn = _open_memory_db(db)
    conn.close()
    _write(db)  # must succeed after recovery


def test_recovers_from_readonly_db_file(tmp_path):
    """A preserved read-only mode bit is repaired when we own the file."""
    db = _seed(tmp_path)
    db.chmod(0o444)

    from eli.memory.memory import _open_memory_db

    conn = _open_memory_db(db)
    conn.close()
    _write(db)


def test_healthy_database_is_untouched(tmp_path):
    """The repair must be a no-op on a healthy store."""
    db = _seed(tmp_path)
    before = db.stat().st_mode

    from eli.memory.memory import repair_unwritable_db, _open_memory_db

    assert repair_unwritable_db(db) is None
    conn = _open_memory_db(db)
    conn.close()
    assert db.stat().st_mode == before


@pytest.mark.skipif(os.getuid() == 0, reason="root can write anywhere")
def test_unwritable_directory_reports_actionable_message(tmp_path):
    """What cannot be repaired must at least be explained, not raise a traceback."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    shutil.copy(TEMPLATES / "user.sqlite3", db_dir / "user.sqlite3")
    db_dir.chmod(0o555)
    previous = os.environ.get("ELI_DATA_DIR")
    from eli.core import paths
    from eli.core.init_data import store_blocker

    try:
        os.environ["ELI_DATA_DIR"] = str(tmp_path)
        paths.data_dir.cache_clear()  # data_dir() is lru_cached at import time
        msg = store_blocker()
        assert msg and "chown" in msg and str(db_dir) in msg
    finally:
        db_dir.chmod(0o755)
        if previous is None:
            os.environ.pop("ELI_DATA_DIR", None)
        else:
            os.environ["ELI_DATA_DIR"] = previous
        paths.data_dir.cache_clear()
