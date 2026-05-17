"""Tests for eli.core.paths — ~120 tests."""
from __future__ import annotations

from pathlib import Path
import os
import pytest

from eli.core.paths import (
    project_root,
    models_dir,
    voices_dir,
    config_dir,
    data_dir,
    cache_dir,
    db_dir,
    logs_dir,
    plugins_dir,
    artifacts_dir,
    conversations_dir,
    proactive_dir,
    documents_dir,
    scripts_dir,
    notes_dir,
    user_db_path,
    agent_db_path,
    memory_db_path,
    knowledge_graph_db_path,
    gguf_models_dir,
    embedding_models_dir,
    models_root,
    training_root,
    get_paths,
    get_gguf_model_path,
    set_gguf_model_path,
    path_info,
    EliPaths,
    PATHS,
    PROJECT_ROOT,
    ARTIFACTS_DIR,
    DB_PATH,
    is_frozen,
    _is_dev_mode,
    _find_project_root,
)


# ── Basic imports and constants ───────────────────────────────────────────

def test_project_root_is_path():
    assert isinstance(project_root(), Path)

def test_project_root_exists():
    assert project_root().exists()

def test_project_root_has_eli_dir():
    assert (project_root() / "eli").is_dir()

def test_project_root_constant_matches_function():
    assert PROJECT_ROOT == project_root()

def test_artifacts_dir_constant_matches_function():
    assert ARTIFACTS_DIR == data_dir()

def test_db_path_constant_is_path():
    assert isinstance(DB_PATH, Path)


# ── Dev mode detection ────────────────────────────────────────────────────

def test_is_not_frozen():
    assert not is_frozen()

def test_find_project_root_returns_path_or_none():
    result = _find_project_root()
    assert result is None or isinstance(result, Path)

def test_dev_mode_detection():
    # In the dev environment, should detect dev mode
    result = _is_dev_mode()
    assert isinstance(result, bool)

def test_installer_like_tree_without_git_is_not_dev_mode(monkeypatch, tmp_path):
    import eli.core.paths as paths

    root = tmp_path / "ELI_MKXI"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='eli-mkxi'\n")

    monkeypatch.delenv("ELI_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("ELI_DEV_MODE", raising=False)
    monkeypatch.delenv("ELI_FORCE_DEV_MODE", raising=False)
    monkeypatch.setattr(paths, "_find_project_root", lambda: root)

    paths.data_dir.cache_clear()
    paths.config_dir.cache_clear()
    paths.cache_dir.cache_clear()
    try:
        assert paths._is_dev_mode() is False
        assert paths.data_dir() != root / "artifacts"
    finally:
        paths.data_dir.cache_clear()
        paths.config_dir.cache_clear()
        paths.cache_dir.cache_clear()

def test_explicit_project_root_keeps_dev_mode(monkeypatch, tmp_path):
    import eli.core.paths as paths

    root = tmp_path / "ELI_MKXI"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(root))
    monkeypatch.delenv("ELI_DEV_MODE", raising=False)
    monkeypatch.delenv("ELI_FORCE_DEV_MODE", raising=False)

    assert paths._is_dev_mode() is True


# ── Directory functions return Paths ─────────────────────────────────────

@pytest.mark.parametrize("fn", [
    project_root, data_dir, config_dir, cache_dir, logs_dir,
    models_dir, voices_dir, plugins_dir, artifacts_dir,
    conversations_dir, proactive_dir, documents_dir,
    scripts_dir, notes_dir, models_root,
    gguf_models_dir, embedding_models_dir, training_root,
])
def test_path_functions_return_path(fn):
    assert isinstance(fn(), Path)


# ── DB path functions ────────────────────────────────────────────────────

def test_user_db_path_is_path():
    assert isinstance(user_db_path(), Path)

def test_agent_db_path_is_path():
    assert isinstance(agent_db_path(), Path)

def test_memory_db_path_is_path():
    assert isinstance(memory_db_path(), Path)

def test_knowledge_graph_db_path_is_path():
    assert isinstance(knowledge_graph_db_path(), Path)

def test_knowledge_graph_db_same_as_memory():
    assert knowledge_graph_db_path() == memory_db_path()

def test_user_db_path_ends_with_sqlite3():
    assert user_db_path().suffix == ".sqlite3"

def test_agent_db_path_ends_with_sqlite3():
    assert agent_db_path().suffix == ".sqlite3"


