#!/usr/bin/env python3
"""Build schema-only SQLite templates for fresh installs (no personal data).

Writes config/templates/db/*.sqlite3 — copied by install.sh when artifacts/db
is empty. Uses a temp ELI_DATA_DIR + ELI_DB_DIR so every store lands in staging.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalise_journal_mode(p: Path) -> None:
    """Check the WAL back into the main file and ship the template in DELETE mode.

    A template is a seed that gets copied between machines, filesystems and (via
    sudo installs) uid boundaries. WAL mode drags ``-wal``/``-shm`` sidecars along
    for the ride, and a sidecar the running user cannot write makes SQLite report
    "attempt to write a readonly database" on the first write — with the database
    file and its directory both perfectly writable. DELETE mode carries no
    sidecars; ELI switches the store to WAL itself on first open.
    """
    import sqlite3
    conn = sqlite3.connect(str(p))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.execute("PRAGMA journal_mode=DELETE;")
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        Path(str(p) + suffix).unlink(missing_ok=True)


def main() -> int:
    staging = Path(tempfile.mkdtemp(prefix="eli_db_seed_"))
    db_dir = staging / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    out = ROOT / "config" / "templates" / "db"
    out.mkdir(parents=True, exist_ok=True)

    os.environ["ELI_DATA_DIR"] = str(staging)
    os.environ["ELI_DB_DIR"] = str(db_dir)

    from eli.core.init_data import init_all_data
    from eli.core import memory_reset as mr

    results = init_all_data(verbose=True)
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"[WARN] init steps deferred: {', '.join(failed)}")

    copied = 0
    for p in sorted(db_dir.glob("*.sqlite3")):
        mr.clear_db(p)
        _normalise_journal_mode(p)
        dest = out / p.name
        shutil.copy2(p, dest)
        dest.chmod(0o644)  # copy2 preserves mode; a seed must never ship read-only
        copied += 1
        print(f"  [OK] {dest.name} ({dest.stat().st_size} bytes)")

    shutil.rmtree(staging, ignore_errors=True)
    print(f"[OK] {copied} template DB(s) in {out}")
    return 0 if copied else 1


if __name__ == "__main__":
    raise SystemExit(main())
