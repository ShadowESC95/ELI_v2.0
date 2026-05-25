"""
Database path resolution — delegates to core.paths.
Kept for backward compatibility; import from eli.core.paths directly in new code.
"""
from eli.core.paths import (
    project_root, data_dir, user_db_path, agent_db_path,
    memory_db_path, get_gguf_model_path, set_gguf_model_path,
)

# Backward compat: some modules import DBPaths class
class DBPaths:
    """Legacy compatibility wrapper."""
    
    @staticmethod
    def project_root():
        return project_root()
    
    @staticmethod
    def artifacts_dir():
        return data_dir()
    
    @staticmethod
    def user_db():
        return user_db_path()
    
    @staticmethod
    def agent_db():
        return agent_db_path()
    
    @staticmethod
    def memory_db():
        return memory_db_path()

# Canonical database path implementation:
#   - get_db_paths() returns an _AttrDict (dict subclass with attribute
#     access) so both p.user_db and p["user_db"] work.
#   - Each path is resolved by eli.core.paths, which honors:
#       * ELI_PROJECT_ROOT  (set by bin/elix)
#       * ELI_DATA_DIR      (per-user XDG override)
#       * ELI_DB_DIR        (db-only override)
#       * ELI_USER_DB       (single-file override)
#       * ELI_MEMORY_DB     (legacy single-file override)
#       * ELI_AGENT_DB      (single-file override)
#     ...then falls through to dev-mode (project_root/artifacts/db) or
#     platformdirs (~/.local/share/eli/db on Linux, %LOCALAPPDATA%
#     on Windows, ~/Library/Application Support on macOS) for installed
#     non-dev users.

class _AttrDict(dict):
    """Dict subclass with attribute access, for `paths.user_db` syntax."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(key) from e
    __setattr__ = dict.__setitem__


def get_db_paths(*args, **kwargs):
    """Canonical resolver. Returns _AttrDict with project_root/user_db/agent_db/memory_db."""
    from eli.core.paths import (
        project_root as _project_root,
        user_db_path as _user_db_path,
        agent_db_path as _agent_db_path,
        memory_db_path as _memory_db_path,
        db_dir as _db_dir,
    )
    # Ensure the directory exists (callers may stat the parent before opening).
    try:
        _db_dir().mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return _AttrDict(
        project_root=str(_project_root()),
        user_db=str(_user_db_path()),
        agent_db=str(_agent_db_path()),
        memory_db=str(_memory_db_path()),
    )


def get_user_db_path():
    return get_db_paths().user_db


def get_agent_db_path():
    return get_db_paths().agent_db


def get_memory_db_path():
    return get_db_paths().memory_db


# Module-level cached instance for callers that want eager resolution.
DB_PATHS = get_db_paths()
