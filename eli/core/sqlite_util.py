"""Shared SQLite pragmas — WAL with a portable-safe fallback.

Write-Ahead Logging is a concurrency/throughput optimisation, NOT a correctness
requirement. It relies on shared-memory (`-shm`) and POSIX byte-range locking that
several filesystems do NOT provide:

  * NTFS / exFAT / FAT (a dual-boot machine's data partition, a USB stick)
  * network mounts (NFS, CIFS/SMB)
  * some FUSE / overlay setups

On those, ``PRAGMA journal_mode=WAL`` reports ``SQLITE_READONLY`` ("attempt to
write a readonly database") even though the file and its directory are writable —
a normal rollback-journal (DELETE) connection works fine in the very same folder.
This bit a user who extracted the portable Linux build under ``~/Downloads`` on a
non-ext4 partition: every WAL-backed store failed while the rollback-journal
stores beside them succeeded.

``apply_pragmas`` tries WAL and silently falls back to DELETE when the filesystem
rejects it, so ELI stays fully functional everywhere. Import-light and dependency
-free on purpose: the many DB modules that need it must not pull in heavy imports.
"""
from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)

# Remember filesystems we have already downgraded so the warning fires once, not
# on every connection.
_wal_unsupported: set[str] = set()


def apply_pragmas(conn: sqlite3.Connection, *, db_path: str | None = None,
                  synchronous: str = "NORMAL", cache_size: int | None = None) -> str:
    """Set journal mode (WAL, or DELETE where WAL is unsupported) + tuning pragmas.

    Returns the journal mode actually in effect ("wal" or "delete"). Never raises
    on a filesystem that rejects WAL — that is the whole point.
    """
    # synchronous first: it applies in any journal mode, and setting it to NORMAL
    # before the WAL write-probe below means that probe's COMMIT is fsync-free on a
    # healthy WAL system (WAL+NORMAL only fsyncs at checkpoint), so this stays cheap
    # on the hot path.
    if synchronous:
        try:
            conn.execute(f"PRAGMA synchronous={synchronous};")
        except sqlite3.OperationalError:
            log.debug("could not set synchronous=%s", synchronous, exc_info=True)

    mode = "delete"
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        # PRAGMA journal_mode reports the mode now in effect; a WAL-hostile
        # filesystem may leave it unchanged ('delete') rather than raise.
        row = conn.execute("PRAGMA journal_mode;").fetchone()
        got = (row[0] if row else "").lower()
        if got != "wal":
            raise sqlite3.OperationalError(f"journal_mode stayed '{got or 'unknown'}', not wal")
        # Prove a write actually works in WAL on this fs: on NTFS/exFAT/network
        # mounts the failure surfaces on the FIRST write, not on the pragma.
        conn.execute("BEGIN IMMEDIATE;")
        conn.execute("COMMIT;")
        mode = "wal"
    except sqlite3.OperationalError as exc:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK;")
            except sqlite3.OperationalError:
                log.debug("rollback after failed WAL probe did nothing", exc_info=True)
        _fallback_to_delete(conn, db_path, exc)
        mode = "delete"

    if cache_size is not None:
        try:
            conn.execute(f"PRAGMA cache_size={cache_size};")
        except sqlite3.OperationalError:
            log.debug("could not set cache_size=%s", cache_size, exc_info=True)
    return mode


def _fallback_to_delete(conn: sqlite3.Connection, db_path: str | None,
                        exc: Exception) -> None:
    """Switch a WAL-hostile connection to rollback-journal mode."""
    key = db_path or "<unknown>"
    if key not in _wal_unsupported:
        _wal_unsupported.add(key)
        log.warning(
            "[SQLITE] WAL journal unavailable for %s (%s) — this filesystem "
            "(e.g. NTFS/exFAT/FAT or a network mount) does not support it; "
            "falling back to DELETE journal. ELI works normally, just without "
            "WAL's extra concurrency.", key, exc,
        )
    try:
        conn.execute("PRAGMA journal_mode=DELETE;")
    except sqlite3.OperationalError:
        # Even DELETE refused — genuinely read-only medium. Leave it; the caller's
        # own error handling / init_data.store_blocker() surfaces an actionable
        # message rather than a bare traceback.
        log.debug("could not set journal_mode=DELETE either for %s", key, exc_info=True)
