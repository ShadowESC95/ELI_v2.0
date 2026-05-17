from __future__ import annotations

import os

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory import (
    DBPaths,
    Memory,
    _clear_memory_singletons,
    get_agent_memory,
    get_memory,
    get_memory_authority,
    resolve_db_paths,
)

__all__ = [
    "DBPaths",
    "Memory",
    "resolve_db_paths",
    "get_memory",
    "get_agent_memory",
    "get_memory_authority",
    "_clear_memory_singletons",
    "add_memory",
    "search_memory",
    "recall_recent",
    "log_event",
    "get_memory_status",
    "memory_store_fn",
    "memory_search_fn",
    "memory_recent_fn",
]


def __getattr__(name: str):
    """Lazy-load memory_adapter exports to avoid circular import at package init."""
    if name in ("memory_store_fn", "memory_search_fn", "memory_recent_fn"):
        from .memory_adapter import memory_store_fn, memory_search_fn, memory_recent_fn  # noqa: F401
        _map = {
            "memory_store_fn": memory_store_fn,
            "memory_search_fn": memory_search_fn,
            "memory_recent_fn": memory_recent_fn,
        }
        return _map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

_legacy_memory_singleton: Optional[Memory] = None


def _use_legacy_memory_db(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("ELI_USE_LEGACY_MEMORY_DB", "0").strip().lower() in {"1", "true", "yes", "on"}


def _active_memory() -> Memory:
    return get_memory()


def _legacy_memory() -> Memory:
    """
    Legacy compatibility store for older tests/modules that expect
    eli.memory helpers to write to user.sqlite3 instead of user.sqlite3.
    """
    global _legacy_memory_singleton
    db = resolve_db_paths().memory_db
    if db is None:
        db = resolve_db_paths().user_db
    db = Path(db).expanduser().resolve()
    if _legacy_memory_singleton is None or Path(_legacy_memory_singleton.db_path).resolve() != db:
        _legacy_memory_singleton = Memory(db_path=db)
    return _legacy_memory_singleton


def _compat_memory(use_legacy_db: Optional[bool] = None) -> Memory:
    return _legacy_memory() if _use_legacy_memory_db(use_legacy_db) else _active_memory()


def add_memory(
    text: str,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
):
    mem = _compat_memory(kwargs.get('use_legacy_db'))
    if hasattr(mem, "store_memory"):
        return mem.store_memory(text, tags=tags or [], metadata=metadata or {})
    raise AttributeError("Memory.store_memory not found")


def search_memory(query: str, limit: int = 5, **kwargs: Any):
    mem = _compat_memory(kwargs.get('use_legacy_db'))

    if hasattr(mem, "search_memory"):
        return mem.search_memory(query, limit=limit)

    if hasattr(mem, "recall_memory"):
        return mem.recall_memory(query, limit=limit)

    raise AttributeError("No search-compatible method found on Memory")


def recall_recent(limit: int = 5, k: Optional[int] = None, **kwargs: Any):
    mem = _compat_memory(kwargs.get('use_legacy_db'))
    actual_limit = k if k is not None else limit

    if hasattr(mem, "recall_recent"):
        return mem.recall_recent(limit=actual_limit)

    if hasattr(mem, "get_recent_conversation"):
        return mem.get_recent_conversation(limit=actual_limit)

    return []


def log_event(event_type: str, details: Any):
    mem = get_memory()
    if hasattr(mem, "log_habit_event"):
        return mem.log_habit_event(event_type, details)
    raise AttributeError("Memory.log_habit_event not found")


def get_memory_status(db_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """
    Grounded telemetry helper used by UI/status answers.

    Returns counts from the actual SQLite file instead of making the model guess.
    """
    if db_path is None:
        resolved = resolve_db_paths().user_db or resolve_db_paths().memory_db
    else:
        resolved = Path(db_path).expanduser().resolve()

    db = Path(resolved).expanduser().resolve()
    out: Dict[str, Any] = {
        "ok": True,
        "db_path": str(db),
        "exists": db.exists(),
        "tables": [],
        "memory_entries": 0,
        "conversation_turns": 0,
        "distinct_sessions": 0,
        "db_size_mb": 0.0,
    }

    if not db.exists():
        out["ok"] = False
        out["error"] = f"database_not_found: {db}"
        return out

    out["db_size_mb"] = db.stat().st_size / 1048576.0

    con = sqlite3.connect(str(db))
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        out["tables"] = tables

        for tbl in ("memories", "memory", "eli_memory", "mem"):
            if tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                out["memory_entries"] = int(cur.fetchone()[0] or 0)
                break

        # Also count semantic user facts
        if "semantic" in tables:
            try:
                cur.execute("SELECT COUNT(*) FROM semantic")
                sem = int(cur.fetchone()[0] or 0)
                out["semantic_facts"] = sem
                out["memory_entries"] = out["memory_entries"] + sem
            except Exception:
                pass

        for tbl in ("conversation_turns", "conversations", "conversation", "chat_history", "history"):
            if tbl in tables:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                out["conversation_turns"] = int(cur.fetchone()[0] or 0)
                if tbl == "conversations":
                    try:
                        cur.execute(
                            "SELECT COUNT(DISTINCT session_id) FROM conversations WHERE COALESCE(session_id, '') <> ''"
                        )
                        out["distinct_sessions"] = int(cur.fetchone()[0] or 0)
                    except Exception:
                        out["distinct_sessions"] = 0
                break
    finally:
        con.close()

    return out

from .memory import get_search_memory, get_memory_authority, rebuild_vector_index_from_search_db

# === MKXI_LOCAL_DB_AUTHORITY_PATCH ===
from pathlib import Path as _MKXIPath
import os as _MKXIOS

def _mkxi_user_db_path():
    from eli.core.paths import get_paths as _mkxi_get_paths
    gp = _mkxi_get_paths()
    raw = (
        _MKXIOS.environ.get("ELI_MEMORY_DB")
        or _MKXIOS.environ.get("ELI_MEMORY_DB_PATH")
        or str(gp.user_db)
    )
    p = _MKXIPath(raw).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _mkxi_agent_db_path():
    from eli.core.paths import get_paths as _mkxi_get_paths
    gp = _mkxi_get_paths()
    raw = _MKXIOS.environ.get("ELI_AGENT_DB") or str(gp.agent_db)
    p = _MKXIPath(raw).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

# Compatibility helpers for resolve_db_paths / get_memory / get_agent_memory
# REMOVED. The previous shadows returned plain dicts (causing
# `'dict' object has no attribute 'user_db'` on every callsite using
# attribute access) and bypassed the canonical Memory(db_path=...)
# arg contract. The canonical versions imported from eli.memory.memory
# at the top of this file (line ~16) return proper DBPaths dataclasses
# and accept an optional db_path. _mkxi_user_db_path / _mkxi_agent_db_path
# above remain in place — they are independent helpers any caller can
# use directly to resolve a single db path under env-var precedence.

# ---------------------------------------------------------------------
# Compatibility public API
# ---------------------------------------------------------------------
# Older runtime/executor code may import store_memory directly from
# eli.memory. Keep this wrapper generic and user-neutral.

def store_memory(*args, **kwargs):
    """
    Compatibility wrapper for storing a memory.

    Delegates to the active Memory authority without hard-coded user data.
    """
    from eli.memory.memory import get_memory

    mem = get_memory()

    for method_name in ("store_memory", "add_memory", "remember", "store"):
        method = getattr(mem, method_name, None)
        if callable(method):
            return method(*args, **kwargs)

    raise AttributeError(
        "No supported memory store method found on active Memory authority."
    )


def recall_memory(*args, **kwargs):
    """
    Compatibility wrapper for recalling memories.
    """
    from eli.memory.memory import get_memory

    mem = get_memory()

    for method_name in ("recall_memory", "recall", "search_memory", "search"):
        method = getattr(mem, method_name, None)
        if callable(method):
            return method(*args, **kwargs)

    raise AttributeError(
        "No supported memory recall/search method found on active Memory authority."
    )

