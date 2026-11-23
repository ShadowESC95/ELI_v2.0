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
    resolve_runtime_path,
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


# ── The test session's own sandbox ────────────────────────────────────────

_SANDBOX = Path(__file__).resolve().parents[1] / "artifacts" / "_pytest"


def test_every_store_a_test_can_reach_is_in_the_session_sandbox():
    """Only some stores were moved into the sandbox, one variable at a time: the config folder stayed
    this checkout's own and the data folder its artifacts/ (tests/_state_env.py)."""
    from tests._state_env import outside
    assert outside(_SANDBOX) == {}


def test_a_name_a_test_gives_reaches_the_sandbox_not_the_owners_settings(monkeypatch):
    """A live-engine test said "my name is Sam", and the owner's ELI called them Sam: set_user_name
    mirrored the name into the config folder's settings.json, not the settings file in force, and the
    config folder was this checkout's. The profile it writes is the data folder's (runtime/users)."""
    import json
    from eli.core.runtime_settings import _settings_file
    from eli.kernel import state

    settings = _settings_file()
    assert _SANDBOX in settings.parents
    settings.write_text(json.dumps({"user_name": "Robin"}), encoding="utf-8")
    monkeypatch.setattr(state, "sync_identity_to_world_model", lambda user_id=None: None)
    try:
        state.set_user_name("Sam", user_id="a-test-owner")
        assert json.loads(settings.read_text(encoding="utf-8"))["user_name"] == "Sam"
        assert _SANDBOX in state._profile_path("a-test-owner").parents
    finally:
        settings.unlink(missing_ok=True)
        state._profile_path("a-test-owner").unlink(missing_ok=True)


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

    root = tmp_path / "ELI_v2.0"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='eli-v2.0'\n")

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

    root = tmp_path / "ELI_v2.0"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(root))
    monkeypatch.delenv("ELI_DEV_MODE", raising=False)
    monkeypatch.delenv("ELI_FORCE_DEV_MODE", raising=False)

    assert paths._is_dev_mode() is True


def test_relative_runtime_paths_anchor_to_active_project_root(monkeypatch, tmp_path):
    import eli.core.paths as paths

    root = tmp_path / "ELI_v2-2.0.9-linux-portable"
    cwd = tmp_path / "somewhere_else"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    cwd.mkdir()

    monkeypatch.setenv("ELI_PROJECT_ROOT", str(root))
    monkeypatch.chdir(cwd)

    assert paths.resolve_runtime_path("models") == root / "models"
    assert paths.resolve_runtime_path("artifacts/db/user.sqlite3") == root / "artifacts" / "db" / "user.sqlite3"


def test_models_dir_relative_override_is_not_cwd_based(monkeypatch, tmp_path):
    import eli.core.paths as paths

    root = tmp_path / "ELI_v2-2.0.9-linux-portable"
    cwd = tmp_path / "caller_cwd"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    cwd.mkdir()

    monkeypatch.setenv("ELI_PROJECT_ROOT", str(root))
    monkeypatch.setenv("ELI_MODELS_DIR", "models")
    monkeypatch.chdir(cwd)

    assert paths.models_dir() == root / "models"
    assert paths.models_dir() != cwd / "models"


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


def test_gguf_relative_env_path_anchors_to_project_root(monkeypatch, tmp_path):
    import eli.core.paths as paths

    root = tmp_path / "ELI_v2-2.0.9-linux-portable"
    cwd = tmp_path / "caller_cwd"
    model = root / "models" / "env_model.gguf"
    (root / "eli" / "cognition").mkdir(parents=True)
    (root / "eli" / "gui").mkdir(parents=True)
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fake")
    cwd.mkdir()

    monkeypatch.setenv("ELI_PROJECT_ROOT", str(root))
    monkeypatch.setenv("ELI_GGUF_MODEL_PATH", "models/env_model.gguf")
    monkeypatch.chdir(cwd)

    assert paths.get_gguf_model_path() == str(model)


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


