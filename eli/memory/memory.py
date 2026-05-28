from __future__ import annotations

def _path_value(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# eli/memory/memory.py

import json
import os
import sqlite3
import sys as _sys
import threading
import time
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from eli.core import paths as core_paths


# ---------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class DBPaths:
    user_db: Path
    agent_db: Path
    memory_db: Optional[Path] = None


def _resolve_project_artifacts_dir() -> Path:
    """Single source of truth: follow eli.core.paths first."""
    try:
        if hasattr(core_paths, "get_artifact_dir"):
            return Path(core_paths.get_artifact_dir()).expanduser().resolve()
        return core_paths.get_paths().artifacts_dir.resolve()
    except Exception:
        pass

    v = os.environ.get("ELI_ARTIFACTS_DIR") or os.environ.get("ELI_ARTIFACTS")
    if v:
        return Path(v).expanduser().resolve()

    here = Path(__file__).resolve()
    eli_root = here.parents[1]
    return (eli_root / "artifacts").resolve()


def resolve_db_paths() -> DBPaths:
    """
    Canonical three-DB resolution.

    - memory_db: searchable memories + conversations (eli_memory.sqlite3)
    - user_db: user profile/state db
    - agent_db: proactive/agent/self-improvement db

    The actual path authority lives in eli.core.paths.
    This compatibility helper preserves older imports that still call resolve_db_paths().
    """
    paths = core_paths.get_paths()

    def _pick(name: str, fallback: Path) -> Path:
        fn = getattr(core_paths, name, None)
        if callable(fn):
            try:
                return Path(fn()).expanduser().resolve()
            except Exception:
                pass
        return Path(fallback).expanduser().resolve()

    return DBPaths(
        user_db=_pick("get_user_db_path", _path_value(paths, 'user_db')),
        agent_db=_pick("get_agent_db_path", _path_value(paths, 'agent_db')),
        memory_db=_pick("get_memory_db_path", _path_value(paths, 'memory_db')),
    )


# ---------------------------------------------------------------------
# Memory instances (per-db singletons)
# ---------------------------------------------------------------------

_memory_singletons: Dict[str, "Memory"] = {}
_memory_lock = threading.Lock()
# Compat: conftest does `mem_mod._memory_singleton = None` to reset cache.
_memory_singleton = None
_memory = None
_agent_memory_singleton = None
_agent_memory = None

# ── Recall write queue ────────────────────────────────────────────────────────
# recall_memory() fires UPDATE + INSERT on every read, creating write contention
# on the hot path. Queue write callables and flush in a background daemon thread.
_recall_write_queue: List = []  # list of (db_path, callable(conn))
_recall_write_lock = threading.Lock()
_RECALL_FLUSH_BATCH = 50  # flush when queue reaches this size


def _enqueue_recall_write(db_path: Path, fn) -> None:
    """Queue a write callable `fn(conn)` to be applied against `db_path`."""
    with _recall_write_lock:
        _recall_write_queue.append((db_path, fn))
        if len(_recall_write_queue) >= _RECALL_FLUSH_BATCH:
            _flush_recall_writes_locked()


def _flush_recall_writes_locked() -> None:
    """Drain the queue. Must be called with _recall_write_lock held."""
    if not _recall_write_queue:
        return
    batch = list(_recall_write_queue)
    _recall_write_queue.clear()
    by_db: Dict[Path, List] = {}
    for db_path, fn in batch:
        by_db.setdefault(db_path, []).append(fn)
    for db_path, fns in by_db.items():
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            try:
                for fn in fns:
                    try:
                        fn(conn)
                    except Exception:
                        pass
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass


def flush_recall_writes() -> None:
    """Public flush — call on idle or shutdown to drain the queue."""
    with _recall_write_lock:
        _flush_recall_writes_locked()


def _clear_memory_singletons() -> None:
    """Clear all cached Memory instances (call between tests)."""
    with _memory_lock:
        _memory_singletons.clear()
    try:
        import eli.runtime.self_improvement as _si

        _si._self_engine = None
    except Exception:
        pass


_this_module = _sys.modules[__name__]


class _MemoryModule(type(_this_module)):
    def __setattr__(self, name, value):
        if name in {"_memory_singleton", "_memory", "_agent_memory_singleton", "_agent_memory"} and value is None:
            _clear_memory_singletons()
        super().__setattr__(name, value)


_this_module.__class__ = _MemoryModule


def get_memory(db_path: Union[str, Path, None] = None) -> "Memory":
    """
    Get or create a Memory instance for the USER DB by default.

    Important contract:
    - get_memory()         -> user.sqlite3 only
    - get_agent_memory()   -> agent.sqlite3 only
    - get_search_memory()  -> memory_db when configured, else user.sqlite3
    """
    paths = resolve_db_paths()
    if db_path is None:
        db_path = _path_value(paths, 'user_db')
    db_path = Path(db_path).expanduser().resolve()
    key = str(db_path)

    with _memory_lock:
        if key not in _memory_singletons:
            # Canonical rule: default user memory writes only to its own DB.
            # No implicit fan-out into agent.sqlite3 or any secondary store.
            _memory_singletons[key] = Memory(db_path=db_path, secondary_paths=[])
        return _memory_singletons[key]


def get_agent_memory(db_path: Union[str, Path, None] = None) -> "Memory":
    """Get or create Memory for the AGENT DB."""
    paths = resolve_db_paths()
    if db_path is None:
        db_path = _path_value(paths, 'agent_db')
    return get_memory(db_path=db_path)


def get_search_memory(db_path: Union[str, Path, None] = None) -> "Memory":
    """Return the retrieval/search memory authority (memory_db when present, else user_db)."""
    paths = resolve_db_paths()
    if db_path is None:
        db_path = _path_value(paths, 'memory_db') or _path_value(paths, 'user_db')
    return get_memory(db_path=db_path)


def get_memory_authority() -> Dict[str, str]:
    paths = resolve_db_paths()
    return {
        "user_db": str(Path(_path_value(paths, 'user_db')).expanduser().resolve()) if _path_value(paths, 'user_db') else "",
        "agent_db": str(Path(_path_value(paths, 'agent_db')).expanduser().resolve()) if _path_value(paths, 'agent_db') else "",
        "memory_db": str(Path(_path_value(paths, 'memory_db')).expanduser().resolve()) if _path_value(paths, 'memory_db') else "",
    }


# ---------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------

import re as _re_sql


from eli.utils.log import get_logger
log = get_logger(__name__)

# Allowlist of known table names used in schema migrations.
_KNOWN_TABLES: frozenset = frozenset({
    "memories", "conversation_turns", "conversations", "session_summaries",
    "kg_entities", "kg_relations", "recall_log", "error_tracking",
    "improvements", "failures", "habit_rules", "habit_events",
    "memories_fts", "self_improvements", "capabilities",
    "agent_dispatches", "proactive_insights",
})

_IDENTIFIER_RE = _re_sql.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _validate_identifier(name: str, context: str = "identifier") -> str:
    """Validate a SQL identifier (table or column name) before f-string interpolation.

    Only allows characters safe for SQL identifiers.  Raises ValueError on
    anything that looks like an injection attempt.
    """
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid SQL {context} '{name}': only [A-Za-z0-9_] allowed"
        )
    return name


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _cols(conn: sqlite3.Connection, table: str) -> List[str]:
    t = _validate_identifier(table, "table")
    return [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    t = _validate_identifier(table, "table")
    cols = _cols(conn, table)
    if col not in cols:
        # ddl is e.g. "col_name TEXT DEFAULT NULL" — validate first token as the column name
        col_name = ddl.split()[0] if ddl else ""
        _validate_identifier(col_name, "column")
        conn.execute(f"ALTER TABLE {t} ADD COLUMN {ddl}")


# ---------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------

class _MemoryMeta(type):
    """Metaclass that intercepts Memory._instance = None to clear singleton cache."""

    def __setattr__(cls, name, value):
        if name == "_instance" and value is None:
            _clear_memory_singletons()
            return
        super().__setattr__(name, value)


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def _eli_count_table(conn, table_name: str) -> int:
    if not _eli_table_exists(conn, table_name):
        return 0
    row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
    return int((row[0] if row else 0) or 0)

def _eli_format_tags(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value if str(x).strip())
    return str(value or "")

def _add_column_if_missing(conn, table, name, decl):
    cols = _table_columns(conn, table)
    if name not in cols:
        t = _validate_identifier(table, "table")
        _validate_identifier(name, "column")
        conn.execute(f"ALTER TABLE {t} ADD COLUMN {name} {decl}")

def _ensure_memory_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            kind TEXT,
            text TEXT, value TEXT,
            content TEXT,
            tags TEXT,
            source TEXT,
            status TEXT,
            confidence REAL DEFAULT 1.0,
            weight REAL DEFAULT 1.0,
            importance REAL DEFAULT 0.5
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("timestamp", "REAL"),
        ("kind", "TEXT"),
        ("text", "TEXT"),
        ("content", "TEXT"),
        ("tags", "TEXT"),
        ("source", "TEXT"),
        ("status", "TEXT"),
        ("confidence", "REAL DEFAULT 1.0"),
        ("weight", "REAL DEFAULT 1.0"),
        ("importance", "REAL DEFAULT 0.5"),
    ]:
        _add_column_if_missing(conn, "memories", name, decl)

    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(text, tags, content='memories', content_rowid='id')
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, text, tags)
                VALUES (new.id, COALESCE(new.text, new.content, ''), COALESCE(new.tags, ''));
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text, tags)
                VALUES('delete', old.id, COALESCE(old.text, old.content, ''), COALESCE(old.tags, ''));
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, text, tags)
                VALUES('delete', old.id, COALESCE(old.text, old.content, ''), COALESCE(old.tags, ''));
                INSERT INTO memories_fts(rowid, text, tags)
                VALUES (new.id, COALESCE(new.text, new.content, ''), COALESCE(new.tags, ''));
            END
            """
        )
    except Exception:
        pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp REAL,
            ts REAL,
            created_at REAL,
            updated_at REAL,
            title TEXT
        )
        """
    )
    for name, decl in [
        ("user_id", "TEXT"),
        ("session_id", "TEXT"),
        ("role", "TEXT"),
        ("content", "TEXT"),
        ("timestamp", "REAL"),
        ("ts", "REAL"),
        ("created_at", "REAL"),
        ("updated_at", "REAL"),
        ("title", "TEXT"),
    ]:
        _add_column_if_missing(conn, "conversations", name, decl)

    # ── Performance indexes ─────────────────────────────────────────────────
    # memories(ts) — ORDER BY COALESCE(timestamp, ts) used in every recall query
    # conversations(user_id, session_id) — WHERE clause in search_conversations
    # conversation_turns(session_id, timestamp) — ORDER BY in deep history fallback
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_ts ON memories(ts DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_session "
            "ON conversations(user_id, session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_turns_session "
            "ON conversation_turns(session_id, timestamp DESC)"
        )
    except Exception:
        pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            session_id TEXT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            ts REAL
        )
        """
    )
    for name, decl in [
        ("timestamp", "REAL"),
        ("session_id", "TEXT"),
        ("user_id", "TEXT"),
        ("role", "TEXT"),
        ("content", "TEXT"),
        ("ts", "REAL"),
    ]:
        _add_column_if_missing(conn, "conversation_turns", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recall_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            query TEXT,
            result_count INTEGER,
            results_count INTEGER,
            memory_id INTEGER
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("timestamp", "REAL"),
        ("query", "TEXT"),
        ("result_count", "INTEGER"),
        ("results_count", "INTEGER"),
        ("memory_id", "INTEGER"),
    ]:
        _add_column_if_missing(conn, "recall_log", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            name TEXT,
            cmd TEXT,
            method TEXT,
            event_type TEXT,
            event TEXT,
            data TEXT,
            details TEXT,
            command TEXT,
            count INTEGER DEFAULT 0,
            timestamp REAL
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("name", "TEXT"),
        ("cmd", "TEXT"),
        ("method", "TEXT"),
        ("event_type", "TEXT"),
        ("event", "TEXT"),
        ("data", "TEXT"),
        ("details", "TEXT"),
        ("command", "TEXT"),
        ("count", "INTEGER DEFAULT 0"),
        ("timestamp", "REAL"),
    ]:
        _add_column_if_missing(conn, "habit_events", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            name TEXT,
            pattern TEXT,
            action TEXT,
            enabled INTEGER DEFAULT 1,
            command TEXT,
            trigger_phrase TEXT,
            action_type TEXT,
            hour INTEGER,
            minute INTEGER,
            days TEXT,
            timestamp REAL
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("name", "TEXT"),
        ("pattern", "TEXT"),
        ("action", "TEXT"),
        ("enabled", "INTEGER DEFAULT 1"),
        ("command", "TEXT"),
        ("trigger_phrase", "TEXT"),
        ("action_type", "TEXT"),
        ("hour", "INTEGER"),
        ("minute", "INTEGER"),
        ("days", "TEXT"),
        ("timestamp", "REAL"),
    ]:
        _add_column_if_missing(conn, "habit_rules", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            name TEXT,
            cmd TEXT,
            method TEXT,
            count INTEGER DEFAULT 0,
            hour INTEGER,
            minute INTEGER,
            timestamp REAL,
            command TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("name", "TEXT"),
        ("cmd", "TEXT"),
        ("method", "TEXT"),
        ("count", "INTEGER DEFAULT 0"),
        ("hour", "INTEGER"),
        ("minute", "INTEGER"),
        ("timestamp", "REAL"),
        ("command", "TEXT DEFAULT ''"),
        ("enabled", "INTEGER DEFAULT 1"),
    ]:
        _add_column_if_missing(conn, "habits", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS improvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            title TEXT,
            name TEXT,
            improvement TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            description TEXT,
            source TEXT,
            status TEXT,
            count INTEGER DEFAULT 1,
            area TEXT,
            category TEXT,
            priority INTEGER DEFAULT 1,
            created_at REAL
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("timestamp", "REAL"),
        ("title", "TEXT"),
        ("name", "TEXT"),
        ("improvement", "TEXT"),
        ("text", "TEXT"),
        ("content", "TEXT"),
        ("details", "TEXT"),
        ("description", "TEXT"),
        ("source", "TEXT"),
        ("status", "TEXT"),
        ("count", "INTEGER DEFAULT 1"),
        ("area", "TEXT"),
        ("category", "TEXT"),
        ("priority", "INTEGER DEFAULT 1"),
        ("created_at", "REAL"),
    ]:
        _add_column_if_missing(conn, "improvements", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            user_input TEXT,
            command TEXT,
            error TEXT,
            traceback TEXT,
            confidence REAL,
            low_confidence INTEGER DEFAULT 0,
            context TEXT,
            context_json TEXT,
            occurrence_count INTEGER DEFAULT 1,
            first_seen REAL,
            last_seen REAL,
            failure TEXT,
            name TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            description TEXT,
            source TEXT,
            signature TEXT,
            status TEXT,
            count INTEGER DEFAULT 1
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("timestamp", "REAL"),
        ("user_input", "TEXT"),
        ("command", "TEXT"),
        ("error", "TEXT"),
        ("traceback", "TEXT"),
        ("confidence", "REAL"),
        ("low_confidence", "INTEGER DEFAULT 0"),
        ("context", "TEXT"),
        ("context_json", "TEXT"),
        ("occurrence_count", "INTEGER DEFAULT 1"),
        ("first_seen", "REAL"),
        ("last_seen", "REAL"),
        ("failure", "TEXT"),
        ("name", "TEXT"),
        ("text", "TEXT"),
        ("content", "TEXT"),
        ("details", "TEXT"),
        ("description", "TEXT"),
        ("source", "TEXT"),
        ("signature", "TEXT"),
        ("status", "TEXT"),
        ("count", "INTEGER DEFAULT 1"),
    ]:
        _add_column_if_missing(conn, "failures", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            capability TEXT,
            rationale TEXT,
            proposed_name TEXT,
            reasoning TEXT,
            description TEXT,
            examples TEXT,
            plugin_code TEXT,
            status TEXT,
            priority TEXT,
            notes TEXT,
            created_at REAL,
            updated_at REAL,
            source TEXT,
            category TEXT
        )
        """
    )
    for name, decl in [
        ("ts", "REAL"),
        ("timestamp", "REAL"),
        ("capability", "TEXT"),
        ("rationale", "TEXT"),
        ("proposed_name", "TEXT"),
        ("reasoning", "TEXT"),
        ("description", "TEXT"),
        ("examples", "TEXT"),
        ("plugin_code", "TEXT"),
        ("status", "TEXT"),
        ("priority", "TEXT"),
        ("notes", "TEXT"),
        ("created_at", "REAL"),
        ("updated_at", "REAL"),
        ("source", "TEXT"),
        ("category", "TEXT"),
    ]:
        _add_column_if_missing(conn, "capability_proposals", name, decl)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, original TEXT, corrected TEXT, timestamp REAL, ts REAL)"
    )
    for name, decl in [("original", "TEXT"), ("corrected", "TEXT"), ("timestamp", "REAL"), ("ts", "REAL")]:
        _add_column_if_missing(conn, "corrections", name, decl)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, content TEXT, timestamp REAL, ts REAL)"
    )
    for name, decl in [("source", "TEXT"), ("content", "TEXT"), ("timestamp", "REAL"), ("ts", "REAL")]:
        _add_column_if_missing(conn, "observations", name, decl)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS error_tracking (id INTEGER PRIMARY KEY AUTOINCREMENT, error_type TEXT, details TEXT, timestamp REAL, occurrence_count INTEGER DEFAULT 1, first_seen REAL, last_seen REAL)"
    )
    for name, decl in [
        ("error_type", "TEXT"),
        ("details", "TEXT"),
        ("timestamp", "REAL"),
        ("occurrence_count", "INTEGER DEFAULT 1"),
        ("first_seen", "REAL"),
        ("last_seen", "REAL"),
    ]:
        _add_column_if_missing(conn, "error_tracking", name, decl)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS user_patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, pattern_type TEXT, pattern_data TEXT, timestamp REAL, ts REAL)"
    )
    for name, decl in [("pattern_type", "TEXT"), ("pattern_data", "TEXT"), ("timestamp", "REAL"), ("ts", "REAL")]:
        _add_column_if_missing(conn, "user_patterns", name, decl)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_replay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            input_text TEXT,
            output_text TEXT,
            action TEXT,
            outcome TEXT,
            reward REAL,
            metadata TEXT,
            timestamp REAL,
            ts REAL
        )
        """
    )
    for name, decl in [
        ("event_type", "TEXT"),
        ("input_text", "TEXT"),
        ("output_text", "TEXT"),
        ("action", "TEXT"),
        ("outcome", "TEXT"),
        ("reward", "REAL"),
        ("metadata", "TEXT"),
        ("timestamp", "REAL"),
        ("ts", "REAL"),
    ]:
        _add_column_if_missing(conn, "learning_replay", name, decl)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, summary TEXT, content TEXT, timestamp REAL, ts REAL)"
    )
    for name, decl in [("session_id", "TEXT"), ("summary", "TEXT"), ("content", "TEXT"), ("timestamp", "REAL"), ("ts", "REAL")]:
        _add_column_if_missing(conn, "session_summaries", name, decl)

def _table_columns(conn, table):
    try:
        t = _validate_identifier(table, "table")
        return [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
    except (ValueError, Exception):
        return []

def _memory_db_path_for_instance(self):
    db_path = getattr(self, "db_path", None)
    if not db_path:
        raise RuntimeError("Memory instance missing db_path")
    p = Path(str(db_path)).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def _add_contract_column(conn, table, name, decl):
    if name not in _contract_table_columns(conn, table):
        t = _validate_identifier(table, "table")
        _validate_identifier(name, "column")
        conn.execute(f"ALTER TABLE {t} ADD COLUMN {name} {decl}")

def _ensure_contract_schema(conn):
    # improvements
    conn.execute("""
        CREATE TABLE IF NOT EXISTS improvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            category TEXT,
            area TEXT,
            description TEXT,
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            created_at REAL,
            title TEXT,
            name TEXT,
            improvement TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            source TEXT,
            count INTEGER DEFAULT 1,
            suggestion TEXT,
            applied INTEGER DEFAULT 0
        )
    """)
    for name, decl in [
        ("ts", "REAL"), ("timestamp", "REAL"), ("category", "TEXT"), ("area", "TEXT"),
        ("description", "TEXT"), ("priority", "INTEGER DEFAULT 1"), ("status", "TEXT DEFAULT 'pending'"),
        ("created_at", "REAL"), ("title", "TEXT"), ("name", "TEXT"), ("improvement", "TEXT"),
        ("text", "TEXT"), ("content", "TEXT"), ("details", "TEXT"), ("source", "TEXT"),
        ("count", "INTEGER DEFAULT 1"), ("suggestion", "TEXT"), ("applied", "INTEGER DEFAULT 0"),
    ]:
        _add_contract_column(conn, "improvements", name, decl)

    # failures
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            user_input TEXT,
            command TEXT,
            error TEXT,
            confidence REAL DEFAULT 0.0,
            low_confidence INTEGER DEFAULT 0,
            context TEXT,
            context_json TEXT,
            occurrence_count INTEGER DEFAULT 1,
            first_seen REAL,
            last_seen REAL,
            failure TEXT,
            name TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            description TEXT,
            source TEXT,
            signature TEXT,
            status TEXT,
            count INTEGER DEFAULT 1,
            traceback TEXT
        )
    """)
    for name, decl in [
        ("ts", "REAL"), ("timestamp", "REAL"), ("user_input", "TEXT"), ("command", "TEXT"),
        ("error", "TEXT"), ("confidence", "REAL DEFAULT 0.0"), ("low_confidence", "INTEGER DEFAULT 0"),
        ("context", "TEXT"), ("context_json", "TEXT"), ("occurrence_count", "INTEGER DEFAULT 1"),
        ("first_seen", "REAL"), ("last_seen", "REAL"), ("failure", "TEXT"), ("name", "TEXT"),
        ("text", "TEXT"), ("content", "TEXT"), ("details", "TEXT"), ("description", "TEXT"),
        ("source", "TEXT"), ("signature", "TEXT"), ("status", "TEXT"), ("count", "INTEGER DEFAULT 1"),
        ("traceback", "TEXT"),
    ]:
        _add_contract_column(conn, "failures", name, decl)