# ── Env overrides ────────────────────────────────────────────────────────

def test_user_db_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_USER_DB", str(tmp_path / "custom.sqlite3"))
    # Re-import to pick up override (functions are not cached for these env paths)
    from eli.core.paths import user_db_path as _udb
    assert str(tmp_path) in str(_udb())

def test_agent_db_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_AGENT_DB", str(tmp_path / "agent.sqlite3"))
    from eli.core.paths import agent_db_path as _adb
    assert str(tmp_path) in str(_adb())


# ── Models directories ────────────────────────────────────────────────────

def test_gguf_models_dir_inside_models_root():
    assert str(models_root()) in str(gguf_models_dir())

def test_embedding_models_dir_inside_models_root():
    assert str(models_root()) in str(embedding_models_dir())

def test_models_root_inside_project_root():
    assert str(project_root()) in str(models_root())

def test_models_root_matches_models_dir():
    assert models_root() == models_dir()


# ── get_paths / PATHS singleton ───────────────────────────────────────────

def test_get_paths_returns_eli_paths():
    assert isinstance(get_paths(), EliPaths)

def test_paths_singleton_is_eli_paths():
    assert isinstance(PATHS, EliPaths)

def test_paths_project_root_attr():
    p = get_paths()
    assert p.project_root is not None

def test_paths_models_dir_attr():
    p = get_paths()
    assert p.models_dir is not None

def test_paths_config_dir_attr():
    p = get_paths()
    assert p.config_dir is not None

def test_paths_user_db_attr():
    p = get_paths()
    assert p.user_db is not None

def test_paths_agent_db_attr():
    p = get_paths()
    assert p.agent_db is not None

def test_paths_repr():
    p = get_paths()
    r = repr(p)
    assert "EliPaths" in r


# ── GGUF model path ───────────────────────────────────────────────────────

def test_get_gguf_model_path_returns_str_or_none():
    result = get_gguf_model_path()
    assert result is None or isinstance(result, str)

def test_set_gguf_model_path(monkeypatch, tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fake")
    set_gguf_model_path(str(model))
    assert get_gguf_model_path() == str(model)

def test_gguf_env_override(monkeypatch, tmp_path):
    model = tmp_path / "env_model.gguf"
    model.write_bytes(b"fake")
    monkeypatch.setenv("ELI_GGUF_MODEL_PATH", str(model))
    assert get_gguf_model_path() == str(model)


# ── path_info ────────────────────────────────────────────────────────────

def test_path_info_returns_dict():
    info = path_info()
    assert isinstance(info, dict)

def test_path_info_has_project_root():
    info = path_info()
    assert "project_root" in info

def test_path_info_has_is_dev_mode():
    info = path_info()
    assert "is_dev_mode" in info

def test_path_info_has_is_frozen():
    info = path_info()
    assert "is_frozen" in info

@pytest.mark.parametrize("key", [
    "project_root", "data_dir", "config_dir", "cache_dir",
    "db_dir", "logs_dir", "models_dir", "voices_dir",
    "plugins_dir", "user_db", "agent_db",
])
def test_path_info_has_key(key):
    info = path_info()
    assert key in info

def test_path_info_values_are_strings_or_bool():
    info = path_info()
    for k, v in info.items():
        assert isinstance(v, (str, bool)), f"{k}: {v} is {type(v)}"


# ── EliPaths class ────────────────────────────────────────────────────────

def test_eli_paths_all_attrs():
    p = EliPaths()
    attrs = [
        "project_root", "root", "artifacts_dir", "data_dir", "config_dir",
        "cache_dir", "db_dir", "logs_dir", "log_dir", "models_dir",
        "voices_dir", "plugins_dir", "user_db", "agent_db", "memory_db",
        "knowledge_graph_db", "db", "conversations_dir", "proactive_dir",
        "documents_dir", "scripts_dir", "notes_dir", "notebook_dir",
    ]
    for attr in attrs:
        val = getattr(p, attr)
        assert val is not None, f"EliPaths.{attr} is None"

def test_eli_paths_root_alias():
    p = EliPaths()
    assert p.root == p.project_root

def test_eli_paths_db_alias():
    p = EliPaths()
    assert p.db is not None
    assert isinstance(p.db, Path)

def test_eli_paths_log_dir_alias():
    p = EliPaths()
    assert p.log_dir == p.logs_dir
