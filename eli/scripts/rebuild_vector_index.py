#!/usr/bin/env python3
"""
rebuild_vector_index.py
=======================
Rebuild the FAISS vector index from scratch using SQLite memories.
Bypasses the VectorStore singleton to avoid the background auto-rebuild race.

Usage
-----
    python -m eli.scripts.rebuild_vector_index [--db PATH] [--dry-run] [--verbose]
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from pathlib import Path

from eli.utils.log import get_logger
log = get_logger(__name__)


def _resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        from eli.core.paths import user_db_path
        return Path(user_db_path()).expanduser().resolve()
    except Exception:
        pass
    return Path.home() / ".eli" / "user.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild ELI FAISS vector index.")
    parser.add_argument("--db", default=None, help="Path to memories SQLite DB")
    parser.add_argument("--dry-run", action="store_true", help="Show counts, do not write")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    db_path = _resolve_db_path(args.db)
    log.debug(f"[rebuild_vector_index] DB: {db_path}")
    if not db_path.exists():
        log.error(f"[rebuild_vector_index] ERROR: DB not found at {db_path}")
        return 1

    # Load memories from SQLite
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, COALESCE(text, content, '') AS text, COALESCE(tags, '') AS tags, "
        "COALESCE(kind, 'memory') AS kind, COALESCE(source, 'user') AS source, "
        "COALESCE(importance, 0.5) AS importance "
        "FROM memories WHERE length(COALESCE(text, content, '')) > 0"
    ).fetchall()
    conn.close()

    log.debug(f"[rebuild_vector_index] Found {len(rows)} memories.")
    if args.dry_run:
        log.debug("[rebuild_vector_index] Dry run — no changes written.")
        return 0

    # Get index paths directly (bypasses singleton)
    try:
        import faiss
        from eli.memory.vector_store import _get_index_paths, EMBED_DIM
    except ImportError as exc:
        log.error(f"[rebuild_vector_index] Import failed: {exc}")
        return 1

    idx_path, meta_path = _get_index_paths()

    # Load embedder (same path as VectorStore._init_embedder)
    try:
        from eli.memory.vector_store import VectorStore as _VS
        _tmp = object.__new__(_VS)
        _tmp._lock = __import__("threading").Lock()
        _tmp._adds_since_save = 0
        _tmp._save_generation = 0
        _tmp._needs_rebuild = False
        _tmp._meta = []
        _tmp._index_path = idx_path
        _tmp._meta_path = meta_path
        _tmp._embedder = None
        _tmp._init_embedder()
        embedder = _tmp._embedder
    except Exception as exc:
        log.error(f"[rebuild_vector_index] Embedder init failed: {exc}")
        return 1

    if embedder is None:
        log.error("[rebuild_vector_index] No embedder available.")
        return 1

    # Build fresh index
    index = faiss.IndexFlatL2(EMBED_DIM)
    meta: list = []
    indexed = 0
    t0 = time.perf_counter()

    for mem_id, text, tags, kind, source, importance in rows:
        if not text:
            continue
        try:
            import numpy as np
            emb = embedder.embed(text)
            if emb is None:
                continue
            vec = np.array([emb], dtype="float32")
            index.add(vec)
            meta.append({
                "text": text,
                "memory_id": mem_id,
                "kind": kind,
                "source": source,
                "tags": tags,
                "importance": importance,
            })
            indexed += 1
            if args.verbose:
                print(f"  [{indexed}] id={mem_id} text={text[:60]!r}")
        except Exception as exc:
            log.debug(f"  [WARN] id={mem_id} failed: {exc}")

    # Write atomically
    faiss.write_index(index, str(idx_path))
    with open(str(meta_path), "wb") as f:
        pickle.dump(meta, f)

    # Reload singleton so subsequent queries use the fresh index
    from eli.memory.vector_store import reset_vector_store
    reset_vector_store()

    elapsed = time.perf_counter() - t0
    log.debug(
        f"[rebuild_vector_index] Indexed {indexed}/{len(rows)} memories "
        f"in {elapsed:.2f}s → {idx_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
