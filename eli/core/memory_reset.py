"""ELI memory / identity factory-reset — reusable core.

Clears every store where ELI keeps learned state AND the user's identity, while
preserving all DB schema (tables/columns/FTS) and install config. Backs up first.

Identity lives in MORE than artifacts/db — clearing only the DB left ELI still
knowing the user, because the name was seeded in config/settings.json + runtime
caches and re-synced on next launch. This module knows ALL of them:

  • artifacts/db/*.sqlite3        rows wiped (schema kept, FTS reset, VACUUM)
  • vectors/index.faiss + meta    semantic index reset (rebuilds empty)
  • runtime/users/**/user_profile.json + user_info*   learned profile
  • config/settings.json[user_name]                   the identity SEED
  • runtime/world_model.json, state.json              name fields blanked
  • conversations/*.json                              session transcripts

Used by both tools/clear_memory.py (CLI) and the GUI Advanced settings page.
VACUUM is best-effort so a reset can run even while ELI holds DB connections
(the rows still commit; only space-reclaim is skipped under a lock).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

_NAME_KEYS = {"name", "preferred_name", "user_name", "nickname", "alias", "first_name"}


def bases():
    """(data_dir, config_dir) resolved via eli.core.paths (dev + platformdirs)."""
    try:
        from eli.core.paths import get_paths, data_dir
        return Path(data_dir()), Path(get_paths().config_dir)
    except Exception:
        repo = Path(__file__).resolve().parents[2]
        return repo / "artifacts", repo / "config"


def _skip(p: Path) -> bool:
    return "_memory_backup_" in str(p)


def discover(base: Path, config: Path,
             keep_conversations: bool = False, keep_profile: bool = False) -> Dict[str, List[Path]]:
    """Existing targets by category."""
    t: Dict[str, List[Path]] = {}
    t["dbs"] = [p for p in base.glob("db/*.sqlite3") if not _skip(p)]
    t["faiss"] = [p for p in (base / "vectors").glob("*.faiss") if not _skip(p)]
    if (base / "vectors" / "meta.json").exists():
        t["faiss"].append(base / "vectors" / "meta.json")
    t["name_caches"] = [p for p in (base / "runtime" / "world_model.json",
                                    base / "state.json",
                                    base / "runtime" / "state.json") if p.exists()]
    t["settings"] = [config / "settings.json"] if (config / "settings.json").exists() and not keep_profile else []
    t["profile"] = []
    if not keep_profile:
        for p in (base / "runtime" / "users").rglob("*"):
            if p.is_file() and (p.name == "user_profile.json" or p.name.startswith("user_info")):
                t["profile"].append(p)
    t["conversations"] = ([] if keep_conversations
                          else [p for p in (base / "conversations").rglob("*.json") if not _skip(p)])
    # Transient runtime state — pending offers ELI may have left mid-conversation
    # (code-fix suggestions, app/package repair offers). Not "learned" memory but
    # a true factory reset should not leave a stale pending action behind.
    t["transient"] = [p for p in (base / "pending_code_fix.json",
                                  base / "pending_remediation.json")
                      if p.exists()]
    return t


def counts(t: Dict[str, List[Path]]) -> Dict[str, int]:
    return {k: len(v) for k, v in t.items()}


# ── operations ──────────────────────────────────────────────────────────────
def clear_db(path: Path) -> int:
    """Delete all rows (keep schema), reset FTS, best-effort VACUUM. Returns rows cleared."""
    c = sqlite3.connect(str(path)); c.isolation_level = None
    try:
        c.execute("PRAGMA foreign_keys=OFF")
        rows = c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        fts = [n for n, s in rows if "using fts" in (s or "").lower()]
        shadow = ("_data", "_idx", "_docsize", "_config", "_content")
        base = [n for n, s in rows if "using fts" not in (s or "").lower() and not n.endswith(shadow)]
        before = 0
        for n in base + fts:
            try:
                before += c.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
            except Exception:
                pass
        for n in base:
            if n == "sqlite_sequence":
                continue
            c.execute(f'DELETE FROM "{n}"')
        for n in fts:
            try:
                c.execute(f'INSERT INTO "{n}"("{n}") VALUES(\'delete-all\')')
            except Exception:
                try:
                    c.execute(f'DELETE FROM "{n}"')
                except Exception:
                    pass
        try:
            c.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
        try:
            c.execute("VACUUM")  # best-effort: may fail if ELI holds a connection
        except Exception:
            pass
        return before
    finally:
        c.close()


def scrub_json_names(path: Path) -> int:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    def _walk(o):
        n = 0
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k.lower() in _NAME_KEYS and isinstance(v, str) and v.strip():
                    o[k] = ""; n += 1
                else:
                    n += _walk(v)
        elif isinstance(o, list):
            for x in o:
                n += _walk(x)
        return n

    n = _walk(d)
    if n:
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return n


def clear_settings_name(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if str(d.get("user_name", "")).strip():
        d["user_name"] = ""
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
        return True
    return False


def backup(t: Dict[str, List[Path]], base: Path) -> Path:
    bk = base / f"_memory_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    for cat, paths in t.items():
        for p in paths:
            rel = p.relative_to(base) if base in p.parents else Path(cat) / p.name
            dest = bk / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(p, dest)
            except Exception:
                pass
    return bk


def run_reset(keep_profile: bool = False, keep_conversations: bool = False,
              do_backup: bool = True) -> Dict[str, Any]:
    """Perform the reset. Returns a summary dict (safe to show in a UI)."""
    base, config = bases()
    t = discover(base, config, keep_conversations, keep_profile)
    summary: Dict[str, Any] = {"ok": True, "backup": None, "db_rows": 0, "errors": []}

    if do_backup:
        try:
            summary["backup"] = str(backup(t, base))
        except Exception as e:
            summary["errors"].append(f"backup: {e}")

    for p in t["dbs"]:
        try:
            summary["db_rows"] += clear_db(p)
        except Exception as e:
            summary["errors"].append(f"{p.name}: {e}")
    for p in t["faiss"] + t["profile"] + t["conversations"] + t.get("transient", []):
        try:
            p.unlink()
        except Exception:
            pass
    summary["name_fields_blanked"] = sum(scrub_json_names(p) for p in t["name_caches"])
    summary["settings_name_cleared"] = any(clear_settings_name(p) for p in t["settings"])
    summary["faiss_reset"] = len(t["faiss"])
    summary["profiles_removed"] = len(t["profile"])
    summary["conversations_removed"] = len(t["conversations"])
    summary["transient_removed"] = len(t.get("transient", []))
    summary["ok"] = not summary["errors"]
    return summary
