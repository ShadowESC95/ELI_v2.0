# eli/memory/sqlite_memory.py
"""
Compatibility wrapper: some old code imports SQLiteMemory from here.
We map it to eli.memory.Memory.
"""

from eli.memory import Memory, get_memory, get_agent_memory, resolve_db_paths, DBPaths  # noqa: F401


# ── Functions added by apply_fixes.py ────────────────────────────────────────

def add_memory(text: str, tags: str = "") -> dict:
    """Store a memory entry; returns {ok, id}."""
    from eli.memory import get_memory
    try:
        mem = get_memory()
        r = mem.store_memory(text, tags=[t.strip() for t in tags.split(",") if t.strip()])
        if isinstance(r, dict):
            return r
        return {"ok": True, "id": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_memory(query: str) -> dict:
    """Search memories; returns {ok, results}."""
    if not query or not query.strip():
        return {"ok": False, "error": "empty query"}
    from eli.memory import get_memory
    try:
        results = get_memory().recall_memory(query)
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def log_event(event_type: str, data=None) -> None:
    """Log a habit/system event."""
    from eli.memory import get_memory
    try:
        get_memory().log_habit_event(event_type, data or {})
    except Exception:
        pass
