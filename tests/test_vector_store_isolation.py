"""The FAISS index must honour the artifacts overrides like every other store.

`_get_index_paths()` hardcoded `_project_root()/artifacts/vectors`, which meant:

* an **installed** build kept writing inside the installation even though
  `_is_dev_mode()` is False when frozen and every other store resolves to the
  platform data dir — on an AppImage that directory is a read-only mount;
* **redirection was ignored**, so a run that had pointed every database at a
  throwaway tree still wrote vectors into the user's real semantic memory. Caught
  live: a test session appended five auto-reflections about itself to the real index
  (292 -> 297). The suite only escaped the same fate because faiss is absent here,
  which is luck, not isolation.

Dev-tree behaviour must stay byte-identical: artifacts_dir() IS
<project_root>/artifacts in dev mode.
"""
import importlib
import os
from pathlib import Path

import pytest

from eli.core.paths import project_root


def _paths(monkeypatch, **env):
    for k in ("ELI_ARTIFACTS_DIR", "ELI_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import eli.memory.vector_store as vs
    importlib.reload(vs)
    return Path(vs._get_index_paths()[0])


def test_artifacts_dir_override_is_honoured(tmp_path, monkeypatch):
    p = _paths(monkeypatch, ELI_ARTIFACTS_DIR=str(tmp_path))
    assert tmp_path in p.parents, f"index escaped the override: {p}"


def test_data_dir_override_is_honoured(tmp_path, monkeypatch):
    p = _paths(monkeypatch, ELI_DATA_DIR=str(tmp_path))
    assert tmp_path in p.parents


def test_artifacts_dir_wins_over_data_dir(tmp_path, monkeypatch):
    a = tmp_path / "a"; d = tmp_path / "d"
    p = _paths(monkeypatch, ELI_ARTIFACTS_DIR=str(a), ELI_DATA_DIR=str(d))
    assert a in p.parents and d not in p.parents


def test_dev_tree_default_is_unchanged(monkeypatch):
    """The whole point of using artifacts_dir(): a source checkout must land in
    exactly the directory it always did, so nobody's index moves."""
    p = _paths(monkeypatch)
    assert p == (project_root() / "artifacts" / "vectors" / "index.faiss").resolve()


def test_the_hardcoded_project_path_is_gone():
    import inspect
    import eli.memory.vector_store as vs
    src = inspect.getsource(vs._get_index_paths)
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("*", "#")))
    assert "ELI_ARTIFACTS_DIR" in body and "artifacts_dir" in body


def test_migration_does_not_clobber_an_existing_index(tmp_path, monkeypatch):
    """Copying a legacy index into a location that already has one would destroy
    live data — the guard is 'only when the target has none'."""
    vdir = tmp_path / "vectors"; vdir.mkdir(parents=True)
    sentinel = vdir / "index.faiss"
    sentinel.write_bytes(b"DO-NOT-CLOBBER")
    _paths(monkeypatch, ELI_ARTIFACTS_DIR=str(tmp_path))
    assert sentinel.read_bytes() == b"DO-NOT-CLOBBER"


def test_paths_never_raise_when_the_target_is_unwritable(tmp_path, monkeypatch):
    """A read-only target must degrade to the user data dir, not take VectorStore
    construction down with it."""
    blocked = tmp_path / "ro"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        p = _paths(monkeypatch, ELI_ARTIFACTS_DIR=str(blocked))
        assert p.name == "index.faiss"
    finally:
        blocked.chmod(0o700)
