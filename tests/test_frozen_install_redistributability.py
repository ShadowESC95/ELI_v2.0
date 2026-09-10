"""Regression locks for AppImage/portable install failures (v2.3.94).

Failures observed on fresh Linux portable/AppImage installs (low-RAM laptops):
  - read-only writes under AppImage mount
  - DB at ~/.local/share/eli/ instead of ELI_v2
  - memories.value column missing on upgraded DBs
  - capability snapshot written into the bundle
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


def test_frozen_data_and_config_dirs_use_eli_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("ELI_DATA_DIR", raising=False)
    monkeypatch.delenv("ELI_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ELI_PROJECT_ROOT", raising=False)

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
