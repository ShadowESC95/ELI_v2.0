from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DBPaths:
    user_db: Path
    agent_db: Path


def resolve_db_paths() -> DBPaths:
    try:
        from eli.core.paths import get_paths
        paths = get_paths()
        return DBPaths(user_db=Path(paths.user_db).resolve(), agent_db=Path(paths.agent_db).resolve())
    except Exception:
        here = Path(__file__).resolve()
        artifacts = (here.parent.parent / "artifacts").resolve()
        artifacts.mkdir(parents=True, exist_ok=True)
        return DBPaths(user_db=(artifacts / "user.sqlite3").resolve(), agent_db=(artifacts / "agent.sqlite3").resolve())
