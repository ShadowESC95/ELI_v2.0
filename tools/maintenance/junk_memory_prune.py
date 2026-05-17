#!/usr/bin/env python3
"""
Portable junk/duplicate prune for ELI-style local assistant projects.

Purpose:
- Keep durable memories.
- Remove obvious junk rows, prompt echoes, news/reflection spam, runtime dumps,
  schema dumps, generated-script loops, and duplicates.
- Rebuild simple memory FTS indexes where possible.
- Quarantine known junk files/directories without wiping the whole memory system.

No machine-specific paths are hard-coded.

Use:
    python3 tools/maintenance/junk_memory_prune.py --dry-run
    python3 tools/maintenance/junk_memory_prune.py
    python3 tools/maintenance/junk_memory_prune.py --aggressive
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
SIDE_SUFFIXES = ("-wal", "-shm", "-journal")

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

TEXT_COLUMN_CANDIDATES = [
    "text", "value", "content", "observation", "details", "pattern_data",
    "summary", "query", "title", "description", "tags", "source",
    "category", "error", "traceback", "context",
]

JUNK_PATTERNS = [
    r"\bReflection \(24h\)\b",
    r"\bconversation volume\b",
    r"\bTop topics:\b",
    r"\bHackerNews\b",
    r"\bReddit/",
    r"\bnews synthesis\b",
    r"\bnews feed\b",
    r"\barXiv: The read operation timed out\b",
    r"\bSYNTHESISE_FROM_DETERMINISTIC_EVIDENCE\b",
    r"\bTreat it as ground truth\b",
    r"\bDo not invent missing runtime details\b",
    r"\braw memory-count dump\b",
    r"\bYou are right: that should not have been\b",
    r"\bMemory truth report\b",
    r"\bRuntime truth report\b",
    r"\bLast-response truth report\b",
    r"\bImport audit\b",
    r"\bControl-action evidence failure\b",
    r"\bsqlite3 schema\b",
    r"\bcolumns:\b",
    r"\brows:\b",
    r"\bScript generated:\b",
    r"\bgenerated_spam\b",
    r"\bGenerate only the requested source code\b",
    r"\bInferenceBroker\.infer\(\) got an unexpected keyword argument\b",
    r"\bNo visible output\b",
    r"\bCognitiveEngine stream produced no visible output\b",
    r"\bAs ELI:\b",
    r"\bI am not Eli, YOU are Eli\b",
    r"\bthe user asked\b.*\bauthoritative deterministic evidence follows\b",
]

AGGRESSIVE_JUNK_PATTERNS = [
    r"\bSession context:\b",
    r"\bCapability inventory updated:\b",
    r"\bOpened folder:\b",
    r"\bLive news\b",
    r"\bnew articles fetched\b",
    r"\bproactive notes\b",
    r"\bPeak activity at\b",
]

CLEAR_TABLES_DEFAULT = {
    "news_articles",
    "news_fts",
    "news_reflections",
}

CLEAR_TABLES_AGGRESSIVE = {
    "recall_log",
}

JUNK_FILES = [
    "artifacts/runtime/last_trace.json",
    "artifacts/runtime/last_response.json",
    "artifacts/runtime/last_image_generation.json",
    "artifacts/runtime_snapshot.json",
    "artifacts/image_engine/outputs/eli_manifest.json",
    "artifacts/image_engine/logs/image_engine.log",
]

JUNK_DIRS = [
    "artifacts/scripts/invalid",
]

JUNK_DIR_PREFIXES = [
    "artifacts/quarantine",
    "artifacts/quarantine_",
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


def default_quarantine_dir(root: Path, stamp: str) -> Path:
    return root.parent / f"{root.name}_junk_quarantine_{stamp}"


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


def normalise(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value).replace("\x00", " ")
    return re.sub(r"\s+", " ", text).strip()


def dedupe_key(text: str) -> str:
    text = normalise(text).lower()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def compile_patterns(aggressive: bool) -> list[re.Pattern[str]]:
    patterns = list(JUNK_PATTERNS)
    if aggressive:
        patterns.extend(AGGRESSIVE_JUNK_PATTERNS)
    return [re.compile(p, re.IGNORECASE | re.UNICODE) for p in patterns]


def is_junk_text(text: str, patterns: list[re.Pattern[str]]) -> bool:
    text = normalise(text)
    if not text:
        return False

    if len(text) > 3500 and any(k in text.lower() for k in ["runtime truth", "sqlite", "schema", "reflection", "hackernews"]):
        return True

    return any(p.search(text) for p in patterns)


def table_rows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT name, type, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    tables: list[dict[str, Any]] = []
    for name, typ, sql in rows:
        if name.startswith("sqlite_"):
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
    names = {t["name"] for t in tables}
    fts_names = {t["name"] for t in tables if t.get("is_fts")}
    suffixes = {"_data", "_idx", "_docsize", "_config", "_content", "_segments", "_segdir", "_stat"}
    return {f"{fts}{s}" for fts in fts_names for s in suffixes if f"{fts}{s}" in names}


def columns(con: sqlite3.Connection, table: str) -> list[str]:
    try:
        return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]
    except Exception:
        return []


def usable_text_columns(con: sqlite3.Connection, table: str) -> list[str]:
    cols = columns(con, table)
    return [c for c in TEXT_COLUMN_CANDIDATES if c in cols]


def rowid_available(con: sqlite3.Connection, table: str) -> bool:
    try:
        con.execute(f'SELECT rowid FROM "{table}" LIMIT 1').fetchone()
        return True
    except Exception:
        return False


def clear_table(con: sqlite3.Connection, table: str, dry_run: bool) -> int | None:
    try:
        n = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except Exception:
        n = None
    if not dry_run:
        con.execute(f'DELETE FROM "{table}"')
    return n


def prune_table(
    con: sqlite3.Connection,
    table: str,
    patterns: list[re.Pattern[str]],
    dry_run: bool,
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "table": table,
        "junk_deleted": 0,
        "duplicates_deleted": 0,
        "kept": 0,
        "errors": [],
    }

    text_cols = usable_text_columns(con, table)
    if not text_cols or not rowid_available(con, table):
        info["skipped"] = "no usable text columns or rowid unavailable"
        return info

    select_cols = ", ".join(["rowid AS _rowid"] + [f'"{c}"' for c in text_cols])

    try:
        rows = con.execute(f'SELECT {select_cols} FROM "{table}" ORDER BY rowid DESC').fetchall()
    except Exception as e:
        info["errors"].append(f"select failed: {type(e).__name__}: {e}")
        return info

    seen: set[str] = set()
    delete_ids: list[int] = []

    for row in rows:
        rowid = int(row["_rowid"])
        parts = [normalise(row[c]) for c in text_cols]
        blob = " | ".join(p for p in parts if p)

        if is_junk_text(blob, patterns):
            delete_ids.append(rowid)
            info["junk_deleted"] += 1
            continue

        key = dedupe_key(blob)
        if len(key) >= 24:
            if key in seen:
                delete_ids.append(rowid)
                info["duplicates_deleted"] += 1
                continue
            seen.add(key)

        info["kept"] += 1

    if not dry_run and delete_ids:
        for i in range(0, len(delete_ids), 500):
            batch = delete_ids[i:i + 500]
            qmarks = ",".join("?" for _ in batch)
            con.execute(f'DELETE FROM "{table}" WHERE rowid IN ({qmarks})', batch)

    return info


def rebuild_memory_fts(con: sqlite3.Connection, dry_run: bool, db_summary: dict[str, Any]) -> None:
    tables = {t["name"] for t in table_rows(con)}
    if "memories" not in tables or "memories_fts" not in tables:
        return

    mem_cols = columns(con, "memories")
    fts_cols = columns(con, "memories_fts")

    if "text" not in fts_cols:
        return

    source_text = None
    for c in ["text", "content", "value"]:
        if c in mem_cols:
            source_text = c
            break

    if not source_text:
        return

    source_tags = "tags" if "tags" in mem_cols and "tags" in fts_cols else None
    db_summary.setdefault("fts_rebuild", []).append("memories_fts")

    if dry_run:
        return

    try:
        con.execute('DELETE FROM "memories_fts"')
        if source_tags:
            con.execute(
                f'INSERT INTO "memories_fts"(rowid, text, tags) '
                f'SELECT rowid, COALESCE("{source_text}", ""), COALESCE("{source_tags}", "") FROM "memories"'
            )
        else:
            con.execute(
                f'INSERT INTO "memories_fts"(rowid, text) '
                f'SELECT rowid, COALESCE("{source_text}", "") FROM "memories"'
            )
    except Exception as e:
        db_summary.setdefault("fts_errors", []).append(f"{type(e).__name__}: {e}")


def prune_db(db: Path, aggressive: bool, dry_run: bool) -> dict[str, Any]:
    db_summary: dict[str, Any] = {
        "db": str(db),
        "dry_run": dry_run,
        "cleared_tables": [],
        "pruned_tables": [],
        "errors": [],
    }

    if not is_sqlite_database(db):
        db_summary["errors"].append("not sqlite")
        return db_summary

    patterns = compile_patterns(aggressive)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row

    try:
        con.execute("PRAGMA foreign_keys=OFF")
        tables = table_rows(con)
        shadows = fts_shadow_tables(tables)

        clear_set = set(CLEAR_TABLES_DEFAULT)
        if aggressive:
            clear_set |= CLEAR_TABLES_AGGRESSIVE

        for t in tables:
            table = t["name"]

            if table in shadows:
                continue

            if table in clear_set:
                try:
                    n = clear_table(con, table, dry_run)
                    db_summary["cleared_tables"].append({"table": table, "rows_before": n})
                except Exception as e:
                    db_summary["errors"].append({"table": table, "error": f"{type(e).__name__}: {e}"})
                continue

            if table.startswith("kg_") and not aggressive:
                continue

            try:
                result = prune_table(con, table, patterns, dry_run)
                if result.get("junk_deleted") or result.get("duplicates_deleted") or result.get("errors"):
                    db_summary["pruned_tables"].append(result)
            except Exception as e:
                db_summary["errors"].append({"table": table, "error": f"{type(e).__name__}: {e}"})

        rebuild_memory_fts(con, dry_run, db_summary)

        if not dry_run:
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

    return db_summary


def move_to_quarantine(root: Path, src: Path, quarantine: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    if not src.exists():
        return

    try:
        rel = src.relative_to(root)
    except Exception:
        raise RuntimeError(f"Refusing to quarantine outside root: {src}")

    dst = quarantine / rel
    summary.setdefault("file_quarantine", []).append({"src": str(src), "dst": str(dst)})

    if dry_run:
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(src), str(dst))


def prune_junk_files(root: Path, quarantine: Path, dry_run: bool, summary: dict[str, Any]) -> None:
    for rel in JUNK_FILES:
        move_to_quarantine(root, root / rel, quarantine, dry_run, summary)

    for rel in JUNK_DIRS:
        move_to_quarantine(root, root / rel, quarantine, dry_run, summary)

    artifacts = root / "artifacts"
    if artifacts.exists():
        for p in artifacts.iterdir():
            rel = p.relative_to(root).as_posix()
            if any(rel.startswith(prefix) for prefix in JUNK_DIR_PREFIXES):
                move_to_quarantine(root, p, quarantine, dry_run, summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Portable junk/duplicate prune for ELI-style projects.")
    parser.add_argument("--root", help="Project root. Default: auto-detect.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without changing files.")
    parser.add_argument("--aggressive", action="store_true", help="Also prune session/context/capability/reflection-style rows.")
    parser.add_argument("--no-file-prune", action="store_true", help="Only prune SQLite DBs; do not quarantine junk files.")
    parser.add_argument("--quarantine-dir", help="Quarantine directory. Default: outside project root.")
    args = parser.parse_args()

    root = find_project_root(override=args.root)
    stamp = utc_stamp()
    quarantine = Path(args.quarantine_dir).expanduser().resolve() if args.quarantine_dir else default_quarantine_dir(root, stamp)

    if not root.exists():
        print(f"ERROR: project root does not exist: {root}", file=sys.stderr)
        return 2

    summary: dict[str, Any] = {
        "ok": True,
        "mode": "junk_memory_prune",
        "dry_run": args.dry_run,
        "aggressive": args.aggressive,
        "project_root": str(root),
        "quarantine": str(quarantine),
        "timestamp_utc": stamp,
        "databases": [],
    }

    all_dbs = sqlite_files(root)
    dbs = [db for db in all_dbs if looks_like_memory_state_db(db)]
    summary["sqlite_skipped_nonmemory"] = [str(db) for db in all_dbs if db not in dbs]

    for db in dbs:
        summary["databases"].append(prune_db(db, args.aggressive, args.dry_run))

    if not args.no_file_prune:
        prune_junk_files(root, quarantine, args.dry_run, summary)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
