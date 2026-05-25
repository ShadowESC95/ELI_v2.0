"""
DB path resolution for planning modules.

Delegates entirely to eli.core.db_paths.get_db_paths() so all three modules
(core, memory, planning) return a compatible object with user_db, agent_db,
and memory_db fields — and env-var overrides (ELI_DATA_DIR, ELI_DB_DIR,
ELI_USER_DB, ELI_MEMORY_DB, ELI_AGENT_DB) are all honoured.

The old frozen dataclass (2 fields, no memory_db, hardcoded artifacts/ fallback)
has been removed; callers that type-checked against DBPaths should use
eli.core.db_paths._AttrDict or duck-type on attribute access.
"""
from __future__ import annotations

from pathlib import Path


def resolve_db_paths():
    """Return an _AttrDict with user_db, agent_db, and memory_db as Path strings."""
    try:
        from eli.core.db_paths import get_db_paths
        return get_db_paths()
    except Exception:
        # Last-resort fallback: compute from file location if core is unavailable.
        here = Path(__file__).resolve()
        artifacts = (here.parents[2] / "artifacts").resolve()
        artifacts.mkdir(parents=True, exist_ok=True)
        user_db = str((artifacts / "db" / "user.sqlite3").resolve())
        agent_db = str((artifacts / "db" / "agent.sqlite3").resolve())
        from types import SimpleNamespace
        ns = SimpleNamespace(user_db=user_db, agent_db=agent_db, memory_db=user_db)
        return ns


# Module-level cached instance.
DB_PATHS = resolve_db_paths()
