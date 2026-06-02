#!/usr/bin/env python3
"""ELI memory / identity factory-reset.

Clears every store where ELI keeps learned state AND the user's identity, while
**preserving all DB schema** (tables/columns/FTS) and your install config. Backs
everything up first so it's reversible.

Why a dedicated tool: identity is spread across MORE than the obvious DB —
clearing only artifacts/db left ELI still knowing the user, because the name was
seeded in config/settings.json and runtime caches and re-synced on next launch.
This tool knows ALL of them:

  • artifacts/db/*.sqlite3        rows wiped (schema kept, FTS reset, VACUUM)
  • artifacts/vectors/index.faiss semantic index reset (rebuilds empty)
  • runtime/users/**/user_profile.json + user_info*   learned profile
  • config/settings.json["user_name"]                 the identity SEED
  • runtime/world_model.json, state.json              name fields blanked
  • artifacts/conversations/*.json                     session transcripts

Usage:
  python tools/clear_memory.py                 # show plan, confirm, back up, wipe
  python tools/clear_memory.py --yes           # no confirmation prompt
  python tools/clear_memory.py --dry-run       # show what WOULD happen, change nothing
  python tools/clear_memory.py --keep-conversations
  python tools/clear_memory.py --keep-profile  # wipe memory but keep your name/profile
  python tools/clear_memory.py --no-backup     # skip backup (not recommended)

Run with ELI NOT running (an open DB lock will abort the wipe).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

_NAME_KEYS = {"name", "preferred_name", "user_name", "nickname", "alias", "first_name"}


def _bases():
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    try:
        from eli.core.paths import get_paths, data_dir
        return Path(data_dir()), Path(get_paths().config_dir), repo
    except Exception:
        return repo / "artifacts", repo / "config", repo


def _skip(p: Path) -> bool:
    return "_memory_backup_" in str(p)


def discover(base: Path, config: Path, keep_conversations: bool, keep_profile: bool):
    """Return {category: [Path, ...]} of existing targets."""
    t: dict = {}
    t["dbs"] = [p for p in base.glob("db/*.sqlite3") if not _skip(p)]
    t["faiss"] = [p for p in (base / "vectors").glob("*.faiss") if not _skip(p)]
    _meta = base / "vectors" / "meta.json"
    if _meta.exists():
        t["faiss"].append(_meta)
    t["name_caches"] = [p for p in (base / "runtime" / "world_model.json",
                                    base / "state.json",
                                    base / "runtime" / "state.json") if p.exists()]
    t["settings"] = [config / "settings.json"] if (config / "settings.json").exists() else []
    if not keep_profile:
        prof = []
        for p in (base / "runtime" / "users").rglob("*"):
            if p.is_file() and (p.name == "user_profile.json" or p.name.startswith("user_info")):
                prof.append(p)
        t["profile"] = prof
    else:
        t["profile"] = []
    if not keep_conversations:
        t["conversations"] = [p for p in (base / "conversations").rglob("*.json") if not _skip(p)]
    else:
        t["conversations"] = []
    return t


# ── operations ──────────────────────────────────────────────────────────────
def clear_db(path: Path):
    c = sqlite3.connect(str(path)); c.isolation_level = None
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
    c.execute("VACUUM")
    c.close()
    return before, len(base) + len(fts)


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

    changed = _walk(d)
    if changed:
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return changed


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


# ── main ──────────────────────────────────────────────────────────────────--
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ELI memory / identity factory-reset")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--keep-conversations", action="store_true")
    ap.add_argument("--keep-profile", action="store_true",
                    help="keep the learned name/profile (wipe only memory)")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    base, config, repo = _bases()
    t = discover(base, config, args.keep_conversations, args.keep_profile)

    print(f"\n  ELI memory reset   (data: {base})")
    print("  " + "─" * 56)
    counts = {
        "DBs (rows wiped, schema kept)": len(t["dbs"]),
        "FAISS index files": len(t["faiss"]),
        "profile files": len(t["profile"]),
        "name-cache files (name fields blanked)": len(t["name_caches"]),
        "settings.json user_name": len(t["settings"]),
        "conversation logs": len(t["conversations"]),
    }
    for k, v in counts.items():
        print(f"    {v:>4}  {k}")
    if args.keep_profile:
        print("    (--keep-profile: name/profile/settings name retained)")
    if args.keep_conversations:
        print("    (--keep-conversations: transcripts retained)")

    if args.dry_run:
        print("\n  DRY RUN — nothing changed.\n")
        return 0

    if not args.yes:
        try:
            resp = input("\n  This is destructive (backed up first). Type 'wipe' to proceed: ")
        except EOFError:
            resp = ""
        if resp.strip().lower() != "wipe":
            print("  aborted.\n")
            return 1

    # ── backup ──
    bk = None
    if not args.no_backup:
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
        print(f"  backup → {bk}")

    # ── execute ──
    db_rows = 0
    for p in t["dbs"]:
        try:
            n, _ = clear_db(p)
            db_rows += n
        except sqlite3.OperationalError as e:
            print(f"  ! {p.name}: {e} (is ELI running? aborting)")
            return 2
    for p in t["faiss"]:
        try:
            p.unlink()
        except Exception:
            pass
    for p in t["profile"]:
        try:
            p.unlink()
        except Exception:
            pass
    blanked = sum(scrub_json_names(p) for p in t["name_caches"])
    seed_cleared = any(clear_settings_name(p) for p in t["settings"]) if not args.keep_profile else False
    for p in t["conversations"]:
        try:
            p.unlink()
        except Exception:
            pass

    print("  " + "─" * 56)
    print(f"  ✓ wiped {db_rows} DB rows · reset {len(t['faiss'])} FAISS file(s) · "
          f"removed {len(t['profile'])} profile file(s)")
    print(f"  ✓ blanked {blanked} name field(s) · "
          f"settings user_name {'cleared' if seed_cleared else 'unchanged'} · "
          f"deleted {len(t['conversations'])} conversation log(s)")
    if bk:
        print(f"  restore from: {bk}")
    print("  Schemas intact. Next launch starts fresh (ELI will ask your name).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
