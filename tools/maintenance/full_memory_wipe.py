#!/usr/bin/env python3
"""
Portable full memory wipe for ELI-style local assistant projects.

Wipes:
- SQLite memory/state DBs under artifacts/db/
- FAISS/vector files under artifacts/vectors/
- runtime profile/world-model/snapshot residue
- conversation archives and known re-poison surfaces

No machine-specific paths are hard-coded.

Use:
    python3 tools/maintenance/full_memory_wipe.py --dry-run
    python3 tools/maintenance/full_memory_wipe.py
    python3 tools/maintenance/full_memory_wipe.py --no-backup
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
SIDE_SUFFIXES = ("-wal", "-shm", "-journal")

# Tables that identify a DB as user/agent memory or assistant state.
# This prevents machine/environment indexes such as system_index.sqlite3
# from being wiped by default.
MEMORY_STATE_TABLE_HINTS = {
    "memories",
    "memories_fts",
    "conversation_turns",
    "conversations",
    "observations",
    "recall_log",
    "session_summaries",
    "user_patterns",
    "habits",
    "habit_events",
    "habit_rules",
    "improvements",
    "failures",
    "corrections",
    "kg_entities",
    "kg_entities_fts",
    "kg_relations",
    "capability_proposals",
    "news_articles",
    "news_fts",
    "news_reflections",
}

RUNTIME_FILES_TO_QUARANTINE = [
    "artifacts/runtime_snapshot.json",
    "artifacts/runtime/user_profile.json",
    "artifacts/runtime/world_model.json",
    "artifacts/runtime/last_trace.json",
    "artifacts/runtime/last_response.json",
    "artifacts/runtime/last_image_generation.json",
    "artifacts/user_info.txt",
    "artifacts/user_info.meta.json",
    "artifacts/user_info_diff.jsonl",
    "artifacts/image_engine/outputs/eli_manifest.json",
    "artifacts/image_engine/logs/image_engine.log",
]

DIRS_TO_QUARANTINE = [
    "artifacts/conversations",
    "artifacts/scripts/invalid",
]

DIR_PREFIXES_TO_QUARANTINE = [
    "artifacts/quarantine",
    "artifacts/quarantine_",
    "artifacts/runtime/quarantine",
    "artifacts/runtime/quarantine_",
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def find_project_root(start: Path | None = None, override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()

    env_root = os.environ.get("ELI_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    here = (start or Path(__file__)).resolve()
    for p in [here] + list(here.parents):
        if (p / "artifacts").exists() and ((p / "eli").exists() or (p / "config").exists()):
            return p

    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd().resolve()


def ensure_inside_or_equal(root: Path, target: Path) -> None:
    root = root.resolve()
    target = target.resolve()
    if target != root and root not in target.parents:
        raise RuntimeError(f"Refusing to operate outside project root: {target}")


def default_backup_dir(root: Path, stamp: str) -> Path:
    return root.parent / f"{root.name}_memory_wipe_backup_{stamp}"


def copy_to_backup(root: Path, src: Path, backup_root: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    if not src.exists():
        return
    rel = src.relative_to(root)
    dst = backup_root / rel
    summary.setdefault("backed_up", []).append({"src": str(src), "dst": str(dst)})
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)


def move_to_backup(root: Path, src: Path, backup_root: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    if not src.exists():
        return
    rel = src.relative_to(root)
    dst = backup_root / rel
    summary.setdefault("quarantined", []).append({"src": str(src), "dst": str(dst)})
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(src), str(dst))


def sqlite_files(root: Path) -> list[Path]:
    db_dir = root / "artifacts" / "db"
    if not db_dir.exists():
        return []
    out: list[Path] = []
    for p in db_dir.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith(SIDE_SUFFIXES):
            continue
        if p.suffix.lower() in SQLITE_SUFFIXES:
            out.append(p)
    return sorted(out)


def is_sqlite_database(path: Path) -> bool:
    try:
        with sqlite3.connect(str(path)) as con:
            con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        return True
    except Exception:
        return False


def sqlite_table_names(path: Path) -> set[str]:
    try:
        with sqlite3.connect(str(path)) as con:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return {str(r[0]) for r in rows}
    except Exception:
        return set()


def looks_like_memory_state_db(path: Path) -> bool:
    names = sqlite_table_names(path)
    return bool(names & MEMORY_STATE_TABLE_HINTS)


def get_table_metadata(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
    ).fetchall()
    tables: list[dict[str, Any]] = []
    for name, typ, sql in rows:
        if typ != "table" or name.startswith("sqlite_"):
            continue
        sql_s = sql or ""
        tables.append({
            "name": name,
            "sql": sql_s,
            "is_virtual": "VIRTUAL TABLE" in sql_s.upper(),
            "is_fts": "USING FTS" in sql_s.upper(),
        })
    return tables


def fts_shadow_tables(tables: list[dict[str, Any]]) -> set[str]:
    fts_names = {t["name"] for t in tables if t.get("is_fts")}
    suffixes = {"_data", "_idx", "_docsize", "_config", "_content", "_segments", "_segdir", "_stat"}
    names = {t["name"] for t in tables}
    return {f"{fts}{s}" for fts in fts_names for s in suffixes if f"{fts}{s}" in names}


def count_rows(con: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        return None


def wipe_sqlite_db(db: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    if not is_sqlite_database(db):
        summary.setdefault("sqlite_skipped", []).append({"db": str(db), "reason": "not sqlite"})
        return

    db_summary: dict[str, Any] = {"db": str(db), "cleared_tables": [], "errors": []}
    con = sqlite3.connect(str(db))
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        tables = get_table_metadata(con)
        shadows = fts_shadow_tables(tables)

        for t in tables:
            name = t["name"]
            if name in shadows:
                continue
            before = count_rows(con, name)
            db_summary["cleared_tables"].append({"table": name, "rows_before": before})
            if not dry_run:
                try:
                    con.execute(f'DELETE FROM "{name}"')
                except Exception as e:
                    db_summary["errors"].append({"table": name, "error": f"{type(e).__name__}: {e}"})

        if not dry_run:
            try:
                con.execute("DELETE FROM sqlite_sequence")
            except Exception:
                pass
            con.commit()
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            try:
                con.execute("VACUUM")
            except Exception as e:
                db_summary["errors"].append({"table": "<vacuum>", "error": f"{type(e).__name__}: {e}"})
    finally:
        con.close()

    summary.setdefault("sqlite_wiped", []).append(db_summary)


def remove_path(root: Path, path: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    if not path.exists():
        return
    ensure_inside_or_equal(root, path)
    summary.setdefault("removed", []).append(str(path))
    if dry_run:
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def neutral_placeholders(root: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    runtime = root / "artifacts" / "runtime"
    conversations = root / "artifacts" / "conversations"
    vectors = root / "artifacts" / "vectors"

    for d in [runtime, conversations, vectors]:
        summary.setdefault("ensured_dirs", []).append(str(d))
        if not dry_run:
            d.mkdir(parents=True, exist_ok=True)

    files: dict[Path, Any] = {
        runtime / "user_profile.json": {
            "name": None,
            "preferred_name": None,
            "linux_user": None,
            "facts": [],
            "preferences": [],
            "active_projects": [],
            "research": [],
            "source": "neutral_post_full_memory_wipe",
        },
        runtime / "world_model.json": {
            "user_aliases": [],
            "facts": [],
            "runtime": {},
            "memory": {},
            "source": "neutral_post_full_memory_wipe",
        },
        root / "artifacts" / "user_info.txt": (
            "ELI USER INFO SNAPSHOT\n"
            "Generated after full memory wipe.\n"
            "No confirmed user facts in active memory.\n"
        ),
    }

    for path, content in files.items():
        summary.setdefault("placeholder_files", []).append(str(path))
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")


def quarantine_residual_surfaces(root: Path, backup_root: Path | None, dry_run: bool, summary: dict[str, Any]) -> None:
    for rel in RUNTIME_FILES_TO_QUARANTINE:
        p = root / rel
        if backup_root is None:
            remove_path(root, p, dry_run, summary)
        else:
            move_to_backup(root, p, backup_root, dry_run, summary)

    for rel in DIRS_TO_QUARANTINE:
        p = root / rel
        if backup_root is None:
            remove_path(root, p, dry_run, summary)
        else:
            move_to_backup(root, p, backup_root, dry_run, summary)

    artifacts = root / "artifacts"
    if artifacts.exists():
        for p in artifacts.iterdir():
            rel = p.relative_to(root).as_posix()
            if any(rel.startswith(prefix) for prefix in DIR_PREFIXES_TO_QUARANTINE):
                if backup_root is None:
                    remove_path(root, p, dry_run, summary)
                else:
                    move_to_backup(root, p, backup_root, dry_run, summary)


def remove_vectors_and_sidecars(root: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    vectors = root / "artifacts" / "vectors"
    if vectors.exists():
        for child in vectors.iterdir():
            remove_path(root, child, dry_run, summary)

    db_dir = root / "artifacts" / "db"
    if db_dir.exists():
        for p in db_dir.iterdir():
            if p.name.endswith(SIDE_SUFFIXES):
                remove_path(root, p, dry_run, summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Portable full memory wipe for ELI-style projects.")
    parser.add_argument("--root", help="Project root. Default: auto-detect.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without changing files.")
    parser.add_argument("--no-backup", action="store_true", help="Do not copy/quarantine old files before wiping.")
    parser.add_argument("--backup-dir", help="Backup/quarantine directory. Default: outside project root.")
    parser.add_argument("--include-nonmemory-dbs", action="store_true", help="Also wipe non-memory SQLite DBs such as system indexes.")
    parser.add_argument("--no-placeholders", action="store_true", help="Do not write neutral placeholder runtime files.")
    args = parser.parse_args()

    root = find_project_root(override=args.root)
    stamp = utc_stamp()

    if not root.exists():
        print(f"ERROR: project root does not exist: {root}", file=sys.stderr)
        return 2

    backup_root: Path | None = None
    if not args.no_backup:
        backup_root = Path(args.backup_dir).expanduser().resolve() if args.backup_dir else default_backup_dir(root, stamp)

    summary: dict[str, Any] = {
        "ok": True,
        "mode": "full_memory_wipe",
        "dry_run": args.dry_run,
        "project_root": str(root),
        "backup_root": str(backup_root) if backup_root else None,
        "timestamp_utc": stamp,
    }

    all_dbs = sqlite_files(root)
    if args.include_nonmemory_dbs:
        dbs = all_dbs
        skipped_nonmemory_dbs = []
    else:
        dbs = [db for db in all_dbs if looks_like_memory_state_db(db)]
        skipped_nonmemory_dbs = [str(db) for db in all_dbs if db not in dbs]

    summary["sqlite_skipped_nonmemory"] = skipped_nonmemory_dbs

    if backup_root is not None:
        for db in dbs:
            copy_to_backup(root, db, backup_root, args.dry_run, summary)
            for suffix in SIDE_SUFFIXES:
                copy_to_backup(root, Path(str(db) + suffix), backup_root, args.dry_run, summary)
        copy_to_backup(root, root / "artifacts" / "vectors", backup_root, args.dry_run, summary)

    for db in dbs:
        wipe_sqlite_db(db, args.dry_run, summary)

    remove_vectors_and_sidecars(root, args.dry_run, summary)
    quarantine_residual_surfaces(root, backup_root, args.dry_run, summary)

    if not args.no_placeholders:
        neutral_placeholders(root, args.dry_run, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
