"""ELI memory / identity factory-reset — reusable core.

Clears every store where ELI keeps learned state AND the user's identity, while
preserving all DB schema (tables/columns/FTS) and install config. Backs up first.

Identity lives in MORE than artifacts/db — clearing only the DB left ELI still
knowing the user, because the name was seeded in config/settings.json + runtime
caches and re-synced on next launch. This module knows ALL of them:

  • artifacts/db/*.sqlite3        rows wiped (schema kept, FTS reset, VACUUM)
  • vectors/index.faiss + meta    semantic index reset (rebuilds empty)
  • runtime/users/**/user_profile.json + user_info*   learned profile
  • config/settings.json identity fields              name, device labels, …
  • runtime/world_model.json, state.json              removed or name-scrubbed
  • conversations/*.json                              session transcripts
  • eli/cognition/persona.auto.txt                    ELI learned overlay
  • runtime residue (last_trace, user_info.txt, …)  stale caches

After wipe, rebuilds the full DB architecture via init_all_data().

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
from typing import Any, Dict, List, Optional

_NAME_KEYS = {"name", "preferred_name", "user_name", "nickname", "alias", "first_name"}
_IDENTITY_SETTINGS = {
    "user_name": "",
    "bluetooth_display_name": "",
    "device_custom_names": {},
    "audio_output_aliases": {},
}
_RUNTIME_RESIDUE = (
    "runtime_snapshot.json",
    "runtime/last_trace.json",
    "runtime/last_response.json",
    "runtime/last_image_generation.json",
    "user_info.txt",
    "user_info.meta.json",
    "user_info_diff.jsonl",
)
_BLANK_PERSONA_TEMPLATE = Path(__file__).resolve().parents[2] / "config" / "templates" / "persona.auto.template.txt"


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


def _persona_overlay_paths(config: Path) -> List[Path]:
    paths: List[Path] = []
    try:
        from eli.core.paths import persona_auto_path
        p = persona_auto_path()
        if p.exists():
            paths.append(p)
    except Exception:
        pass
    alt = config / "persona.auto.txt"
    if alt.exists() and alt not in paths:
        paths.append(alt)
    return paths


def discover(base: Path, config: Path,
             keep_conversations: bool = False, keep_profile: bool = False) -> Dict[str, List[Path]]:
    """Existing targets by category."""
    t: Dict[str, List[Path]] = {}
    t["dbs"] = [p for p in base.glob("db/*.sqlite3") if not _skip(p)]
    t["faiss"] = [p for p in (base / "vectors").glob("*.faiss") if not _skip(p)]
    if (base / "vectors" / "meta.json").exists():
        t["faiss"].append(base / "vectors" / "meta.json")
    wm = base / "runtime" / "world_model.json"
    st = [base / "state.json", base / "runtime" / "state.json"]
    if keep_profile:
        t["name_caches"] = [p for p in [wm, *st] if p.exists()]
        t["runtime_wipe"] = []
    else:
        t["name_caches"] = []
        t["runtime_wipe"] = [p for p in [wm, *st] if p.exists()]
        t["runtime_wipe"].extend(p for rel in _RUNTIME_RESIDUE if (p := base / rel).exists())
    t["settings"] = [config / "settings.json"] if (config / "settings.json").exists() and not keep_profile else []
    t["profile"] = []
    if not keep_profile:
        for p in (base / "runtime" / "users").rglob("*"):
            if p.is_file() and (p.name == "user_profile.json" or p.name.startswith("user_info")):
                t["profile"].append(p)
    t["conversations"] = ([] if keep_conversations
                          else [p for p in (base / "conversations").rglob("*.json") if not _skip(p)])
    t["transient"] = [p for p in (base / "pending_code_fix.json",
                                  base / "pending_remediation.json")
                      if p.exists()]
    t["persona_overlay"] = _persona_overlay_paths(config)
    return t


def counts(t: Dict[str, List[Path]]) -> Dict[str, int]:
    return {k: len(v) for k, v in t.items()}


# ── operations ──────────────────────────────────────────────────────────────
def clear_db(path: Path, keep_tables: "frozenset[str] | set[str] | None" = None) -> int:
    """Delete all rows (keep schema), reset FTS, best-effort VACUUM. Returns rows cleared."""
    keep = {str(t) for t in (keep_tables or ())}
    c = sqlite3.connect(str(path)); c.isolation_level = None
    try:
        c.execute("PRAGMA foreign_keys=OFF")
        rows = c.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        fts = [n for n, s in rows if "using fts" in (s or "").lower() and n not in keep]
        shadow = ("_data", "_idx", "_docsize", "_config", "_content")
        base = [n for n, s in rows if "using fts" not in (s or "").lower()
                and not n.endswith(shadow) and n not in keep]
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
            if keep:
                qs = ",".join("?" * len(keep))
                c.execute(f"DELETE FROM sqlite_sequence WHERE name NOT IN ({qs})", tuple(keep))
            else:
                c.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
        try:
            c.execute("VACUUM")
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


def clear_settings_identity(path: Path) -> bool:
    """Clear user-specific fields in settings.json (name, device labels, …)."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    changed = False
    for key, blank in _IDENTITY_SETTINGS.items():
        cur = d.get(key)
        if cur == blank:
            continue
        if isinstance(blank, dict):
            if cur:
                d[key] = dict(blank)
                changed = True
        elif str(cur or "").strip() != str(blank).strip():
            d[key] = blank
            changed = True
    if changed:
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return changed