def _contract_table_columns(conn, table):
    try:
        t = _validate_identifier(table, "table")
        return [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
    except (ValueError, Exception):
        return []

def _jsonify_contract_value(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(v)

def _now_ts():
    return float(time.time())

def _add_memory_column(conn, table, name, decl):
    if name not in _memory_table_columns(conn, table):
        t = _validate_identifier(table, "table")
        _validate_identifier(name, "column")
        conn.execute(f"ALTER TABLE {t} ADD COLUMN {name} {decl}")

def _ensure_full_memory_schema(conn):
    # Include `importance` in fresh DBs so all storage paths share one schema.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            value TEXT,
            content TEXT,
            tags TEXT,
            kind TEXT,
            ts REAL,
            timestamp REAL,
            source TEXT,
            status TEXT,
            weight REAL DEFAULT 1.0,
            confidence REAL DEFAULT 1.0,
            importance REAL DEFAULT 0.5
        )
    """)
    # Existing DBs get missing columns on connection open. Idempotent:
    # _add_memory_column is a no-op if the column already exists.
    for n, d in [
        ("content", "TEXT"), ("timestamp", "REAL"), ("source", "TEXT"),
        ("status", "TEXT"), ("weight", "REAL DEFAULT 1.0"), ("confidence", "REAL DEFAULT 1.0"),
        ("kind", "TEXT"), ("tags", "TEXT"), ("text", "TEXT"), ("ts", "REAL"),
        ("importance", "REAL DEFAULT 0.5")
    ]:
        _add_memory_column(conn, "memories", n, d)

    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(text, tags, content='memories', content_rowid='id')
        """)
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            timestamp REAL,
            ts REAL,
            created_at REAL,
            updated_at REAL,
            title TEXT
        )
    """)
    for n, d in [
        ("session_id", "TEXT"), ("user_id", "TEXT"), ("role", "TEXT"), ("content", "TEXT"),
        ("timestamp", "REAL"), ("ts", "REAL"), ("created_at", "REAL"), ("updated_at", "REAL"),
        ("title", "TEXT")
    ]:
        _add_memory_column(conn, "conversations", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            ts REAL,
            timestamp REAL
        )
    """)
    for n, d in [
        ("session_id", "TEXT"), ("user_id", "TEXT"), ("role", "TEXT"),
        ("content", "TEXT"), ("ts", "REAL"), ("timestamp", "REAL")
    ]:
        _add_memory_column(conn, "conversation_turns", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS recall_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            query TEXT,
            results_count INTEGER,
            result_count INTEGER,
            memory_id INTEGER
        )
    """)
    for n, d in [
        ("ts", "REAL"), ("timestamp", "REAL"), ("query", "TEXT"),
        ("results_count", "INTEGER"), ("result_count", "INTEGER"), ("memory_id", "INTEGER")
    ]:
        _add_memory_column(conn, "recall_log", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS habit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            event TEXT,
            details TEXT,
            data TEXT,
            timestamp REAL,
            ts REAL,
            name TEXT,
            cmd TEXT,
            method TEXT,
            command TEXT
        )
    """)
    for n, d in [
        ("event_type", "TEXT"), ("event", "TEXT"), ("details", "TEXT"), ("data", "TEXT"),
        ("timestamp", "REAL"), ("ts", "REAL"), ("name", "TEXT"), ("cmd", "TEXT"),
        ("method", "TEXT"), ("command", "TEXT")
    ]:
        _add_memory_column(conn, "habit_events", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS habit_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            command TEXT,
            hour INTEGER,
            minute INTEGER,
            days TEXT,
            enabled INTEGER DEFAULT 1,
            timestamp REAL,
            ts REAL,
            pattern TEXT,
            action TEXT,
            trigger_phrase TEXT,
            action_type TEXT
        )
    """)
    for n, d in [
        ("name", "TEXT"), ("command", "TEXT"), ("hour", "INTEGER"), ("minute", "INTEGER"),
        ("days", "TEXT"), ("enabled", "INTEGER DEFAULT 1"), ("timestamp", "REAL"),
        ("ts", "REAL"), ("pattern", "TEXT"), ("action", "TEXT"),
        ("trigger_phrase", "TEXT"), ("action_type", "TEXT")
    ]:
        _add_memory_column(conn, "habit_rules", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            cmd TEXT,
            method TEXT,
            count INTEGER DEFAULT 0,
            hour INTEGER,
            minute INTEGER,
            timestamp REAL,
            command TEXT,
            enabled INTEGER DEFAULT 1,
            ts REAL
        )
    """)
    for n, d in [
        ("name", "TEXT"), ("cmd", "TEXT"), ("method", "TEXT"), ("count", "INTEGER DEFAULT 0"),
        ("hour", "INTEGER"), ("minute", "INTEGER"), ("timestamp", "REAL"),
        ("command", "TEXT"), ("enabled", "INTEGER DEFAULT 1"), ("ts", "REAL")
    ]:
        _add_memory_column(conn, "habits", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original TEXT,
            corrected TEXT,
            timestamp REAL,
            ts REAL
        )
    """)
    for n, d in [("original", "TEXT"), ("corrected", "TEXT"), ("timestamp", "REAL"), ("ts", "REAL")]:
        _add_memory_column(conn, "corrections", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            category TEXT,
            observation TEXT,
            content TEXT,
            text TEXT,
            details TEXT,
            timestamp REAL,
            ts REAL
        )
    """)
    for n, d in [
        ("source", "TEXT"), ("category", "TEXT"), ("observation", "TEXT"),
        ("content", "TEXT"), ("text", "TEXT"), ("details", "TEXT"),
        ("timestamp", "REAL"), ("ts", "REAL")
    ]:
        _add_memory_column(conn, "observations", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            user_id TEXT,
            summary TEXT,
            content TEXT,
            turns_count INTEGER,
            started_at REAL,
            ended_at REAL,
            source TEXT,
            timestamp REAL,
            ts REAL
        )
    """)
    for n, d in [
        ("session_id", "TEXT"), ("user_id", "TEXT"), ("summary", "TEXT"),
        ("content", "TEXT"), ("turns_count", "INTEGER"), ("started_at", "REAL"),
        ("ended_at", "REAL"), ("source", "TEXT"), ("timestamp", "REAL"), ("ts", "REAL")
    ]:
        _add_memory_column(conn, "session_summaries", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS improvements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            category TEXT,
            area TEXT,
            description TEXT,
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            created_at REAL,
            title TEXT,
            name TEXT,
            improvement TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            source TEXT,
            count INTEGER DEFAULT 1,
            suggestion TEXT,
            applied INTEGER DEFAULT 0
        )
    """)
    for n, d in [
        ("ts", "REAL"), ("timestamp", "REAL"), ("category", "TEXT"), ("area", "TEXT"),
        ("description", "TEXT"), ("priority", "INTEGER DEFAULT 1"), ("status", "TEXT"),
        ("created_at", "REAL"), ("title", "TEXT"), ("name", "TEXT"),
        ("improvement", "TEXT"), ("text", "TEXT"), ("content", "TEXT"),
        ("details", "TEXT"), ("source", "TEXT"), ("count", "INTEGER DEFAULT 1"),
        ("suggestion", "TEXT"), ("applied", "INTEGER DEFAULT 0")
    ]:
        _add_memory_column(conn, "improvements", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            user_input TEXT,
            command TEXT,
            error TEXT,
            traceback TEXT,
            confidence REAL,
            low_confidence INTEGER DEFAULT 0,
            context TEXT,
            context_json TEXT,
            occurrence_count INTEGER DEFAULT 1,
            first_seen REAL,
            last_seen REAL,
            failure TEXT,
            name TEXT,
            text TEXT,
            content TEXT,
            details TEXT,
            description TEXT,
            source TEXT,
            signature TEXT,
            status TEXT,
            count INTEGER DEFAULT 1
        )
    """)
    for n, d in [
        ("ts", "REAL"), ("timestamp", "REAL"), ("user_input", "TEXT"), ("command", "TEXT"),
        ("error", "TEXT"), ("traceback", "TEXT"), ("confidence", "REAL"),
        ("low_confidence", "INTEGER DEFAULT 0"), ("context", "TEXT"), ("context_json", "TEXT"),
        ("occurrence_count", "INTEGER DEFAULT 1"), ("first_seen", "REAL"), ("last_seen", "REAL"),
        ("failure", "TEXT"), ("name", "TEXT"), ("text", "TEXT"), ("content", "TEXT"),
        ("details", "TEXT"), ("description", "TEXT"), ("source", "TEXT"),
        ("signature", "TEXT"), ("status", "TEXT"), ("count", "INTEGER DEFAULT 1")
    ]:
        _add_memory_column(conn, "failures", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS capability_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            timestamp REAL,
            proposed_name TEXT,
            capability TEXT,
            description TEXT,
            examples TEXT,
            plugin_code TEXT,
            reasoning TEXT,
            rationale TEXT,
            status TEXT DEFAULT 'pending',
            priority TEXT,
            notes TEXT,
            created_at REAL,
            updated_at REAL,
            source TEXT,
            category TEXT
        )
    """)
    for n, d in [
        ("ts", "REAL"), ("timestamp", "REAL"), ("proposed_name", "TEXT"), ("capability", "TEXT"),
        ("description", "TEXT"), ("examples", "TEXT"), ("plugin_code", "TEXT"),
        ("reasoning", "TEXT"), ("rationale", "TEXT"), ("status", "TEXT"),
        ("priority", "TEXT"), ("notes", "TEXT"), ("created_at", "REAL"),
        ("updated_at", "REAL"), ("source", "TEXT"), ("category", "TEXT")
    ]:
        _add_memory_column(conn, "capability_proposals", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT,
            details TEXT,
            timestamp REAL,
            occurrence_count INTEGER DEFAULT 1,
            first_seen REAL,
            last_seen REAL
        )
    """)
    for n, d in [
        ("error_type", "TEXT"), ("details", "TEXT"), ("timestamp", "REAL"),
        ("occurrence_count", "INTEGER DEFAULT 1"), ("first_seen", "REAL"), ("last_seen", "REAL")
    ]:
        _add_memory_column(conn, "error_tracking", n, d)

def _memory_table_columns(conn, table):
    try:
        t = _validate_identifier(table, "table")
        return [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
    except (ValueError, Exception):
        return []

def _examples_json(v):
    if v is None:
        return "[]"
    if isinstance(v, str):
        try:
            json.loads(v)
            return v
        except Exception:
            return json.dumps([v], ensure_ascii=False)
    try:
        return json.dumps(list(v), ensure_ascii=False)
    except Exception:
        return json.dumps([str(v)], ensure_ascii=False)

def _memory_connection(self):
    p = _path_from_args(db_path=getattr(self, "db_path", None), db_type=getattr(self, "db_type", None))
    self.db_path = p
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")  # 64 MB page cache
    _ensure_full_memory_schema(conn)
    conn.commit()
    return conn

def _get_habit_events_window(self, event_type=None, days=14):
    window = _now_ts() - float(days) * 86400.0
    conn = self._get_connection()
    try:
        sql = "SELECT id, COALESCE(event_type, event, name, ''), COALESCE(details, data, ''), COALESCE(timestamp, ts, 0) FROM habit_events WHERE COALESCE(timestamp, ts, 0) >= ?"
        params = [window]
        if event_type:
            sql += " AND COALESCE(event_type, event, name, '') = ?"
            params.append(event_type)
        sql += " ORDER BY COALESCE(timestamp, ts, 0) ASC"
        rows = conn.execute(sql, params).fetchall()
        out = []
        for rid, et, det, ts in rows:
            parsed = det
            if isinstance(det, str):
                try:
                    parsed = json.loads(det)
                except Exception:
                    parsed = det
            out.append({
                "id": rid,
                "event_type": et,
                "details": parsed,
                "data": parsed,
                "timestamp": ts,
            })
        return out
    finally:
        conn.close()

def _has_table(conn, table):
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
    except Exception:
        return False

def _insert_payload(conn, table, payload):
    cols = set(_memory_table_columns(conn, table))
    ordered = [k for k in payload.keys() if k in cols]
    vals = [payload[k] for k in ordered]
    sql = f"INSERT INTO {table} ({', '.join(ordered)}) VALUES ({', '.join(['?'] * len(ordered))})"
    cur = conn.execute(sql, vals)
    return int(cur.lastrowid)

def _jsonify_value(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(v)

def _norm_text(v):
    if v is None:
        return ""
    return str(v)

def _path_from_args(db_path=None, db_type=None):
    if db_path is None:
        paths = resolve_db_paths()
        if db_type == "agent":
            db_path = _path_value(paths, 'agent_db')
        elif db_type == "memory":
            db_path = getattr(paths, "memory_db", None) or _path_value(paths, 'user_db')
        else:
            db_path = _path_value(paths, 'user_db')

    p = Path(str(db_path)).expanduser()
    suffix = p.suffix.lower()

    if suffix not in {".db", ".sqlite", ".sqlite3"}:
        name = (db_type or "").strip().lower()
        if name == "agent":
            p = p / "agent.sqlite3"
        elif name == "memory":
            p = p / "eli_memory.sqlite3"
        else:
            p = p / "user.sqlite3"

    p.parent.mkdir(parents=True, exist_ok=True)
    return p.resolve()

def _ensure_profile_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT,
            pattern_data TEXT,
            timestamp REAL,
            ts REAL
        )
    """)
    for n, d in [
        ("pattern_type", "TEXT"),
        ("pattern_data", "TEXT"),
        ("timestamp", "REAL"),
        ("ts", "REAL"),
    ]:
        _add_memory_column(conn, "user_patterns", n, d)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_replay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            input_text TEXT,
            output_text TEXT,
            action TEXT,
            outcome TEXT,
            reward REAL,
            metadata TEXT,
            timestamp REAL,
            ts REAL
        )
    """)
    for n, d in [
        ("event_type", "TEXT"),
        ("input_text", "TEXT"),
        ("output_text", "TEXT"),
        ("action", "TEXT"),
        ("outcome", "TEXT"),
        ("reward", "REAL"),
        ("metadata", "TEXT"),
        ("timestamp", "REAL"),
        ("ts", "REAL"),
    ]:
        _add_memory_column(conn, "learning_replay", n, d)

    if _has_table(conn, "session_summaries"):
        for n, d in [
            ("user_id", "TEXT"),
            ("started_at", "REAL"),
            ("ended_at", "REAL"),
            ("source", "TEXT"),
            ("turns_count", "INTEGER"),
            ("timestamp", "REAL"),
            ("ts", "REAL"),
        ]:
            _add_memory_column(conn, "session_summaries", n, d)

    if _has_table(conn, "observations"):
        for n, d in [
            ("category", "TEXT"),
            ("observation", "TEXT"),
            ("content", "TEXT"),
            ("text", "TEXT"),
            ("details", "TEXT"),
            ("source", "TEXT"),
            ("timestamp", "REAL"),
            ("ts", "REAL"),
        ]:
            _add_memory_column(conn, "observations", n, d)

def _jsonify_profile_value(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(v)

def _profile_now_ts():
    return float(time.time())

def _eli_table_exists(conn, table_name):
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


class Memory(metaclass=_MemoryMeta):
    """
    SQLite-backed memory store with optional secondary writes.
    """

    def __init__(self, db_path=None, db_type=None, secondary_paths=None, *args, **kwargs):
        dtype = db_type or kwargs.get("db_type")
        self.db_path = _path_from_args(db_path=db_path, db_type=dtype)
        self.secondary_paths = secondary_paths or []
        if dtype:
            self.db_type = str(dtype)
        else:
            self.db_type = "agent" if self.db_path.name.lower() == "agent.sqlite3" else "user"
        conn = self._get_connection()
        conn.close()

    def init_db(self) -> None:
        self._ensure_tables()

    def init_self_improvement_tables(self) -> None:
        self._ensure_tables()

    # -----------------------------
    # connection
    # -----------------------------

    def _get_connection(self):
        conn = _memory_connection(self)
        _ensure_profile_schema(conn)
        conn.commit()
        return conn

    def _ensure_tables(self):
        conn = sqlite3.connect(str(_memory_db_path_for_instance(self)))
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            _ensure_memory_schema(conn)
            conn.commit()
        finally:
            conn.close()

    @property
    def vector_store(self):
        try:
            from eli.memory.vector_store import get_vector_store
            return get_vector_store()
        except Exception:
            return None

    def _store_to_db(self, conn: sqlite3.Connection, text: str, tags: Optional[List[str]] = None,
                     source: str = "user", kind: str = "memory", confidence: float = 1.0,
                     ts: float = None, importance: float = 0.5) -> int:
        """Internal method to write a memory to a single DB connection."""
        t = (text or "").strip()
        if not t:
            raise ValueError("empty_text")
        if isinstance(tags, str):
            tags = [x.strip() for x in tags.split(",") if x.strip()]
        tag_blob = ",".join([x.strip() for x in (tags or []) if x.strip()])
        if ts is None:
            ts = time.time()
        cur = conn.execute(
            "INSERT INTO memories (ts, timestamp, kind, text, value, tags, source, confidence, weight, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, ts, kind, t, t, tag_blob, source, float(confidence), 1.0, float(importance)),
        )
        rowid = cur.lastrowid
        try:
            conn.execute(
                "INSERT INTO memories_fts(rowid, text, tags) VALUES (?, ?, ?)",
                (rowid, t, tag_blob),
            )
        except Exception:
            pass
        return rowid

    @staticmethod
    def _score_importance(text: str, tags: Optional[list], source: str, kind: str) -> float:
        """
        Heuristically score memory importance (0.0–1.0) so high-salience
        memories surface higher in recall rankings.

        Scoring rules (additive, clamped to [0.05, 1.0]):
          +0.30  user explicitly asked to remember ("remember", "store", "note that")
          +0.20  identity/preference/name information
          +0.15  source == "user" (user-authored is more salient than ELI-inferred)
          +0.10  kind in {"preference", "fact", "identity"} (structured facts)
          +0.10  tagged with "important", "key", "critical", "remember"
          +0.05  longer text (≥80 chars signals substance)
          -0.20  kind == "reflection" or source == "awareness" (auto-generated, less salient)
          -0.10  kind == "system" (internal bookkeeping)
        """
        score = 0.30  # baseline
        low = (text or "").lower()
        tag_str = " ".join(str(t) for t in (tags or [])).lower()

        if any(k in low for k in ("remember ", "store this", "note that", "don't forget",
                                  "make a note", "save that", "keep in mind")):
            score += 0.30
        if any(k in low for k in ("my name is", "i am ", "i'm ", "i prefer ", "i like ",
                                  "i don't like", "i work ", "i use ", "my job", "i live")):
            score += 0.20
        if source == "user":
            score += 0.15
        if kind in ("preference", "fact", "identity", "note"):
            score += 0.10
        if any(k in tag_str for k in ("important", "key", "critical", "remember", "preference")):
            score += 0.10
        if len(text or "") >= 80:
            score += 0.05
        if kind in ("reflection", "auto") or source in ("awareness", "reflection"):
            score -= 0.20
        if kind == "system":
            score -= 0.10
        return max(0.05, min(1.0, score))

    def store_memory(
        self,
        text: str,
        tags: Optional[List[str]] = None,
        source: str = "user",
        kind: str = "memory",
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        importance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Store memory in primary DB and all secondary DBs.

        Parameters
        ----------
        importance : override the auto-computed salience score (0.0–1.0).
            Pass None to let _score_importance compute it automatically.
        """
        t = (text or "").strip()
        if not t:
            return {"ok": False, "error": "empty_text"}

        # Persistence gate is part of the normal write path.
        # Skip persistence gate in test mode
        if os.environ.get("ELI_TEST_MODE") == "1":
            pass
        elif callable(_eli_should_store_memory_text):
            if not _eli_should_store_memory_text(t, role=str(source or "user"), tags=tags):
                return {"ok": True, "skipped": True, "reason": "persistence_gate"}

        meta = metadata or {}
        if isinstance(meta, dict):
            source = str(meta.get("source", source) or source)
            kind = str(meta.get("kind", kind) or kind)
            try:
                confidence = float(meta.get("confidence", confidence))
            except Exception:
                confidence = float(confidence)
            if importance is None and "importance" in meta:
                try:
                    importance = float(meta["importance"])
                except Exception:
                    pass
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Auto-score importance when not explicitly provided
        if importance is None:
            importance = self._score_importance(t, tags, source, kind)

        ts = time.time()

        # Write to primary
        conn_primary = self._get_connection()
        try:
            rowid = self._store_to_db(conn_primary, t, tags, source, kind, confidence, ts,
                                       importance=importance)
            conn_primary.commit()
        finally:
            conn_primary.close()
        # Also index in FAISS vector store
        try:
            from eli.memory.vector_store import get_vector_store
            vs = get_vector_store()
            if vs is not None:
                added_to_vector_store = vs.add(
                    t,
                    metadata={
                        "memory_id": rowid,
                        "kind": kind,
                        "source": source,
                        "tags": tags if isinstance(tags, str) else ",".join(tags or []),
                        "importance": importance,
                    },
                )
                if added_to_vector_store and hasattr(vs, "flush"):
                    vs.flush()
        except Exception:
            pass

        # Extract entity-relation triples into knowledge graph (fire-and-forget)
        try:
            from eli.memory.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            kg.extract_from_memory(t, source=source)
        except Exception:
            pass

        # Write to secondaries
        for sec_path in self.secondary_paths:
            try:
                sec_conn = sqlite3.connect(sec_path)
                sec_conn.execute("PRAGMA journal_mode=WAL;")
                sec_conn.execute("PRAGMA synchronous=NORMAL;")
                _ensure_memory_schema(sec_conn)
                self._store_to_db(sec_conn, t, tags, source, kind, confidence, ts,
                                   importance=importance)
                sec_conn.commit()
                sec_conn.close()
            except Exception as e:
                log.debug(f"[MEMORY] Failed to write to secondary {sec_path}: {e}")

        # World-model sync is part of the normal write path.
        _eli_sync_world_model_from_memory(self, kind="memory",
                                          role=str(source or "user"),
                                          text=t, tags=tags)

        return {"ok": True, "id": rowid, "importance": importance}

    def add_memory(self, text: str, tags: Union[str, List[str], None] = None) -> Optional[Dict[str, Any]]:
        if isinstance(tags, str):
            tags_list = [tags]
        else:
            tags_list = tags
        return self.store_memory(text, tags=tags_list or [])


    def get_recent_semantic_memories(self, limit=20):
        conn = self._get_connection()
        try:
            if not _eli_table_exists(conn, "memories"):
                return []
            rows = conn.execute("""
                SELECT id, COALESCE(timestamp, ts, id), COALESCE(kind,''), COALESCE(text,''), COALESCE(tags,''), COALESCE(source,'')
                FROM memories
                ORDER BY COALESCE(timestamp, ts, id) DESC
                LIMIT ?
            """, (max(int(limit) * 8, 160),)).fetchall()
            out = []
            for r in rows:
                kind = str(r[2] or '').lower()
                tags = str(r[4] or '').lower()
                source = str(r[5] or '').lower()
                text = str(r[3] or '').strip()
                if not text:
                    continue
                if kind in {'reflection', 'assistant_insight', 'conversation', 'session_summary'}:
                    continue
                if 'reflection' in tags or 'session_summary' in tags or 'continuity' in tags:
                    continue
                if source == 'session_end':
                    continue
                out.append({'id': r[0], 'timestamp': r[1], 'kind': r[2], 'text': text, 'tags': r[4], 'source': r[5]})
                if len(out) >= int(limit):
                    break
            return out
        finally:
            conn.close()

    def recall_memory(self, query, limit=10, keyword_only: bool = False):
        q = _norm_text(query).strip()
        if not q:
            return []

        limit = int(limit or 10)
        conn = self._get_connection()
        try:
            cols = _memory_table_columns(conn, "memories")
            text_expr = "LOWER(COALESCE(text, content, ''))" if "content" in cols else "LOWER(COALESCE(text, ''))"
            tags_expr = "LOWER(COALESCE(tags, ''))"
            time_expr = "COALESCE(timestamp, ts, 0)"

            # importance column present in schema — use it in ordering
            imp_expr = "COALESCE(importance, 0.5)" if "importance" in cols else "0.5"

            # Kinds/tags that are noise for recall: ELI's old responses,
            # conversation blobs, and auto-generated meta-commentary.
            # These are stored for audit/self-improvement but must NOT
            # surface as user-facing recalled memories.
            _noise_kinds = (
                "assistant_insight", "episodic", "reflection",
            )
            _noise_sources = (
                "orchestrator",
            )
            # Noise tag patterns (covers kind='memory' entries that are
            # actually reflections or assistant responses by their tags)
            _tags_col   = "LOWER(COALESCE(m.tags, ''))" if "tags" in cols else "''"
            _tags_col_t = "LOWER(COALESCE(tags, ''))"   if "tags" in cols else "''"

            # kind/source filter expression — works even when the column is NULL
            _kind_col   = "COALESCE(m.kind, '')"   if "kind"   in cols else "''"
            _source_col = "COALESCE(m.source, '')" if "source" in cols else "''"
            _kind_filter = (
                f"AND {_kind_col} NOT IN ({', '.join('?' * len(_noise_kinds))}) "
                f"AND {_source_col} NOT IN ({', '.join('?' * len(_noise_sources))}) "
                f"AND {_tags_col} NOT LIKE '%reflection%' "
                f"AND {_tags_col} NOT LIKE '%assistant_insight%' "
                f"AND {_tags_col} NOT LIKE '%session_summary%' "
                f"AND LENGTH(COALESCE(m.text, m.content, '')) <= 1500"
            )
            _kind_params = list(_noise_kinds) + list(_noise_sources)

            # Same filter for plain-table queries (no 'm.' alias)
            _kind_col_t   = "COALESCE(kind, '')"   if "kind"   in cols else "''"
            _source_col_t = "COALESCE(source, '')" if "source" in cols else "''"
            _kind_filter_t = (
                f"AND {_kind_col_t} NOT IN ({', '.join('?' * len(_noise_kinds))}) "
                f"AND {_source_col_t} NOT IN ({', '.join('?' * len(_noise_sources))}) "
                f"AND {_tags_col_t} NOT LIKE '%reflection%' "
                f"AND {_tags_col_t} NOT LIKE '%assistant_insight%' "
                f"AND {_tags_col_t} NOT LIKE '%session_summary%' "
                f"AND LENGTH(COALESCE(text, content, '')) <= 1500"
            )

            # --- Stage 5: Vector semantic search (primary path) ---
            # FAISS runs first.  FTS5/LIKE only runs as a supplementary
            # path when the vector index is empty or returns fewer than
            # limit // 2 results (e.g. very short query or cold start).
            # When keyword_only=True (called from orchestrator's keyword_search),
            # FAISS is skipped entirely — the orchestrator runs its own dedicated
            # semantic_search() step, so running FAISS here would produce
            # duplicate vector hits with a mismatched "fts5" source label.
            vector_results = []
            _vector_index_populated = False
            if not keyword_only:
                try:
                    from eli.memory.vector_store import get_vector_store
                    _vs = get_vector_store()
                    _idx = getattr(_vs, '_index', None) if _vs is not None else None
                    _ntotal = int(getattr(_idx, 'ntotal', 0) or 0)
                    _vector_index_populated = _ntotal > 0
                    if _vs is not None and _ntotal > 0:
                        _hits = _vs.search(q, top_k=limit) or []
                        for h in _hits:
                            vector_results.append({
                                'id': h.get('memory_id', f"vec:{h.get('pos', 0)}"),
                                'ts': h.get('ts', 0),
                                'timestamp': h.get('ts', 0),
                                'text': h.get('text', ''),
                                'tags': h.get('tags', ''),
                                'weight': float(h.get('score', 0.5)) + 0.5,
                                'importance': float(h.get('score', 0.5)),
                                '_source': 'vector',
                            })
                except Exception:
                    pass

            # --- Stage 6: FTS5 keyword search (supplementary / fallback) ---
            # Always run in keyword_only mode. Otherwise run when vector returned
            # fewer than limit//2 results or the index is empty.
            _need_keyword = keyword_only or (not _vector_index_populated) or (len(vector_results) < max(1, limit // 2))
            fts_rows = []
            if _need_keyword and _has_table(conn, "memories_fts"):
                try:
                    fts_q = " OR ".join(
                        f'"{t}"' for t in re.split(r"[^a-zA-Z0-9_]+", q) if len(t) > 1
                    )
                    if fts_q:
                        fts_rows = conn.execute(
                            f"""
                            SELECT m.id, {time_expr}, COALESCE(m.text, m.content, ''),
                                   COALESCE(m.tags, ''), COALESCE(m.weight, 1.0),
                                   {imp_expr}
                            FROM memories m
                            JOIN memories_fts f ON m.id = f.rowid
                            WHERE memories_fts MATCH ?
                            {_kind_filter}
                            ORDER BY ({imp_expr} * 0.6 + {time_expr} * 0.0000001) DESC
                            LIMIT ?
                            """,
                            (fts_q, *_kind_params, limit),
                        ).fetchall()
                except Exception:
                    fts_rows = []

            # --- LIKE fallback if both vector and FTS5 are empty ---
            like_rows = []
            like = f"%{q.lower()}%"
            if _need_keyword and not fts_rows:
                try:
                    like_rows = conn.execute(
                        f"""
                        SELECT id, {time_expr}, COALESCE(text, content, ''), COALESCE(tags, ''),
                               COALESCE(weight, 1.0), {imp_expr}
                        FROM memories
                        WHERE ({text_expr} LIKE ? OR {tags_expr} LIKE ?)
                        {_kind_filter_t}
                        ORDER BY ({imp_expr} * 0.6 + {time_expr} * 0.0000001) DESC
                        LIMIT ?
                        """,
                        (like, like, *_kind_params, limit),
                    ).fetchall()
                except Exception:
                    like_rows = []

            if _need_keyword and not fts_rows and not like_rows:
                toks = [
                    t.lower()
                    for t in re.split(r"[^a-zA-Z0-9_]+", q)
                    if t and len(t) > 1
                ]
                toks = [t for t in toks if t not in {
                    "the","and","for","with","that","this","from","into","your","have","using",
                    "about","what","when","where","which","will","would","should","could"
                }]
                if toks:
                    clauses = []
                    params = []
                    for tok in toks:
                        clauses.append(f"({text_expr} LIKE ? OR {tags_expr} LIKE ?)")
                        params.extend([f"%{tok}%", f"%{tok}%"])
                    params.extend(_kind_params)
                    params.append(limit)
                    like_rows = conn.execute(
                        f"""
                        SELECT id, {time_expr}, COALESCE(text, content, ''), COALESCE(tags, ''),
                               COALESCE(weight, 1.0), {imp_expr}
                        FROM memories
                        WHERE ({' OR '.join(clauses)})
                        {_kind_filter_t}
                        ORDER BY ({imp_expr} * 0.6 + {time_expr} * 0.0000001) DESC
                        LIMIT ?
                        """,
                        params,
                    ).fetchall()

            # Convert DB rows to dicts — row format: (id, ts, text, tags, weight, importance)
            keyword_results = [
                {"id": r[0], "ts": r[1], "timestamp": r[1], "text": r[2], "tags": r[3],
                 "weight": r[4], "importance": r[5] if len(r) > 5 else 0.5,
                 "_source": "fts" if fts_rows else "like"}
                for r in (fts_rows or like_rows)[:limit]
            ]

            # --- Stage 8: Hybrid Merge — deduplicate and combine ---
            seen_texts: set = set()
            out: List[Dict] = []
            # Interleave: prefer vector hits (semantic) then keyword hits
            for result_list in (vector_results, keyword_results):
                for r in result_list:
                    txt = (r.get("text") or "").strip()[:120]
                    if txt and txt not in seen_texts:
                        seen_texts.add(txt)
                        out.append(r)
                    elif not txt:
                        out.append(r)
            # Sort merged results by composite score: importance × 0.5 + weight × 0.3 + recency × 0.2
            sort_now = time.time()
            def _ts_float(x):
                raw = x.get("ts") or x.get("timestamp") or 0
                try:
                    return float(raw)
                except (ValueError, TypeError):
                    return 0.0
            out.sort(
                key=lambda x: (
                    float(x.get("importance", 0.5) or 0.5) * 0.5
                    + float(x.get("weight", 1.0) or 1.0) * 0.3
                    + max(0.0, 1.0 - (sort_now - _ts_float(x)) / (86400 * 30)) * 0.2
                ),
                reverse=True,
            )

            def _postmerge_noise(hit):
                _tags = str(hit.get('tags', '') or '').lower()
                _kind = str(hit.get('kind', '') or '').lower()
                _source = str(hit.get('source', '') or hit.get('_source', '') or '').lower()
                _text = str(hit.get('text', '') or '').lower()

                if 'reflection' in _tags or _kind == 'reflection' or _source == 'reflection' or _text.startswith('reflection ('):
                    return True
                if 'session_summary' in _tags or 'continuity' in _tags or _text.startswith('session context:'):
                    return True
                if 'capability_change' in _tags or 'self_awareness' in _tags or _text.startswith('capability inventory updated:'):
                    return True
                if _tags.strip() == 'test' or _kind == 'test' or _source == 'test':
                    return True
                if 'e2e_test_' in _tags or _text.startswith('e2e test:') or 'test_enterprise_v2:' in _text:
                    return True
                return False

            _filtered = []
            _seen_filtered = set()
            for _r in out:
                if _postmerge_noise(_r):
                    continue
                _txt = str(_r.get('text', '') or '').strip()
                _key = _txt[:160].lower() if _txt else f"__id__:{_r.get('id')}"
                if _key in _seen_filtered:
                    continue
                _seen_filtered.add(_key)
                _filtered.append(_r)
            out = _filtered

            _q_low = q.lower()
            _identity_query = bool(re.search(
                r"\b(who am i|my name|name|remember me|about me|user|identity)\b",
                _q_low,
            ))

            # Only inject semantic identity facts when the query is actually about identity/user facts.
            if _identity_query:
                try:
                    if _has_table(conn, "semantic"):
                        sem_rows = conn.execute(
                            "SELECT id, fact, tags, confidence, created_at "
                            "FROM semantic ORDER BY confidence DESC"
                        ).fetchall()
                        for sr in sem_rows:
                            out.insert(0, {
                                "id": f"sem:{sr[0]}",
                                "ts": sr[4] or 0,
                                "timestamp": sr[4] or 0,
                                "text": sr[1] or "",
                                "tags": sr[2] or "semantic,user_fact",
                                "weight": float(sr[3] or 1.0) + 0.5,
                                "kind": "semantic",
                                "source": "semantic",
                            })
                except Exception:
                    pass
            # --- Knowledge Graph enrichment ---
            # Skipped when keyword_only=True — the orchestrator runs its own
            # kg_search() step and manages KG insertion into hybrid_merge()
            # with dedicated priority ordering. Injecting here would add a KG
            # hit in both the keyword bucket AND the kg bucket, causing the
            # orchestrator's dedup (text[:240]) to silently drop one copy.
            if not keyword_only:
                try:
                    from eli.memory.knowledge_graph import get_knowledge_graph
                    _kg = get_knowledge_graph()
                    _kg_ctx = _kg.context_for_prompt(q, max_chars=600)
                    if _kg_ctx:
                        out.insert(0, {
                            "id": "kg:context",
                            "ts": 0,
                            "timestamp": 0,
                            "text": _kg_ctx,
                            "tags": "knowledge_graph,entities,relations",
                            "weight": 2.0,
                            "kind": "knowledge_graph",
                            "source": "knowledge_graph",
                            "_source": "kg",
                        })
                except Exception:
                    pass
            # --- Deep history fallback: search conversation_turns when memories sparse ---
            # This surfaces things the user said that were never extracted as facts.
            if len(out) < 2 and _has_table(conn, "conversation_turns"):
                try:
                    _conv_like = f"%{q.lower()}%"
                    _conv_rows = conn.execute(
                        """SELECT COALESCE(timestamp, ts, 0), role, content
                           FROM conversation_turns
                           WHERE LOWER(content) LIKE ?
                           AND role = 'user'
                           ORDER BY COALESCE(timestamp, ts, 0) DESC
                           LIMIT ?""",
                        (_conv_like, max(3, limit - len(out))),
                    ).fetchall()
                    for _cr in _conv_rows:
                        _txt = (_cr[2] or "").strip()
                        _key = _txt[:160].lower()
                        if _key and _key not in _seen_filtered and len(_txt) >= 10:
                            _seen_filtered.add(_key)
                            out.append({
                                "id": f"conv_turn:{_cr[0]}",
                                "ts": float(_cr[0] or 0),
                                "timestamp": float(_cr[0] or 0),
                                "text": _txt,
                                "tags": "conversation,user",
                                "weight": 0.6,
                                "importance": 0.35,
                                "_source": "conversation_turns",
                            })
                except Exception:
                    pass

            # --- Recall frequency learning: boost importance of top recalled memories ---
            # Queued and flushed in background to keep the read path write-free.
            try:
                _boost_ids = [
                    int(_h["id"]) for _h in out[:3]
                    if not str(_h.get("id", "")).startswith(("kg:", "sem:", "conv"))
                    and _h.get("id") is not None
                ]
                for _bid in _boost_ids:
                    _bid_cap = _bid  # capture for closure
                    _enqueue_recall_write(
                        self.db_path,
                        lambda c, bid=_bid_cap: c.execute(
                            "UPDATE memories SET importance = MIN(1.0, COALESCE(importance, 0.5) + 0.02) WHERE id = ?",
                            (bid,),
                        ),
                    )
            except Exception:
                pass

            try:
                _now = _now_ts()
                _q_cap = q
                _cnt = len(out)
                _enqueue_recall_write(
                    self.db_path,
                    lambda c, ts=_now, query=_q_cap, cnt=_cnt: _insert_payload(
                        c, "recall_log",
                        {"ts": ts, "timestamp": ts, "query": query,
                         "results_count": cnt, "result_count": cnt},
                    ),
                )
            except Exception:
                pass
            # Enforce the caller's limit on the final merged list.
            # conversation_turns fallback uses max(3, limit-len) which can push
            # total above `limit` when the initial result set is small.
            return out[:limit]
        finally:
            conn.close()

    def search_memory(self, query, limit=10, include_conversations=True, user_id=None):
        _q_lower = query.lower() if query else ""
        _q_lower = str(query or "").lower()
        out = list(self.recall_memory(query, limit=limit))
        if include_conversations and len(out) < int(limit):
            try:
                conv_hits = self.search_conversations(query, user_id=user_id, limit=max(1, int(limit) - len(out)))
            except Exception:
                conv_hits = []
            for row in conv_hits:
                out.append({
                    "id": f"conv:{row.get('session_id','')}:{row.get('timestamp','')}",
                    "ts": row.get("timestamp") or 0,
                    "timestamp": row.get("timestamp") or 0,
                    "text": row.get("content") or "",
                    "tags": "conversation",
                    "weight": 0.5,
                    "kind": "conversation",
                    "role": row.get("role") or "",
                    "source": "conversations",
                    "session_id": row.get("session_id") or "",
                    "user_id": row.get("user_id") or "",
                })
        # ---- Lexical filter + dedup -----------------------------------------
        # Drops vector hits with no token overlap to the query unless the
        # query looks like an identity question, then dedups by (id, text[:500]).
        # Also filters ALL sources when the query is a pure social greeting /
        # generic phrase (no meaningful content terms) to prevent low-relevance
        # hits from being injected and causing hallucinated memory claims.
        _q_lower = str(query or "").lower()
        _q_terms = set(re.findall(r"[a-z0-9]+", _q_lower))

        # Stopwords that carry no content signal for memory matching.
        _STOPWORDS = {
            "i", "me", "my", "you", "your", "we", "it", "the", "a", "an",
            "is", "are", "was", "were", "be", "been", "am",
            "and", "or", "but", "not", "in", "on", "at", "to", "for",
            "of", "with", "by", "as", "do", "does", "did", "have", "has",
            "had", "will", "would", "could", "should", "can", "may", "might",
            "that", "this", "there", "here", "what", "when", "where", "which",
            "who", "how", "why", "so", "if", "then", "than", "very", "just",
            "up", "down", "out", "about", "now", "today", "pal", "hey",
        }
        _content_terms = _q_terms - _STOPWORDS
        # A query is "social/generic" when it has no content terms at all
        # (pure greetings, chitchat, filler phrases like "how are you today").
        _is_social_query = len(_content_terms) == 0

        def _hardening_text_of(hit):
            if not isinstance(hit, dict):
                return ""
            return str(hit.get("text") or hit.get("fact") or hit.get("value") or "").strip()

        def _hardening_source_of(hit):
            if not isinstance(hit, dict):
                return ""
            return str(hit.get("_source") or hit.get("source") or "").strip().lower()

        def _hardening_looks_identity_query(s):
            return any(p in s for p in (
                "who am i",
                "about me",
                "what do you know about me",
                "user info",
                "profile",
                "memory about me",
            ))

        _filtered = []
        for _hit in out:
            _txt = _hardening_text_of(_hit)
            _src = _hardening_source_of(_hit)
            if not _txt:
                continue
            if _src == "vector":
                _hit_terms = set(re.findall(r"[a-z0-9]+", _txt.lower()))
                _overlap = len(_q_terms & _hit_terms)
                if not _q_terms:
                    continue
                if _overlap == 0 and not _hardening_looks_identity_query(_q_lower):
                    continue
                if _overlap == 0 and len(_q_terms) >= 2:
                    continue
            elif _is_social_query and not _hardening_looks_identity_query(_q_lower):
                # For social/generic queries, drop ALL non-identity hits from
                # every source (fts, like, conversation_turns, kg) — they have
                # no meaningful content overlap and risk hallucinated claims.
                continue
            _filtered.append(_hit)

        _dedup = []
        _seen_keys = set()
        for _hit in _filtered:
            _k_txt = _hardening_text_of(_hit).lower()
            _k_id = str(_hit.get("id", "")) if isinstance(_hit, dict) else ""
            _key = (_k_id, _k_txt[:500])
            if _key in _seen_keys:
                continue
            _seen_keys.add(_key)
            _dedup.append(_hit)

        return _dedup[: int(limit)]

    def search_memories(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.search_memory(query, limit=limit)

    def apply_weight_decay(
        self,
        decay_factor: float = 0.98,
        min_weight: float = 0.05,
        older_than_days: int = 7,
    ) -> int:
        """
        Blueprint Stage Post-Response: Weight Decay.
        Reduce weight on memories older than `older_than_days` by `decay_factor`.
        Entries below `min_weight` are set to min_weight (not deleted).
        Returns number of rows updated.
        """
        cutoff_ts = time.time() - (older_than_days * 86400)
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE memories
                SET weight = MAX(?, COALESCE(weight, 1.0) * ?)
                WHERE COALESCE(timestamp, ts, 0) < ?
                AND COALESCE(importance, 0.5) < 0.85
                """,
                (min_weight, decay_factor, cutoff_ts),
            )
            updated = conn.execute("SELECT changes()").fetchone()[0]
            conn.commit()
            return int(updated or 0)
        except Exception as e:
            log.debug(f"[MEMORY] weight_decay failed: {e}")
            return 0
        finally:
            conn.close()

    # -----------------------------------------------------------------
    # Conversation storage / retrieval
    # -----------------------------------------------------------------

    def add_conversation_turn(
        self,
        role: str,
        content: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Add a conversation turn to the configured DB and any explicit secondaries."""
        # Persistence gate is part of the normal write path.
        if callable(_eli_should_store_conversation_turn):
            if not _eli_should_store_conversation_turn(str(role or ""), content):
                return None

        session_id = session_id or "default-session"
        user_id = user_id or "default-user"
        now = time.time()

        # Dedup flag: set to True by _write_to_conn when it finds the turn was
        # already stored within the last 10 seconds. Gates ALL downstream writes
        # (log_learning_event, record_event, profile_extractor) so that a second
        # concurrent call for the same message produces zero extra rows anywhere.
        _was_deduped = [False]

        # Helper to write to a single connection
        def _write_to_conn(conn):
            ccols = _memory_table_columns(conn, "conversations")
            row = conn.execute(
                "SELECT id FROM conversations WHERE session_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                (session_id, user_id),
            ).fetchone()
            if row:
                updates = []
                params = []
                for name, value in [
                    ("updated_at", now), ("timestamp", now), ("ts", now),
                    ("role", role), ("content", content)
                ]:
                    if name in ccols:
                        updates.append(f"{name} = ?")
                        params.append(value)
                if updates:
                    params.append(int(row[0]))
                    conn.execute(f"UPDATE conversations SET {', '.join(updates)} WHERE id = ?", params)
            else:
                payload = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "role": role,
                    "content": content,
                    "timestamp": now,
                    "ts": now,
                    "created_at": now,
                    "updated_at": now,
                    "title": session_id,
                }
                _insert_payload(conn, "conversations", payload)

            # Dedup guard: skip insert if identical (session, role, content) was
            # stored within the last 10 seconds. Prevents double-writes from
            # re-entrant paths (proactive daemon, secondary mirror, etc.).
            existing = conn.execute(
                "SELECT id FROM conversation_turns "
                "WHERE session_id = ? AND role = ? AND content = ? "
                "AND COALESCE(ts, timestamp, 0) >= ? "
                "LIMIT 1",
                (session_id, role, content, now - 10.0),
            ).fetchone()
            if existing:
                _was_deduped[0] = True
                return existing[0]

            payload = {
                "session_id": session_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "timestamp": now,
                "ts": now,
            }
            rid = _insert_payload(conn, "conversation_turns", payload)
            return rid

        # Primary
        conn_primary = self._get_connection()
        try:
            rid = _write_to_conn(conn_primary)
            conn_primary.commit()
        finally:
            conn_primary.close()

        # If the primary write was deduped, skip all downstream writes.
        # A second concurrent call for the same turn has already been handled.
        if _was_deduped[0]:
            return rid

        # Secondaries
        for sec_path in self.secondary_paths:
            try:
                sec_conn = sqlite3.connect(sec_path)
                sec_conn.execute("PRAGMA journal_mode=WAL;")
                sec_conn.execute("PRAGMA synchronous=NORMAL;")
                _ensure_memory_schema(sec_conn)
                _write_to_conn(sec_conn)
                sec_conn.commit()
                sec_conn.close()
            except Exception as e:
                log.debug(f"[MEMORY] Failed to add conversation turn to secondary {sec_path}: {e}")

        # World-model sync is part of the normal write path.
        _eli_sync_world_model_from_memory(self, kind="conversation_turn",
                                          role=str(role or ""), text=content,
                                          tags=None)

        try:
            self.log_learning_event(
                "conversation_turn",
                input_text=content if str(role or "").lower() == "user" else "",
                output_text=content if str(role or "").lower() == "assistant" else "",
                action="CHAT",
                outcome=str(role or ""),
                metadata={
                    "session_id": session_id,
                    "user_id": user_id,
                    "role": role,
                    "row_id": rid,
                },
                timestamp=now,
            )
        except Exception:
            pass

        try:
            from eli.runtime.diagnostic_patterns import (
                is_user_challenge as _eli_is_user_challenge,
                should_exclude_turn_from_prompt as _eli_exclude_turn,
            )
            from eli.runtime.evidence_ledger import record_event as _eli_record_event

            role_l = str(role or "").lower()
            content_s = str(content or "")
            event_type = "user_challenge" if role_l == "user" and _eli_is_user_challenge(content_s) else "conversation_turn"
            _eli_record_event(
                event_type,
                source="memory.add_conversation_turn",
                action="CHAT",
                subject=role_l,
                content=content_s,
                payload={
                    "session_id": session_id,
                    "user_id": user_id,
                    "role": role,
                    "row_id": rid,
                    "excluded_from_prompt": _eli_exclude_turn(role_l, content_s),
                },
                outcome=role_l,
                reusable=not _eli_exclude_turn(role_l, content_s),
                session_id=str(session_id or ""),
                user_id=str(user_id or ""),
                db_path=self.db_path,
                timestamp=now,
            )
            if event_type == "user_challenge":
                self.log_habit_event(
                    "user_challenge",
                    {
                        "action": "CHAT",
                        "content": content_s[:500],
                        "session_id": session_id,
                        "user_id": user_id,
                        "source": "memory.add_conversation_turn",
                    },
                )
        except Exception:
            pass

        if str(role or "").lower() == "user":
            try:
                from eli.runtime.profile_extractor import write_patterns_from_turn
                write_patterns_from_turn(content, db_path=self.db_path, ts_value=now)
            except Exception as e:
                log.debug(f"[MEMORY] profile extraction failed: {e}")

        return rid

    def store_conversation(self, session_id, role, content, user_id=None):
        return self.add_conversation_turn(
            role=role,
            content=content,
            session_id=session_id,
            user_id=user_id,
        )

    def get_conversation_history(self, session_id, limit=100):
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT COALESCE(timestamp, ts, 0), session_id, user_id, role, content
                FROM conversation_turns
                WHERE session_id = ?
                ORDER BY COALESCE(timestamp, ts, 0) ASC
                LIMIT ?
                """,
                (session_id, int(limit)),
            ).fetchall()

            if not rows:
                ccols = set(_memory_table_columns(conn, "conversations"))
                if {"session_id", "content"} <= ccols:
                    role_expr = "role" if "role" in ccols else "'assistant'"
                    user_expr = "user_id" if "user_id" in ccols else "''"
                    time_expr = "COALESCE(timestamp, updated_at, created_at, ts, id)"
                    rows = conn.execute(
                        f"""
                        SELECT {time_expr}, session_id, {user_expr}, {role_expr}, content
                        FROM conversations
                        WHERE session_id = ?
                        ORDER BY {time_expr} ASC
                        LIMIT ?
                        """,
                        (session_id, int(limit)),
                    ).fetchall()

            return [
                {
                    "timestamp": r[0],
                    "session_id": r[1],
                    "user_id": r[2],
                    "role": r[3],
                    "content": r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def adjust_weight(self, memory_id: int, delta: float) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE memories SET weight = COALESCE(weight, 1.0) + ? WHERE id = ?",
                (float(delta), int(memory_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_turns_since(
        self,
        seconds: int = 900,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        cutoff = time.time() - max(1, int(seconds))
        conn = self._get_connection()
        try:
            q = "SELECT role, content, timestamp, user_id, session_id FROM conversations WHERE COALESCE(timestamp, ts, 0) >= ?"
            params: List[Any] = [cutoff]
            if user_id:
                q += " AND user_id = ?"
                params.append(user_id)
            if session_id:
                q += " AND session_id = ?"
                params.append(session_id)
            q += " ORDER BY COALESCE(timestamp, ts, 0) DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(q, params).fetchall()
            return [
                {"role": r[0], "content": r[1], "timestamp": r[2], "user_id": r[3], "session_id": r[4]}
                for r in rows
            ]
        finally:
            conn.close()

    def get_session_summaries(self, user_id=None, limit=20):
        conn = self._get_connection()
        try:
            cols = _memory_table_columns(conn, "session_summaries")
            has_user = "user_id" in cols
            order_col = "timestamp" if "timestamp" in cols else ("ended_at" if "ended_at" in cols else "id")
            sql = "SELECT session_id"
            sql += ", user_id" if has_user else ", '' AS user_id"
            sql += ", summary, turns_count, started_at, ended_at, source"
            sql += f" FROM session_summaries"
            params = []
            if user_id and has_user:
                sql += " WHERE user_id = ?"
                params.append(user_id)
            sql += f" ORDER BY COALESCE({order_col}, id) DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "session_id": r[0],
                    "user_id": r[1],
                    "summary": r[2],
                    "turns_count": r[3],
                    "started_at": r[4],
                    "ended_at": r[5],
                    "source": r[6],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def search_conversations(self, query, user_id=None, limit=10):
        q = str(query or "").strip()
        if not q:
            return []
        like = f"%{q.lower()}%"
        conn = self._get_connection()
        try:
            sql = (
                "SELECT timestamp, session_id, user_id, role, content, ts FROM conversation_turns "
                "WHERE LOWER(COALESCE(content, '')) LIKE ?"
            )
            params = [like]
            if user_id:
                sql += " AND user_id = ?"
                params.append(user_id)
            sql += " ORDER BY COALESCE(timestamp, ts, 0) DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "timestamp": r[0] or r[5] or 0,
                    "session_id": r[1],
                    "user_id": r[2],
                    "role": r[3],
                    "content": r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_turns_for_day(self, day: str, user_id: Optional[str] = None, limit: int = 40) -> List[Dict[str, Any]]:
        qday = (day or "").strip()
        if not qday:
            return []
        try:
            start_struct = time.strptime(qday + " 00:00:00", "%Y-%m-%d %H:%M:%S")
            end_struct = time.strptime(qday + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            start_ts = time.mktime(start_struct)
            end_ts = time.mktime(end_struct)
        except Exception:
            return []
        conn = self._get_connection()
        try:
            sql = "SELECT role, content, timestamp, user_id, session_id FROM conversations WHERE COALESCE(timestamp, ts, 0) BETWEEN ? AND ?"
            params: List[Any] = [start_ts, end_ts]
            if user_id:
                sql += " AND user_id = ?"
                params.append(user_id)
            sql += " ORDER BY COALESCE(timestamp, ts, 0) ASC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            return [{"role": r[0], "content": r[1], "timestamp": r[2], "user_id": r[3], "session_id": r[4]} for r in rows]
        finally:
            conn.close()

    # -----------------------------------------------------------------
    # Recent memories and statistics (added for GUI)
    # -----------------------------------------------------------------

    def get_recent_memories(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent memory entries, ordered by timestamp descending."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT id, ts, timestamp, kind, text, tags, source, confidence, weight "
                "FROM memories ORDER BY COALESCE(timestamp, ts, id) DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            out = []
            for row in rows:
                out.append({
                    "id": row[0],
                    "ts": row[1] or row[2] or 0,
                    "timestamp": row[2] or row[1] or 0,
                    "kind": row[3] or "note",
                    "text": row[4] or "",
                    "tags": row[5] or "",
                    "source": row[6] or "",
                    "confidence": row[7] or 1.0,
                    "weight": row[8] or 1.0,
                })
            return out
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Return memory statistics: total count and counts by kind."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] or 0
            by_kind_rows = conn.execute(
                "SELECT kind, COUNT(*) FROM memories GROUP BY kind"
            ).fetchall()
            by_kind = {row[0] or "note": row[1] for row in by_kind_rows}
            return {"total": total, "by_kind": by_kind}
        finally:
            conn.close()

    # -----------------------------------------------------------------
    # Habits
    # -----------------------------------------------------------------

    def log_habit_event(self, event_type, details):
        now = _now_ts()
        details_blob = _jsonify_value(details)
        conn = self._get_connection()
        try:
            rid = _insert_payload(conn, "habit_events", {
                "event_type": _norm_text(event_type),
                "event": _norm_text(event_type),
                "details": details_blob,
                "data": details_blob,
                "timestamp": now,
                "ts": now,
                "name": _norm_text(event_type),
                "command": _norm_text(event_type),
            })

            key_name = _norm_text(event_type)
            key_cmd = key_name
            if isinstance(details, dict):
                key_name = _norm_text(
                    details.get("app")
                    or details.get("name")
                    or details.get("action")
                    or event_type
                )
                key_cmd = _norm_text(
                    details.get("cmd")
                    or details.get("command")
                    or details.get("action")
                    or details.get("app")
                    or key_name
                )

            row = conn.execute(
                "SELECT id, COALESCE(count, 0) FROM habits WHERE COALESCE(name,'') = ?",
                (key_name,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE habits SET count = ?, timestamp = ?, ts = ?, command = COALESCE(command, ?), enabled = 1 WHERE id = ?",
                    (int(row[1] or 0) + 1, now, now, key_cmd, int(row[0])),
                )
            else:
                _insert_payload(conn, "habits", {
                    "name": key_name,
                    "cmd": key_cmd,
                    "method": "auto",
                    "count": 1,
                    "timestamp": now,
                    "ts": now,
                    "command": key_cmd,
                    "enabled": 1,
                })

            rr = conn.execute(
                "SELECT id FROM habit_rules WHERE COALESCE(name,'') = ?",
                (key_name,),
            ).fetchone()
            if rr is None:
                _insert_payload(conn, "habit_rules", {
                    "name": key_name,
                    "command": key_cmd,
                    "enabled": 1,
                    "timestamp": now,
                    "ts": now,
                    "pattern": key_name,
                    "action": key_cmd,
                    "trigger_phrase": key_name,
                    "action_type": "auto",
                })

            conn.commit()
            return rid
        finally:
            conn.close()

    def get_habit_events(self, event_type=None, days=14):
        out = _get_habit_events_window(self, event_type=event_type, days=days)
        if out:
            return out

        conn = self._get_connection()
        try:
            if _has_table(conn, "user_patterns"):
                window = _profile_now_ts() - float(days) * 86400.0
                rows = conn.execute(
                    """
                    SELECT id, pattern_data, COALESCE(timestamp, ts, 0)
                    FROM user_patterns
                    WHERE pattern_type = 'app_cmd' AND COALESCE(timestamp, ts, 0) >= ?
                    ORDER BY COALESCE(timestamp, ts, 0) ASC
                    """,
                    (window,),
                ).fetchall()
                derived = []
                for rid, pdata, ts in rows:
                    parsed = pdata
                    if isinstance(pdata, str):
                        try:
                            parsed = json.loads(pdata)
                        except Exception:
                            parsed = pdata
                    derived.append({
                        "id": rid,
                        "event_type": "app_cmd",
                        "details": parsed,
                        "data": parsed,
                        "timestamp": ts,
                    })
                return derived
            return []
        finally:
            conn.close()

    def add_habit_rule(self, name: str, command: str, hour: int, minute: int, days: list = None) -> int:
        now = time.time()
        days_json = json.dumps(days) if days else None
        conn = self._get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO habit_rules (name, command, hour, minute, days, enabled, timestamp, ts) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (name, command, int(hour), int(minute), days_json, now, now),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    # ... (remaining methods unchanged) ...

    # Note: The rest of the class (get_dashboard_counts, get_recent_improvements, etc.)
    # are unchanged from the original. They are omitted here for brevity but must be kept.
    # The full file should include them as in the original.



    def _eli_habit_rows_to_dicts(self, rows):
        out = []
        for r in rows or []:
            try:
                out.append(dict(r))
                continue
            except Exception:
                pass
            try:
                out.append({k: r[k] for k in r.keys()})
                continue
            except Exception:
                pass
            out.append(r)
        return out

    def _eli_habit_table_exists(self, conn, table_name):
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            return bool(row)
        except Exception:
            return False

    def _eli_habit_columns(self, conn, table_name):
        try:
            t = _validate_identifier(table_name, "table")
            rows = conn.execute(f"PRAGMA table_info({t})").fetchall()
            cols = []
            for r in rows:
                try:
                    cols.append(r["name"])
                except Exception:
                    try:
                        cols.append(r[1])
                    except Exception:
                        pass
            return cols
        except Exception:
            return []

    def _eli_habit_count(self, conn, table_name):
        try:
            row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
            if row is None:
                return 0
            try:
                return int(row[0])
            except Exception:
                try:
                    return int(list(row)[0])
                except Exception:
                    return 0
        except Exception:
            return 0

    def _eli_habit_insert_dynamic(self, conn, table_name, preferred):
        import json as _json
        import time as _time

        cols = self._eli_habit_columns(conn, table_name)
        if not cols:
            return False

        now = float(_time.time())
        row = {}

        preferred = preferred or {}
        for key, value in preferred.items():
            if key in cols and value is not None:
                if isinstance(value, (dict, list, tuple)):
                    try:
                        value = _json.dumps(value, ensure_ascii=False)
                    except Exception:
                        value = str(value)
                row[key] = value

        for key in ("created_at", "updated_at", "timestamp", "ts", "last_seen", "first_seen"):
            if key in cols and key not in row:
                row[key] = now

        defaults = {
            "confidence": 0.65,
            "score": 0.65,
            "weight": 1.0,
            "count": 1,
            "occurrences": 1,
            "enabled": 1,
            "active": 1,
        }
        for key, value in defaults.items():
            if key in cols and key not in row:
                row[key] = value

        if not row:
            return False

        col_sql = ", ".join(f'"{k}"' for k in row.keys())
        q_sql = ", ".join("?" for _ in row.keys())
        conn.execute(
            f'INSERT INTO "{table_name}" ({col_sql}) VALUES ({q_sql})',
            list(row.values()),
        )
        return True

    def _eli_habit_pick_text(self, row_dict):
        if not isinstance(row_dict, dict):
            return ""
        for key in (
            "message", "text", "content", "user_text", "assistant_text",
            "command", "cmd", "app_name", "preference", "value", "summary",
            "event_name", "rule_name", "name", "query", "prompt"
        ):
            v = row_dict.get(key)
            if v:
                s = str(v).strip()
                if s:
                    return s
        for key, value in row_dict.items():
            if isinstance(value, str):
                s = value.strip()
                if s:
                    return s
        return ""

    def _eli_habit_pick_ts(self, row_dict):
        if not isinstance(row_dict, dict):
            return None
        for key in (
            "updated_at", "created_at", "timestamp", "ts", "time",
            "last_seen", "first_seen", "date"
        ):
            v = row_dict.get(key)
            if v is not None:
                return v
        return None

    def _eli_backfill_habit_tables(self, conn):
        import json as _json
        import time as _time

        has_events = self._eli_habit_table_exists(conn, "habit_events")
        has_rules = self._eli_habit_table_exists(conn, "habit_rules")
        if not has_events and not has_rules:
            return

        events_count = self._eli_habit_count(conn, "habit_events") if has_events else 0
        rules_count = self._eli_habit_count(conn, "habit_rules") if has_rules else 0
        if events_count > 0 and rules_count > 0:
            return

        try:
            table_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        except Exception:
            return

        names = []
        for r in table_rows:
            try:
                names.append(r["name"])
            except Exception:
                try:
                    names.append(r[0])
                except Exception:
                    pass

        preferred = [
            "conversation_history",
            "conversations",
            "conversation_turns",
            "app_commands",
            "app_cmds",
            "memories",
            "observations",
            "events",
        ]

        ordered = []
        for t in preferred:
            if t in names:
                ordered.append(t)
        for t in names:
            if t not in ordered and not t.startswith("sqlite_") and t not in ("habit_events", "habit_rules"):
                ordered.append(t)

        src_table = None
        src_row = None

        for table_name in ordered:
            try:
                cnt = self._eli_habit_count(conn, table_name)
                if cnt <= 0:
                    continue
                rows = conn.execute(f'SELECT * FROM "{table_name}" ORDER BY ROWID DESC LIMIT 3').fetchall()
                if not rows:
                    continue
                row0 = rows[0]
                try:
                    row0 = dict(row0)
                except Exception:
                    try:
                        row0 = {k: row0[k] for k in row0.keys()}
                    except Exception:
                        row0 = {}
                src_table = table_name
                src_row = row0
                break
            except Exception:
                continue

        if not src_table:
            return

        text = self._eli_habit_pick_text(src_row)
        ts = self._eli_habit_pick_ts(src_row)
        if ts is None:
            ts = float(_time.time())

        base_name = (text or src_table or "observed_activity").strip()
        if not base_name:
            base_name = "observed_activity"
        base_name = base_name[:160]

        payload = {
            "source_table": src_table,
            "seed_row": src_row,
        }

        if has_events and events_count == 0:
            self._eli_habit_insert_dynamic(
                conn,
                "habit_events",
                {
                    "event_type": "observed_activity",
                    "event_name": base_name,
                    "pattern": base_name,
                    "source": src_table,
                    "details": base_name,
                    "payload": payload,
                    "metadata": payload,
                    "json": payload,
                    "timestamp": ts,
                    "ts": ts,
                    "created_at": ts,
                    "updated_at": ts,
                    "last_seen": ts,
                    "first_seen": ts,
                    "count": 1,
                    "occurrences": 1,
                    "confidence": 0.65,
                },
            )

        if has_rules and rules_count == 0:
            self._eli_habit_insert_dynamic(
                conn,
                "habit_rules",
                {
                    "rule_type": "observed_pattern",
                    "rule_name": f"derived_from_{src_table}",
                    "pattern": base_name,
                    "source": src_table,
                    "details": base_name,
                    "payload": payload,
                    "metadata": payload,
                    "json": payload,
                    "timestamp": ts,
                    "ts": ts,
                    "created_at": ts,
                    "updated_at": ts,
                    "last_seen": ts,
                    "first_seen": ts,
                    "count": 1,
                    "occurrences": 1,
                    "confidence": 0.65,
                    "score": 0.65,
                    "weight": 1.0,
                    "enabled": 1,
                    "active": 1,
                },
            )

        try:
            conn.commit()
        except Exception:
            pass


    def get_habit_rules(self, enabled_only=True):
        conn = self._get_connection()
        try:
            cols = set(_memory_table_columns(conn, "habit_rules"))
            time_expr = "COALESCE(timestamp, ts, id)"
            sql = "SELECT id"
            sql += ", COALESCE(name, '')"
            sql += ", COALESCE(command, action, '')"
            sql += ", COALESCE(hour, 0)"
            sql += ", COALESCE(minute, 0)"
            sql += ", COALESCE(days, '')" if "days" in cols else ", ''"
            sql += ", COALESCE(enabled, 1)"
            sql += f", {time_expr}"
            sql += " FROM habit_rules"
            if enabled_only and "enabled" in cols:
                sql += " WHERE COALESCE(enabled, 1) = 1"
            sql += f" ORDER BY {time_expr} ASC"
            rows = conn.execute(sql).fetchall()

            out = []
            for r in rows:
                days = None
                if r[5]:
                    try:
                        days = json.loads(r[5])
                    except Exception:
                        days = r[5]
                out.append({
                    "id": r[0],
                    "name": r[1],
                    "command": r[2],
                    "hour": r[3],
                    "minute": r[4],
                    "days": days,
                    "enabled": bool(r[6]),
                    "timestamp": r[7],
                })
            return out
        finally:
            conn.close()

    def record_habit_run(self, rule_id: int) -> None:
        self.log_habit_event("habit_run", {"rule_id": int(rule_id)})

    def log_learning_event(
        self,
        event_type: str,
        input_text: str = "",
        output_text: str = "",
        action: str = "",
        outcome: str = "",
        reward: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        """Append one row to the local replay buffer for continual-learning audits."""
        now = float(timestamp or _now_ts())
        payload = {
            "event_type": _norm_text(event_type),
            "input_text": _norm_text(input_text)[:4000],
            "output_text": _norm_text(output_text)[:4000],
            "action": _norm_text(action),
            "outcome": _norm_text(outcome),
            "reward": reward,
            "metadata": _jsonify_value(metadata or {}),
            "timestamp": now,
            "ts": now,
        }
        conn = self._get_connection()
        try:
            rid = _insert_payload(conn, "learning_replay", payload)
            conn.commit()
            try:
                from eli.runtime.evidence_ledger import record_event as _eli_record_event
                _eli_record_event(
                    "learning_replay",
                    source="memory.log_learning_event",
                    action=action,
                    subject=event_type,
                    content=input_text or output_text,
                    payload={
                        "input_text": input_text,
                        "output_text": output_text,
                        "metadata": metadata or {},
                    },
                    outcome=outcome,
                    confidence=None,
                    reusable=True,
                    db_path=self.db_path,
                    timestamp=now,
                )
            except Exception:
                pass
            return int(rid or 0)
        finally:
            conn.close()


    def store_app_cmd(self, name, cmd, method=None):
        now = _profile_now_ts()
        name = _norm_text(name).strip()
        if isinstance(cmd, (list, tuple)):
            cmd_str = " ".join(_norm_text(x).strip() for x in cmd if _norm_text(x).strip())
        else:
            cmd_str = _norm_text(cmd).strip()

        payload_json = _jsonify_profile_value({
            "name": name,
            "cmd": cmd_str,
            "method": method,
        })

        conn = self._get_connection()
        try:
            _ensure_profile_schema(conn)

            cur = conn.execute(
                """
                INSERT INTO user_patterns (pattern_type, pattern_data, timestamp, ts)
                VALUES (?, ?, ?, ?)
                """,
                ("app_cmd", payload_json, now, now),
            )

            row = conn.execute(
                "SELECT id, COALESCE(count, 0) FROM habits WHERE COALESCE(name, '') = ?",
                (name,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE habits
                    SET count = ?, timestamp = ?, ts = ?, command = ?, cmd = ?, method = ?, enabled = 1
                    WHERE id = ?
                    """,
                    (int(row[1] or 0) + 1, now, now, cmd_str, cmd_str, _norm_text(method), int(row[0])),
                )
            else:
                _insert_payload(conn, "habits", {
                    "name": name,
                    "cmd": cmd_str,
                    "method": _norm_text(method),
                    "count": 1,
                    "timestamp": now,
                    "ts": now,
                    "command": cmd_str,
                    "enabled": 1,
                })

            rule = conn.execute(
                "SELECT id FROM habit_rules WHERE COALESCE(name, '') = ?",
                (name,),
            ).fetchone()
            if rule is None:
                _insert_payload(conn, "habit_rules", {
                    "name": name,
                    "command": cmd_str,
                    "enabled": 1,
                    "timestamp": now,
                    "ts": now,
                    "pattern": name,
                    "action": cmd_str,
                    "trigger_phrase": name,
                    "action_type": "app_cmd",
                })

            _insert_payload(conn, "habit_events", {
                "event_type": "app_cmd",
                "event": "app_cmd",
                "details": payload_json,
                "data": payload_json,
                "timestamp": now,
                "ts": now,
                "name": name,
                "command": cmd_str,
                "cmd": cmd_str,
                "method": _norm_text(method),
            })

            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


    def log_failure(self, user_input, error="", confidence=0.0, context=None, details=None, source="manual", **kwargs):
        user_input = str(user_input or "").strip()
        error_text = str(error or kwargs.get("error") or "").strip()
        ctx = context if context is not None else kwargs.get("context")
        ctx_text = _jsonify_contract_value(ctx)
        details_text = _jsonify_contract_value(details if details not in (None, "") else ctx)
        source = str(source or kwargs.get("source") or "manual").strip() or "manual"
        now = _now_ts()
        signature = hashlib.sha1(f"{user_input}|{error_text}".encode("utf-8", "ignore")).hexdigest()

        conn = self._get_connection()
        try:
            _ensure_contract_schema(conn)

            row = conn.execute(
                "SELECT id, COALESCE(occurrence_count, 0) FROM failures WHERE user_input = ? AND error = ?",
                (user_input, error_text),
            ).fetchone()

            if row:
                row_id = int(row[0])
                occ = int(row[1] or 0) + 1
                conn.execute(
                    """
                    UPDATE failures
                    SET timestamp = ?, ts = ?, last_seen = ?, occurrence_count = ?, count = ?,
                        confidence = ?, low_confidence = ?, context = ?, context_json = ?,
                        details = ?, description = ?, source = ?, signature = ?, status = COALESCE(status, 'open')
                    WHERE id = ?
                    """,
                    (
                        now, now, now, occ, occ,
                        float(confidence or 0.0), 1 if float(confidence or 0.0) < 0.5 else 0,
                        ctx_text, ctx_text,
                        details_text, details_text or error_text or user_input,
                        source, signature,
                        row_id,
                    ),
                )
                conn.commit()
                return row_id

            cur = conn.execute(
                """
                INSERT INTO failures (
                    ts, timestamp, user_input, command, error, confidence, low_confidence,
                    context, context_json, occurrence_count, first_seen, last_seen,
                    failure, name, text, content, details, description, source,
                    signature, status, count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now, now, user_input, user_input, error_text, float(confidence or 0.0),
                    1 if float(confidence or 0.0) < 0.5 else 0,
                    ctx_text, ctx_text, 1, now, now,
                    user_input, user_input, details_text or error_text or user_input,
                    details_text or error_text or user_input,
                    details_text, details_text or error_text or user_input,
                    source, signature, "open", 1,
                ),
            )
            conn.commit()
            try:
                from eli.runtime.evidence_ledger import record_event as _eli_record_event
                _eli_record_event(
                    "failure",
                    source=source,
                    action="",
                    subject=user_input,
                    content=error_text,
                    payload={"context": ctx, "details": details, "signature": signature},
                    severity="error",
                    outcome="failed",
                    confidence=float(confidence or 0.0),
                    reusable=True,
                    db_path=self.db_path,
                    timestamp=now,
                )
            except Exception:
                pass
            return int(cur.lastrowid)
        finally:
            conn.close()

    def log_correction(self, original: str, corrected: str):
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO corrections (original, corrected, timestamp, ts) VALUES (?, ?, ?, ?)",
                (original, corrected, now, now),
            )
            conn.commit()
        finally:
            conn.close()


    def add_observation(self, *args, **kwargs):
        if not args and not kwargs:
            raise TypeError("add_observation requires at least one positional argument")

        # Support both positional (category, observation) and kwargs-only
        # (category=, observation=, source=) calling conventions.
        # awareness_boot uses kwargs-only; older call sites use positional.
        first = _norm_text(args[0]).strip() if args else ""
        second = _norm_text(args[1]).strip() if len(args) > 1 else _norm_text(kwargs.pop("observation", "")).strip()

        named_content = kwargs.pop("content", None)
        named_source = kwargs.pop("source", None)
        named_category = kwargs.pop("category", None)

        source = _norm_text(named_source).strip() or first or "runtime"
        category = _norm_text(named_category).strip() or first or "general"
        observation = second
        content_value = _norm_text(named_content).strip() if named_content is not None else (second or "")

        now = _now_ts()
        conn = self._get_connection()
        try:
            payload = {
                "source": source,
                "category": category,
                "observation": observation,
                "content": content_value,
                "text": content_value or observation,
                "details": content_value or observation,
                "timestamp": now,
                "ts": now,
            }
            rid = _insert_payload(conn, "observations", payload)
            conn.commit()
            return rid
        finally:
            conn.close()


    def add_capability_proposal(self, *args, **kwargs):
        capability = kwargs.pop("capability", None)
        proposed_name = kwargs.pop("proposed_name", None)
        description = kwargs.pop("description", "")
        examples = kwargs.pop("examples", None)
        plugin_code = kwargs.pop("plugin_code", kwargs.pop("code", ""))
        status = kwargs.pop("status", "pending")
        reasoning = kwargs.pop("reasoning", "")
        rationale = kwargs.pop("rationale", None)

        if len(args) >= 1:
            if proposed_name is None:
                proposed_name = args[0]
            elif capability is None:
                capability = args[0]
        if len(args) >= 2 and not description:
            description = args[1]
        if len(args) >= 3 and examples is None:
            examples = args[2]
        if len(args) >= 4 and not plugin_code:
            plugin_code = args[3]

        if capability is None:
            capability = proposed_name or ""
        if proposed_name is None:
            proposed_name = capability or ""

        now = _now_ts()
        conn = self._get_connection()
        try:
            payload = {
                "ts": now,
                "timestamp": now,
                "proposed_name": _norm_text(proposed_name),
                "capability": _norm_text(capability),
                "description": _norm_text(description),
                "examples": _examples_json(examples),
                "plugin_code": _norm_text(plugin_code),
                "reasoning": _norm_text(reasoning or rationale or description),
                "rationale": _norm_text(rationale or description or reasoning),
                "status": _norm_text(status or "pending"),
                "created_at": now,
                "updated_at": now,
            }
            rid = _insert_payload(conn, "capability_proposals", payload)
            conn.commit()
            return rid
        finally:
            conn.close()

    def get_dashboard_counts(self):
        conn = self._get_connection()
        try:
            by_kind = {}
            raw_memories = _eli_count_table(conn, "memories")
            processed_memories = 0
            if _eli_table_exists(conn, "memories"):
                rows = conn.execute(
                    """
                    SELECT COALESCE(kind, 'note') AS kind, COUNT(*)
                    FROM memories
                    GROUP BY COALESCE(kind, 'note')
                    ORDER BY COUNT(*) DESC, kind ASC
                    """
                ).fetchall()
                by_kind = {str(r[0] or "note"): int(r[1]) for r in rows}
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM memories
                    WHERE TRIM(COALESCE(text, '')) <> ''
                      AND LOWER(COALESCE(kind, 'note')) <> 'chat'
                    """
                ).fetchone()
                processed_memories = int((row[0] if row else 0) or 0)
            semantic_count = 0
            if _eli_table_exists(conn, "semantic"):
                try: semantic_count = conn.execute("SELECT COUNT(*) FROM semantic").fetchone()[0] or 0
                except Exception: pass

            return {
                "processed_memories": processed_memories + semantic_count,
                "semantic_facts": semantic_count,
                "raw_memories": raw_memories,
                "total_memories": raw_memories,
                "conversation_turns": _eli_count_table(conn, "conversation_turns"),
                "conversations": _eli_count_table(conn, "conversations"),
                "habit_rules": _eli_count_table(conn, "habit_rules"),
                "habit_events": _eli_count_table(conn, "habit_events"),
                "observations": _eli_count_table(conn, "observations"),
                "failures": _eli_count_table(conn, "failures"),
                "improvements": _eli_count_table(conn, "improvements"),
                "session_summaries": _eli_count_table(conn, "session_summaries"),
                "by_kind": by_kind,
                "by_type": by_kind,
                "generated_at": time.time(),
            }
        finally:
            conn.close()

    def get_pending_proposals(self, limit=25, **kwargs):
        limit = int(limit or kwargs.get("n") or 25)
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT id, proposed_name, capability, description, examples, plugin_code, reasoning, status, COALESCE(timestamp, created_at, ts, id) "
                "FROM capability_proposals "
                "WHERE COALESCE(status, 'pending') = 'pending' "
                "ORDER BY COALESCE(timestamp, created_at, ts, id) DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                ex = []
                if r[4]:
                    try:
                        ex = json.loads(r[4])
                    except Exception:
                        ex = [r[4]]
                out.append({
                    "id": r[0],
                    "proposed_name": r[1],
                    "capability": r[2],
                    "description": r[3],
                    "examples": ex,
                    "plugin_code": r[5],
                    "reasoning": r[6],
                    "status": r[7],
                    "timestamp": r[8],
                })
            return out
        finally:
            conn.close()

    def get_recent_conversation(self, limit=20, session_id=None, user_id=None):
        limit = int(limit) if limit else 20
        conn = self._get_connection()
        try:
            # Fetch the most-recent `limit` rows (DESC), then reverse so the
            # caller receives them in chronological (oldest-first) order.
            sql = "SELECT COALESCE(timestamp, ts, 0), session_id, user_id, role, content FROM conversation_turns"
            where = []
            params = []
            if session_id:
                where.append("session_id = ?")
                params.append(session_id)
            if user_id:
                where.append("user_id = ?")
                params.append(user_id)
            # Exclude fragment-guard NOOP entries — they are internal routing
            # events that were stored before the NOOP-suppression fix.
            # Including them in LLM context causes the model to mimic JSON format.
            where.append("content NOT LIKE '%\"event\": \"input_fragment_guard\"%'")
            where.append("content NOT LIKE '%fragmentary_input%'")
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY COALESCE(timestamp, ts, 0) DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            # Reverse to chronological order for the synthesiser
            rows = list(reversed(rows))
            return [
                {
                    "timestamp": r[0],
                    "session_id": r[1],
                    "user_id": r[2],
                    "role": r[3],
                    "content": r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_recent_failures(self, limit=20):
        conn = self._get_connection()
        try:
            if not _eli_table_exists(conn, "failures"):
                return []
            rows = conn.execute(
                """
                SELECT
                    COALESCE(user_input, '') AS user_input,
                    COALESCE(error, '') AS error,
                    COALESCE(command, '') AS command,
                    COALESCE(occurrence_count, 1) AS occurrence_count,
                    COALESCE(timestamp, ts, id) AS sort_ts
                FROM failures
                ORDER BY sort_ts DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [{"user_input": r[0], "error": r[1], "command": r[2], "occurrence_count": r[3], "timestamp": r[4]} for r in rows]
        finally:
            conn.close()

    def get_recent_improvements(self, limit=20):
        conn = self._get_connection()
        try:
            if not _eli_table_exists(conn, "improvements"):
                return []
            rows = conn.execute(
                """
                SELECT
                    COALESCE(category, area, 'runtime') AS category,
                    COALESCE(area, category, 'runtime') AS area,
                    COALESCE(description, suggestion, '') AS description,
                    COALESCE(status, 'pending') AS status,
                    COALESCE(timestamp, created_at, ts, id) AS sort_ts
                FROM improvements
                ORDER BY sort_ts DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [{"category": r[0], "area": r[1], "description": r[2], "status": r[3], "timestamp": r[4]} for r in rows]
        finally:
            conn.close()

    def get_recent_observations(self, limit=20):
        conn = self._get_connection()
        try:
            if not _has_table(conn, "observations"):
                return []
            cols = _memory_table_columns(conn, "observations")
            category_expr = "category" if "category" in cols else ("source" if "source" in cols else "'system'")
            obs_expr = "observation" if "observation" in cols else ("content" if "content" in cols else ("text" if "text" in cols else "''"))
            content_expr = "content" if "content" in cols else ("observation" if "observation" in cols else ("text" if "text" in cols else "''"))
            source_expr = "source" if "source" in cols else "'runtime'"
            time_expr = "COALESCE(timestamp, ts, id)"
            rows = conn.execute(
                f"""
                SELECT {category_expr}, {obs_expr}, {content_expr}, {source_expr}, {time_expr}
                FROM observations
                ORDER BY {time_expr} DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [
                {
                    "category": r[0],
                    "observation": r[1],
                    "content": r[2],
                    "source": r[3],
                    "timestamp": r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_recent_processed_memories(self, limit=20):
        conn = self._get_connection()
        try:
            if not _eli_table_exists(conn, "memories"):
                return []
            rows = conn.execute(
                """
                SELECT
                    id,
                    COALESCE(timestamp, ts, id) AS sort_ts,
                    COALESCE(kind, 'note') AS kind,
                    COALESCE(text, '') AS text,
                    COALESCE(tags, '') AS tags,
                    COALESCE(source, '') AS source
                FROM memories
                ORDER BY sort_ts DESC
                LIMIT ?
                """,
                (max(int(limit) * 6, 120),),
            ).fetchall()
            out = []
            for r in rows:
                text = str(r[3] or "").strip()
                kind = str(r[2] or "note")
                tags = _eli_format_tags(r[4])
                low = text.lower()
                if not text:
                    continue
                if kind.lower() == "chat":
                    continue
                if "conversation" in tags.lower():
                    continue
                if low.startswith("q:") and "\na:" in low:
                    continue
                out.append({
                    "id": r[0],
                    "timestamp": r[1],
                    "kind": kind,
                    "text": text,
                    "tags": tags,
                    "source": str(r[5] or ""),
                })
                if len(out) >= int(limit):
                    break
            return out
        finally:
            conn.close()

    def log_improvement(self, category, description="", area="runtime", priority=1, status="pending", code_before="", code_after="", details=None, **kwargs):
        category = str(category or "").strip()
        description = str(description or "").strip()
        area = str(area or "runtime").strip() or "runtime"
        details_text = _jsonify_contract_value(details) if details not in (None, "") else ""
        body = description or details_text or category or "improvement"
        now = _now_ts()

        conn = self._get_connection()
        try:
            _ensure_contract_schema(conn)

            row = conn.execute(
                "SELECT id FROM improvements WHERE COALESCE(category,'') = ? AND COALESCE(area,'') = ? AND COALESCE(description,'') = ?",
                (category, area, body),
            ).fetchone()

            if row:
                row_id = int(row[0])
                conn.execute(
                    "UPDATE improvements SET timestamp = ?, ts = ?, priority = ?, status = ?, details = ?, "
                    "text = ?, content = ?, improvement = ?, suggestion = ?, source = COALESCE(source, ?) "
                    "WHERE id = ?",
                    (
                        now, now, int(priority or 1), str(status or "pending"), details_text,
                        body, body, body, body, str(kwargs.get("source") or "manual"),
                        row_id,
                    ),
                )
                conn.commit()
                return row_id

            cur = conn.execute(
                """
                INSERT INTO improvements (
                    ts, timestamp, category, area, description, priority, status, created_at,
                    title, name, improvement, text, content, details, source, count, suggestion, applied
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now, now, category, area, body, int(priority or 1), str(status or "pending"), now,
                    category, category, body, body, body, details_text,
                    str(kwargs.get("source") or "manual"), 1, body, 0,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def propose_capability(self, capability, reasoning="", description="", examples=None, plugin_code=""):
        return self.add_capability_proposal(
            proposed_name=capability,
            capability=capability,
            description=description or f"Proposed capability: {capability}",
            examples=examples or [],
            plugin_code=plugin_code or "",
            reasoning=reasoning or "",
            status="pending",
        )

    def save_session_summary(self, session_id, user_id=None, summary="", turns_count=0, started_at=None, ended_at=None, source="gui.autosave"):
        now = _now_ts()
        started_at = now if started_at is None else float(started_at)
        ended_at = now if ended_at is None else float(ended_at)
        conn = self._get_connection()
        try:
            payload = {
                "session_id": session_id,
                "user_id": user_id,
                "summary": summary,
                "turns_count": int(turns_count or 0),
                "started_at": started_at,
                "ended_at": ended_at,
                "source": source,
                "timestamp": now,
                "ts": now,
            }
            rid = _insert_payload(conn, "session_summaries", payload)
            conn.commit()
            return rid
        finally:
            conn.close()

    # ════════════════════════════════════════════════════════════
    # LAYERED MEMORY FACADE
    # ════════════════════════════════════════════════════════════

    def store_episodic(self, role, content, session_id=None, user_id=None):
        """Store a conversation turn (episodic memory)."""
        self.add_conversation_turn(role, content, session_id, user_id)

    def store_semantic(self, fact, tags="", confidence=0.8):
        """Store a user fact/preference."""
        conn = self._get_connection()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS semantic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, fact TEXT, tags TEXT,
                confidence REAL DEFAULT 0.8, created_at REAL)""")
            conn.execute(
                "INSERT INTO semantic (user_id, fact, tags, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
                ("default", fact, tags, confidence, time.time()))
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def recall_semantic(self, query="", limit=10):
        """Recall user facts from semantic table."""
        conn = self._get_connection()
        try:
            if query:
                rows = conn.execute(
                    "SELECT fact, tags, confidence FROM semantic WHERE fact LIKE ? ORDER BY confidence DESC LIMIT ?",
                    (f"%{query}%", limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fact, tags, confidence FROM semantic ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
            return [{"fact": r[0], "tags": r[1], "confidence": r[2]} for r in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def store_reflective(self, category, content, **kwargs):
        """Store failure/improvement/observation."""
        if category == "failure":
            self.log_failure(content, **kwargs)
        elif category == "improvement":
            self.log_improvement(content, **kwargs)
        else:
            self.add_observation(category or "system", content)

    def get_db_routing_info(self):
        """Return which DB this instance uses."""
        try:
            my_path = str(getattr(self, "db_path", ""))
            paths = resolve_db_paths()
            role = "user" if "user" in my_path else "agent" if "agent" in my_path else "unknown"
            return {"db_path": my_path, "role": role,
                    "user_db": str(_path_value(paths, 'user_db')), "agent_db": str(_path_value(paths, 'agent_db')),
                    "memory_db": str(_path_value(paths, 'memory_db')) if _path_value(paths, 'memory_db') else None}
        except Exception as e:
            return {"db_path": str(getattr(self, "db_path", "")), "role": "unknown", "error": str(e)}


# Persistence-gate + world-model-sync helpers.
# Lazily import to keep the module loadable when these are missing.
try:
    from eli.runtime.persistence_gate import (
        should_store_conversation_turn as _eli_should_store_conversation_turn,
        should_store_memory_text as _eli_should_store_memory_text,
    )
except Exception:
    _eli_should_store_conversation_turn = None
    _eli_should_store_memory_text = None

try:
    from eli.kernel.world_model import (
        merge_memory_snapshot as _eli_merge_memory_snapshot,
        append_observation as _eli_append_world_observation,
    )
except Exception:
    _eli_merge_memory_snapshot = None
    _eli_append_world_observation = None


def _eli_sync_world_model_from_memory(mem_obj, *, kind: str, role: str = "", text: str = "", tags=None) -> None:
    """Update world_model.json with a snapshot of the latest persisted record.

    Uses canonical DB path resolution and appends a compact persistence
    observation when memory writes succeed.
    """
    try:
        dbp = str(getattr(mem_obj, "db_path", "") or "")
        paths = resolve_db_paths()
        snap = {
            "user_db": str(getattr(paths, "user_db", "") or ""),
            "agent_db": str(getattr(paths, "agent_db", "") or ""),
            "memory_db": str(getattr(paths, "memory_db", "") or dbp or ""),
            "last_write_db": dbp,
            "last_write_kind": str(kind or ""),
            "last_write_role": str(role or ""),
        }
        if callable(_eli_merge_memory_snapshot):
            _eli_merge_memory_snapshot(snap)
        if callable(_eli_append_world_observation):
            _eli_append_world_observation(
                "persistence",
                {
                    "kind": str(kind or ""),
                    "role": str(role or ""),
                    "db_path": dbp,
                    "size": len(str(text or "")),
                    "tags": list(tags or []) if isinstance(tags, (list, tuple, set)) else ([str(tags)] if tags else []),
                },
            )
    except Exception:
        pass


# Explicit FAISS persistence helper.
# vs.flush() should persist the FAISS index, but historically has been
# unreliable. This helper does an explicit faiss.write_index() to the
# canonical artifacts/vectors/ paths so post-rebuild state always survives
# a restart.
def _eli_persist_loaded_vector_store(rows_for_meta=None):
    """Persist the live VectorStore index/meta to canonical FAISS artifacts.

    Uses canonical vector_store paths instead of constructing repo paths here.
    """
    import pickle

    try:
        import faiss
    except Exception as exc:
        return {"ok": False, "error": f"faiss_import_failed:{exc}", "persisted": False}

    from eli.memory import vector_store as _vs

    index_path_s, meta_path_s = _vs._get_index_paths()
    index_path = Path(index_path_s).resolve()
    meta_path = Path(meta_path_s).resolve()
    index_path.parent.mkdir(parents=True, exist_ok=True)

    store = _vs.get_vector_store()
    if store is None:
        return {"ok": False, "error": "get_vector_store_returned_none",
                "persisted": False, "index_path": str(index_path),
                "meta_path": str(meta_path)}

    def _attr(obj, names):
        for name in names:
            if hasattr(obj, name):
                value = getattr(obj, name)
                if value is not None:
                    return name, value
        return None, None

    index_attr, index_obj = _attr(
        store, ("index", "_index", "faiss_index", "_faiss_index", "idx", "_idx"),
    )
    meta_attr, meta_obj = _attr(
        store, ("metadata", "_metadata", "meta", "_meta", "metas", "_metas",
                "records", "_records", "items", "_items"),
    )

    rows = list(rows_for_meta or [])

    # Case A: VectorStore already has a live FAISS index.
    if index_obj is not None and hasattr(index_obj, "ntotal"):
        ntotal = int(index_obj.ntotal)
        if ntotal <= 0:
            return {"ok": False, "error": "faiss_index_empty", "persisted": False,
                    "index_attr": index_attr, "ntotal": ntotal}

        if not isinstance(meta_obj, (list, tuple)) or len(meta_obj) != ntotal:
            meta_obj = rows[:ntotal]

        faiss.write_index(index_obj, str(index_path))
        with meta_path.open("wb") as f:
            pickle.dump(list(meta_obj), f)

        return {"ok": True, "persisted": True, "method": "write_live_faiss_index",
                "index_attr": index_attr, "meta_attr": meta_attr,
                "ntotal": ntotal,
                "index_path": str(index_path), "meta_path": str(meta_path),
                "index_size": index_path.stat().st_size if index_path.exists() else 0,
                "meta_size": meta_path.stat().st_size if meta_path.exists() else 0}

    # Case B: VectorStore stores vectors as numpy arrays/lists, not FAISS index.
    vec_attr, vectors = _attr(
        store, ("vectors", "_vectors", "embeddings", "_embeddings", "matrix", "_matrix"),
    )

    if vectors is not None:
        try:
            import numpy as np
            arr = np.asarray(vectors, dtype="float32")
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.ndim == 2 and arr.shape[0] > 0 and arr.shape[1] > 0:
                faiss.normalize_L2(arr)
                idx = faiss.IndexFlatIP(int(arr.shape[1]))
                idx.add(arr)
                if not isinstance(meta_obj, (list, tuple)) or len(meta_obj) != int(arr.shape[0]):
                    meta_obj = rows[: int(arr.shape[0])]
                faiss.write_index(idx, str(index_path))
                with meta_path.open("wb") as f:
                    pickle.dump(list(meta_obj), f)
                return {"ok": True, "persisted": True, "method": "build_from_vector_array",
                        "vector_attr": vec_attr,
                        "ntotal": int(idx.ntotal), "dim": int(arr.shape[1]),
                        "index_path": str(index_path), "meta_path": str(meta_path),
                        "index_size": index_path.stat().st_size if index_path.exists() else 0,
                        "meta_size": meta_path.stat().st_size if meta_path.exists() else 0}
        except Exception as exc:
            return {"ok": False, "error": f"vector_array_persist_failed:{exc}",
                    "persisted": False, "vector_attr": vec_attr}

    return {"ok": False, "error": "no_faiss_index_or_vector_array_found",
            "persisted": False, "store_type": str(type(store)),
            "index_path": str(index_path), "meta_path": str(meta_path)}


def rebuild_vector_index_from_search_db() -> Dict[str, Any]:
    """Compatibility helper: rebuild the vector index from the search-authority DB.

    Rebuilds the vector index from the search-authority DB and then persists
    the FAISS files through canonical vector_store paths.
    """
    search_mem = get_search_memory()
    db_path = Path(getattr(search_mem, "db_path", "")).expanduser().resolve()

    from eli.memory.vector_store import get_vector_store, EMBED_DIM
    import faiss
    vs = get_vector_store()
    if vs is None:
        return {"ok": False, "indexed": 0, "db_path": str(db_path), "error": "vector_store_unavailable"}

    conn = search_mem._get_connection()
    try:
        rows = conn.execute(
            "SELECT id, "
            "COALESCE(text, content, value, '') AS text, "
            "COALESCE(kind, 'memory') AS kind, "
            "COALESCE(source, 'memory') AS source, "
            "COALESCE(tags, '') AS tags "
            "FROM memories "
            "WHERE TRIM(COALESCE(text, content, value, '')) <> '' "
            "ORDER BY COALESCE(timestamp, ts, 0) ASC"
        ).fetchall()
    finally:
        conn.close()

    try:
        with vs._lock:
            vs._index = faiss.IndexFlatL2(EMBED_DIM)
            vs._meta = []
            vs._adds_since_save = 0
    except Exception:
        pass

    source_count = 0
    indexed = 0
    skipped = 0
    for row in rows:
        text = (row[1] or "").strip()
        if not text:
            continue
        source_count += 1
        try:
            meta = {
                "memory_id": row[0],
                "kind": row[2],
                "source": row[3],
                "tags": row[4],
            }
            if vs.add(text, metadata=meta):
                indexed += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
            continue

    try:
        vs.flush()
    except Exception:
        pass

    # vs.flush() should persist, but explicit persistence keeps rebuilds
    # durable through canonical artifacts/vectors paths.
    persist = _eli_persist_loaded_vector_store(rows_for_meta=[
        {"id": int(r[0]), "text": (r[1] or "").strip(), "kind": r[2], "source": r[3], "tags": r[4]}
        for r in rows if (r[1] or "").strip()
    ])

    result = {
        "ok": True,
        "source_count": source_count,
        "indexed": indexed,
        "skipped": skipped,
        "db_path": str(db_path),
    }
    if persist.get("ok") and persist.get("persisted"):
        result["faiss_persisted"] = True
        result["faiss_index_path"] = persist.get("index_path")
        result["faiss_meta_path"] = persist.get("meta_path")
        result["faiss_ntotal"] = persist.get("ntotal")
    else:
        result["faiss_persisted"] = False
        result["faiss_persist_error"] = persist.get("error", "unknown")
    return result

# Persistence behavior is implemented directly in Memory.store_memory,
# Memory.add_conversation_turn, and rebuild_vector_index_from_search_db.