def test_notes_go_to_the_data_folder_and_appending_keeps_every_line(tmp_path, monkeypatch):
    """Notes were written to ./eli_notebook wherever ELI was started from (the code checkout, in a
    benchmark), read whole and written back."""
    from eli.core import paths
    from eli.execution.executor_enhanced import _eli_safe_write_note
    monkeypatch.delenv("ELI_NOTEBOOK_DIR", raising=False)
    monkeypatch.delenv("ELI_NOTES_DIR", raising=False)
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    paths.data_dir.cache_clear()        # resolved (and cached) while the executor was imported
    assert paths.notes_dir() == tmp_path / "data" / "notes"
    first = _eli_safe_write_note({"text": "buy oat milk"})
    _eli_safe_write_note({"text": "call the garage"})
    page = Path(first["path"])
    assert page.parent == tmp_path / "data" / "notes" and not (tmp_path / "eli_notebook").exists()
    lines = [l for l in page.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2 and lines[0].endswith("buy oat milk") and lines[1].endswith("call the garage")


def test_every_note_is_listed_and_searched_wherever_it_was_written(tmp_path, monkeypatch):
    """WRITE_NOTE wrote its lines to the notebook folder and NEW_NOTE / LIST_NOTES / SEARCH_NOTES
    used the notes folder, so "search notes" never found a line written with "note: ...". A daily
    page an older version left in the notebook folder is still found, and a second note with the
    same title no longer replaces the first."""
    from eli.execution.executor_enhanced import execute
    monkeypatch.setenv("ELI_NOTES_DIR", str(tmp_path / "notes"))
    monkeypatch.setenv("ELI_NOTEBOOK_DIR", str(tmp_path / "notebook"))
    (tmp_path / "notebook").mkdir()
    (tmp_path / "notebook" / "2020-01-02.md").write_text("- [09:00:00] water the fern\n", encoding="utf-8")
    execute("WRITE_NOTE", {"text": "renew the bike lock code"})
    execute("NEW_NOTE", {"title": "garden", "content": "plant the tulip bulbs"})
    execute("NEW_NOTE", {"title": "garden", "content": "fix the hose reel"})
    found = execute("SEARCH_NOTES", {"query": "bike lock"})
    assert len(found["hits"]) == 1 and "renew the bike lock code" in found["response"]
    assert len(execute("SEARCH_NOTES", {"query": "fern"})["hits"]) == 1
    listed = execute("LIST_NOTES", {})["notes"]
    assert "2020-01-02.md" in listed and len(listed) == 4
    assert len(execute("SEARCH_NOTES", {"query": "tulip"})["hits"]) == 1
    assert len(execute("SEARCH_NOTES", {"query": "hose reel"})["hits"]) == 1


def test_notes_are_kept_in_the_data_folder_not_where_eli_was_started(tmp_path, monkeypatch):
    """With ELI_NOTES_DIR unset the notes folder was Path(""), the working directory, so listing
    notes in a checkout listed README.md."""
    from eli.core import paths
    from eli.execution.executor_enhanced import execute
    monkeypatch.delenv("ELI_NOTES_DIR", raising=False)
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    paths.data_dir.cache_clear()
    (tmp_path / "README.md").write_text("not a note", encoding="utf-8")
    execute("NEW_NOTE", {"title": "garage", "content": "call the garage on Monday"})
    listed = str(execute("LIST_NOTES", {}))
    assert "README.md" not in listed and (tmp_path / "data" / "notes").is_dir()


def test_a_real_eli_folder_in_home_keeps_its_paths(monkeypatch, tmp_path):
    # ~/eli stood for the program's folder (it used to live there), so on a machine with a real ~/eli
    # folder every path under it was read from the program's folder: fixing or listing ~/eli/work/x.py,
    # or anything in a checkout kept under ~/eli, reached a file that is not there
    from eli.core.paths import canonical_project_root, resolve_user_repo_path
    from eli.execution import executor_enhanced as EX

    home = tmp_path / "home"
    work = home / "eli" / "work"
    work.mkdir(parents=True)
    mine = work / "x.py"
    mine.write_text("print('mine')\n")
    monkeypatch.setenv("HOME", str(home))
    assert resolve_user_repo_path("~/eli/work/x.py") == mine.resolve()
    assert resolve_user_repo_path(str(mine)) == mine.resolve()
    assert resolve_user_repo_path("~/eli/work/new.txt") == (work / "new.txt").resolve()
    listed = EX.execute("LIST_DIR", {"path": "~/eli/work"})
    assert listed.get("ok") is True and listed.get("path") == str(work.resolve())
    assert "x.py" in listed.get("content", "")

    # with no real ~/eli the old alias still reaches the program's folder and its package
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.setenv("HOME", str(bare))
    root = canonical_project_root()
    assert resolve_user_repo_path("~/eli/pyproject.toml") == (root / "pyproject.toml").resolve()
    assert resolve_user_repo_path("~/eli/core") == (root / "eli" / "core").resolve()


@pytest.mark.parametrize("platform,variable,default", [
    ("linux", "XDG_DATA_HOME", (".local", "share")),
    ("win32", "LOCALAPPDATA", ("AppData", "Local")),
])
@pytest.mark.parametrize("value", ["", "   ", "relative/share"])
def test_a_data_home_left_empty_or_relative_is_not_the_folder_eli_starts_in(tmp_path, monkeypatch, platform,
                                                                          variable, default, value):
    """An XDG_DATA_HOME set to nothing is no folder by the XDG rules, but it was read as Path(""), the
    current folder: a new user's whole ELI_v2 root (databases, settings, models) went into whatever
    folder ELI was started from, the packaged app's runtime hook and the launcher pointer with it."""
    import importlib.util
    import sys
    import eli.core.paths as P
    import eli.runtime.desktop_launchers as dl
    home, elsewhere = tmp_path / "home", tmp_path / "started_here"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(dl, "product_line", lambda: "v2")
    own = (home.joinpath(*default) / "ELI_v2").resolve()
    hook_file = Path(P.__file__).resolve().parents[2] / "packaging" / "pyinstaller" / "rthook_eli_frozen_paths.py"
    spec = importlib.util.spec_from_file_location("_rthook_under_test", hook_file)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)          # not frozen here: it only defines its functions
    assert P._frozen_user_root() == own
    assert hook._user_root().resolve() == own
    assert dl.stable_user_root() == own


def test_temp_names_are_each_users_own(monkeypatch):
    """/tmp is one folder for every account on the machine, and a Windows named pipe one namespace. With
    the version alone in the name, a second account's ELI took the first one's speaking lock as its own
    (its microphone muted while the other ELI spoke) and could not write its own lock or player socket."""
    import eli.core.paths as P
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX accounts")
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    first = (P.temp_path("tts_speaking.lock"), P.pipe_path("youtube_mpv"))
    monkeypatch.setattr(os, "getuid", lambda: 1001)
    second = (P.temp_path("tts_speaking.lock"), P.pipe_path("youtube_mpv"))
    assert first[0] != second[0] and first[1] != second[1]
    assert first[0].parent == second[0].parent and first[0].name.startswith("ELI_v2-")