def clear_settings_name(path: Path) -> bool:
    """Backward-compatible alias — clears full identity block in settings."""
    return clear_settings_identity(path)


def reset_persona_overlay(template: Optional[Path] = None) -> bool:
    """Replace persona.auto.txt with the blank shipped template."""
    tpl = template or _BLANK_PERSONA_TEMPLATE
    text = ""
    if tpl.exists():
        text = tpl.read_text(encoding="utf-8")
    else:
        text = (
            "# Auto-updated persona overlay\n"
            "# Generated from habits, reflection, self-improvement, memory, and runtime signals.\n"
        )
    try:
        from eli.cognition.persona import write_auto_persona
        write_auto_persona(text)
        return True
    except Exception:
        try:
            from eli.core.paths import persona_auto_path
            dest = persona_auto_path()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text.rstrip() + "\n", encoding="utf-8")
            return True
        except Exception:
            return False


def rebuild_after_reset(verbose: bool = False) -> Dict[str, Any]:
    """Drop in-memory caches and rebuild the full blank DB architecture."""
    out: Dict[str, Any] = {"init_ok": True, "init_steps": 0, "init_failed": []}
    try:
        from eli.memory import _clear_memory_singletons
        _clear_memory_singletons()
    except Exception:
        pass
    try:
        from eli.core.init_data import init_all_data
        results = init_all_data(verbose=verbose)
        out["init_steps"] = len(results)
        out["init_failed"] = [n for n, ok, _ in results if not ok]
        out["init_ok"] = not out["init_failed"]
    except Exception as e:
        out["init_ok"] = False
        out["init_error"] = str(e)
    return out


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
              do_backup: bool = True,
              keep_tables: "frozenset[str] | set[str] | None" = None,
              rebuild: bool = True) -> Dict[str, Any]:
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
            summary["db_rows"] += clear_db(p, keep_tables=keep_tables)
        except Exception as e:
            summary["errors"].append(f"{p.name}: {e}")

    removed = (t["faiss"] + t["profile"] + t["conversations"]
               + t.get("transient", []) + t.get("runtime_wipe", []))
    for p in removed:
        try:
            p.unlink()
        except Exception:
            pass

    try:
        from eli.memory.vector_store import reset_vector_store
        reset_vector_store()
        summary["vector_store_reset"] = True
    except Exception as e:
        summary["vector_store_reset"] = False
        summary["errors"].append(f"vector_store_reset: {e}")

    summary["name_fields_blanked"] = sum(scrub_json_names(p) for p in t["name_caches"])
    summary["settings_identity_cleared"] = any(clear_settings_identity(p) for p in t["settings"])
    summary["settings_name_cleared"] = summary["settings_identity_cleared"]
    summary["persona_overlay_reset"] = reset_persona_overlay()
    summary["faiss_reset"] = len(t["faiss"])
    summary["profiles_removed"] = len(t["profile"])
    summary["conversations_removed"] = len(t["conversations"])
    summary["transient_removed"] = len(t.get("transient", []))
    summary["runtime_wiped"] = len(t.get("runtime_wipe", []))

    if rebuild:
        summary["rebuild"] = rebuild_after_reset()

    summary["ok"] = not summary["errors"]
    return summary
