from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

_STORES = None


def _norm(p):
    try:
        return Path(p).expanduser().resolve()
    except Exception:
        return Path(str(p))


def _stores_match_current_paths(stores) -> bool:
    try:
        from .memory import resolve_db_paths
        paths = resolve_db_paths()
        return (
            hasattr(stores, "user")
            and hasattr(stores, "agent")
            and _norm(stores.user.db_path) == _norm(paths.user_db)
            and _norm(stores.agent.db_path) == _norm(paths.agent_db)
        )
    except Exception:
        return False


def get_stores():
    global _STORES
    from . import get_memory, get_agent_memory

    if _STORES is None or not _stores_match_current_paths(_STORES):
        _STORES = SimpleNamespace(
            user=get_memory(),
            agent=get_agent_memory(),
        )
    return _STORES


__all__ = ["get_stores", "_STORES"]
