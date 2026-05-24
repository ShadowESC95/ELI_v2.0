#!/usr/bin/env python3
"""
rebuild_vector_index.py
=======================
Utility script: rebuild the FAISS vector index from the primary SQLite
memories database.  Run this after bulk imports, DB migrations, or if the
index drifts out of sync with the memories table.

Usage
-----
    python eli/scripts/rebuild_vector_index.py [--db PATH] [--dry-run]

Options
-------
    --db PATH     Path to the SQLite memories DB (default: auto-detected via
                  eli.core.paths).
    --dry-run     Show what would be rebuilt without writing anything.
    --verbose     Print each memory as it is indexed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path



from eli.utils.log import get_logger
log = get_logger(__name__)

def _resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        from eli.core.paths import get_db_path
        return Path(get_db_path("user")).expanduser().resolve()
    except Exception:
        pass
    try:
        from eli.memory.db_paths import user_db as _user_db
        return Path(_user_db).expanduser().resolve()
    except Exception:
        pass
    fallback = Path.home() / ".eli" / "user.sqlite3"
    return fallback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild ELI FAISS vector index from SQLite memories DB."
    )
    parser.add_argument("--db", default=None, help="Path to memories SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Do not write index")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    db_path = _resolve_db_path(args.db)
    log.debug(f"[rebuild_vector_index] DB: {db_path}")
    if not db_path.exists():
        log.error(f"[rebuild_vector_index] ERROR: DB not found at {db_path}")
        return 1

    try:
        from eli.memory.vector_store import get_vector_store
    except ImportError as exc:
        log.error(f"[rebuild_vector_index] ERROR: cannot import vector_store: {exc}")
        return 1

    vs = get_vector_store()
    if vs is None:
        log.debug("[rebuild_vector_index] No vector store available (FAISS not installed?).")
        return 0

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, COALESCE(text, content, '') AS text, COALESCE(tags, '') AS tags, "
        "COALESCE(kind, 'memory') AS kind, COALESCE(source, 'user') AS source, "
        "COALESCE(importance, 0.5) AS importance "
        "FROM memories WHERE COALESCE(text, content, '') != ''"
    ).fetchall()
    conn.close()

    log.debug(f"[rebuild_vector_index] Found {len(rows)} memories to index.")
    if args.dry_run:
        log.debug("[rebuild_vector_index] Dry run — no changes written.")
        return 0

    indexed = 0
    t0 = time.perf_counter()
    for row in rows:
        mem_id, text, tags, kind, source, importance = row
        try:
            vs.add(
                text,
                metadata={
                    "memory_id": mem_id,
                    "kind": kind,
                    "source": source,
                    "tags": tags,
                    "importance": importance,
                },
            )
            indexed += 1
            if args.verbose:
                print(f"  [{indexed}] id={mem_id} text={text[:60]!r}")
        except Exception as exc:
            print(f"  [WARN] id={mem_id} failed: {exc}")

    if hasattr(vs, "flush"):
        vs.flush()

    elapsed = time.perf_counter() - t0
    log.debug(
        f"[rebuild_vector_index] Indexed {indexed}/{len(rows)} memories "
        f"in {elapsed:.2f}s."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
