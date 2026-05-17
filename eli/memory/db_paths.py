from __future__ import annotations

class _AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        self[name] = value

def _normalize_paths(obj):
    if isinstance(obj, _AttrDict):
        data = dict(obj)
    elif isinstance(obj, dict):
        data = dict(obj)
    else:
        data = {}
        for key in (
            "project_root",
            "artifacts_dir",
            "db_dir",
            "user_db",
            "agent_db",
            "memory_db",
            "world_model",
            "runtime_dir",
        ):
            if hasattr(obj, key):
                data[key] = getattr(obj, key)

    if "memory_db" not in data:
        if "user_db" in data:
            data["memory_db"] = data["user_db"]

    if "user_db" not in data and "memory_db" in data:
        data["user_db"] = data["memory_db"]

    return _AttrDict(data)

def get_db_paths(*args, **kwargs):
    try:
        from eli.core.db_paths import get_db_paths as _core_get_db_paths
    except Exception:
        return _AttrDict({})

    try:
        return _normalize_paths(_core_get_db_paths(*args, **kwargs))
    except Exception:
        return _AttrDict({})

DB_PATHS = get_db_paths()

# The top-level get_db_paths delegates to eli.core.db_paths.get_db_paths and
# normalizes the result into an _AttrDict for attribute-style and item-style
# access.
