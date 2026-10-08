"""Regression locks for AppImage/portable install failures (v2.3.94).

Failures observed on fresh Linux portable/AppImage installs (low-RAM laptops):
  - read-only writes under AppImage mount
  - DB at ~/.local/share/eli/ instead of ELI_v2
  - memories.value column missing on upgraded DBs
  - capability snapshot written into the bundle
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest


def test_frozen_data_and_config_dirs_use_eli_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ELI_DATA_DIR", raising=False)
    monkeypatch.delenv("ELI_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ELI_PROJECT_ROOT", raising=False)
    # tests/conftest.py sets this process-wide, for the whole suite, so no test
    # run ever touches the real persona file (a past incident — see
    # persona_auto_path()'s own docstring). That override must win in every
    # OTHER test; this one specifically exercises what persona_auto_path()
    # computes with no override at all under a simulated frozen install, so
    # it has to clear the override to test the thing it's actually testing.
    monkeypatch.delenv("ELI_PERSONA_AUTO_PATH", raising=False)

    from eli.core import paths

    paths.data_dir.cache_clear()
    paths.config_dir.cache_clear()

    root = paths.project_root()
    assert root.name == "ELI_v2"
    assert paths.data_dir() == root / "artifacts"
    assert paths.config_dir() == root / "config"
    assert paths.persona_auto_path() == root / "config" / "persona.auto.txt"


def test_frozen_project_root_rejects_read_only_explicit_env(tmp_path, monkeypatch):
    import os

    read_only = tmp_path / "readonly_mount"
    read_only.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(read_only))
    os.chmod(read_only, 0o555)

    from eli.core import paths

    paths.data_dir.cache_clear()

    resolved = paths.project_root()
    assert resolved.name == "ELI_v2"
    assert paths.data_dir().is_relative_to(resolved)


def test_capability_sync_state_dir_is_writable_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "artifacts"))

    from eli.core import paths
    from eli.runtime.capability_sync import CapabilitySync

    paths.data_dir.cache_clear()
    sync = CapabilitySync(repo_root=tmp_path / "bundle")
    state = sync._state_dir()
    assert state == tmp_path / "artifacts" / "runtime"
    state.mkdir(parents=True, exist_ok=True)
    probe = state / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"


def test_memory_schema_adds_value_column_on_legacy_db(tmp_path):
    db = tmp_path / "user.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            text TEXT,
            content TEXT
        )
        """
    )
    conn.commit()

    from eli.memory.memory import _ensure_memory_schema

    _ensure_memory_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    assert "value" in cols

    conn.execute(
        "INSERT INTO memories (ts, text, value) VALUES (?, ?, ?)",
        (1.0, "hello", "world"),
    )
    conn.commit()
    row = conn.execute("SELECT value FROM memories WHERE id=1").fetchone()
    assert row[0] == "world"
    conn.close()


def test_rthook_safe_copy_reads_from_readonly_source(tmp_path):
    import importlib.util

    src_root = tmp_path / "bundle"
    dst_root = tmp_path / "user"
    src_file = src_root / "tts_piper" / "piper" / "voice.onnx"
    src_file.parent.mkdir(parents=True)
    src_file.write_bytes(b"onnx-bytes")

    hook_path = Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller" / "rthook_eli_frozen_paths.py"
    spec = importlib.util.spec_from_file_location("rthook_eli_frozen_paths", hook_path)
    hook = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(hook)

    hook._safe_copy_file(src_file, dst_root / "tts_piper" / "piper" / "voice.onnx")
    copied = dst_root / "tts_piper" / "piper" / "voice.onnx"
    assert copied.read_bytes() == b"onnx-bytes"


# A frozen build copies its eli/ source into the user's data folder and runs it from there. The copy
# was keyed on the version alone, so a second build under the same number (a dry run, a release
# rebuilt under its tag) found the first one's copy and ran the old code.
ROOT = Path(__file__).resolve().parents[1]


def _hook():
    spec = importlib.util.spec_from_file_location("rthook_eli_frozen_paths",
                                                  ROOT / "packaging" / "pyinstaller" / "rthook_eli_frozen_paths.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _bundle(path: Path, stamp: str, code: str) -> Path:
    (path / "eli" / "core").mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (path / "build_stamp.txt").write_text(stamp + "\n", encoding="utf-8")
    (path / "eli" / "core" / "mod.py").write_text(code, encoding="utf-8")
    return path


def test_a_rebuild_under_the_same_version_replaces_the_copy(tmp_path):
    hook, user = _hook(), tmp_path / "user"
    hook._seed(_bundle(tmp_path / "first", "aaaa", "OLD = 1\n"), user)
    hook._seed(_bundle(tmp_path / "second", "bbbb", "NEW = 1\n"), user)
    assert (user / "eli" / "core" / "mod.py").read_text(encoding="utf-8") == "NEW = 1\n"


def test_the_same_build_does_not_copy_again(tmp_path):
    hook, user = _hook(), tmp_path / "user"
    bundle = _bundle(tmp_path / "b", "aaaa", "X = 1\n")
    hook._seed(bundle, user)
    (user / "eli" / "core" / "mod.py").write_text("PATCHED = 1\n", encoding="utf-8")   # self-improvement's edit
    hook._seed(bundle, user)
    assert (user / "eli" / "core" / "mod.py").read_text(encoding="utf-8") == "PATCHED = 1\n"


def test_the_build_records_its_source():
    spec = (ROOT / "ELI.spec").read_text(encoding="utf-8")
    assert "build_stamp.txt" in spec and '"rev-parse", "HEAD"' in spec
