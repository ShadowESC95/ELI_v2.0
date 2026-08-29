"""Regression tests for v2.3.49 AppImage path + memory/self-update fixes."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eli.contracts import runtime_status as rs
from eli.kernel.engine import _eli_mc_counts_v4
from eli.runtime import control_contracts as cc


def test_memory_count_uses_eli_data_dir_not_cwd(tmp_path, monkeypatch):
    db_dir = tmp_path / "artifacts" / "db"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "user.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, text TEXT)")
        conn.executemany("INSERT INTO memories (text) VALUES (?)", [("m",)] * 7)
        conn.commit()

    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ELI_USER_DB", str(db_path))
    monkeypatch.setenv("ELI_AGENT_DB", str(db_dir / "agent.sqlite3"))
    monkeypatch.setenv("ELI_DB_DIR", str(db_dir))
    (tmp_path / "empty_cwd").mkdir()
    monkeypatch.chdir(tmp_path / "empty_cwd")

    from eli.core import paths as cp

    for name in ("data_dir", "config_dir", "user_db_path", "agent_db_path", "project_root"):
        fn = getattr(cp, name, None)
        if fn is not None and hasattr(fn, "cache_clear"):
            fn.cache_clear()

    resolved, counts = _eli_mc_counts_v4()
    assert Path(resolved) == db_path.resolve()
    assert counts["long_term_memory_rows"] == 7


def test_runtime_status_paths_use_canonical_data_dir(tmp_path, monkeypatch):
    artifacts = tmp_path / "userdata" / "artifacts"
    config = tmp_path / "userdata" / "config"
    db_dir = artifacts / "db"
    db_dir.mkdir(parents=True)
    config.mkdir(parents=True)
    (db_dir / "user.sqlite3").write_text("")
    (db_dir / "agent.sqlite3").write_text("")
    (artifacts / "runtime_snapshot.json").write_text(
        '{"provider":"gguf","model_path":"/models/q.gguf","n_ctx":4096,"loaded":true}'
    )
    (config / "settings.json").write_text('{"provider":"gguf","n_ctx":4096}')

    (tmp_path / "install").mkdir()
    monkeypatch.setenv("ELI_DATA_DIR", str(artifacts))
    monkeypatch.setenv("ELI_CONFIG_DIR", str(config))
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path / "install"))
    monkeypatch.setenv("ELI_USER_DB", str(db_dir / "user.sqlite3"))
    monkeypatch.setenv("ELI_AGENT_DB", str(db_dir / "agent.sqlite3"))
    monkeypatch.setenv("ELI_DB_DIR", str(db_dir))
    (tmp_path / "wrong_cwd").mkdir()
    monkeypatch.chdir(tmp_path / "wrong_cwd")

    from eli.core import paths as cp

    for name in ("data_dir", "config_dir", "user_db_path", "agent_db_path", "project_root"):
        fn = getattr(cp, name, None)
        if fn is not None and hasattr(fn, "cache_clear"):
            fn.cache_clear()

    evidence = rs.build_live_evidence(mode="quick")
    assert str(tmp_path / "install") in evidence.project_root
    assert evidence.user_db == str((db_dir / "user.sqlite3").resolve())
    assert evidence.agent_db == str((db_dir / "agent.sqlite3").resolve())
    assert evidence.model_path == "/models/q.gguf"
    assert evidence.context_size == 4096


def test_self_update_build_control_evidence_is_compact_not_json(monkeypatch):
    monkeypatch.setattr(
        cc,
        "runtime_paths",
        lambda: {
            "project_root": "/home/user/.local/share/ELI_v2",
            "user_db": "/home/user/.local/share/ELI_v2/artifacts/db/user.sqlite3",
            "model_path": "/home/user/.local/share/ELI_v2/models/m.gguf",
        },
    )
    monkeypatch.setattr(
        "eli.runtime.self_model_refresh.refresh_all_overlays_nonfatal",
        lambda reason="": {
            "ok": True,
            "capability_manifest": {"total": 225, "summary": "no capability changes"},
            "persona_overlay": {"ok": True, "skipped": True},
            "user_profile_overlay": {"ok": True, "skipped": True},
            "user_info_snapshot": {"ok": True, "refreshed": False},
        },
    )
    monkeypatch.setattr(
        "eli.runtime.self_model_refresh.refresh_world_model_runtime",
        lambda: True,
    )

    out = cc.build_control_evidence(None, "SELF_UPDATE", {}, "self update")
    text = out["content"]
    assert "Self-update evidence packet:" not in text
    assert '"paths":' not in text
    assert "Self-update result:" in text
    assert "world_model_runtime_refreshed: True" in text
    assert "ELI_v2" in text


def test_identity_false_denial_violates_evidence():
    evidence = (
        "Yes, I have memory records associated with the active user profile.\n"
        "No confirmed name is stored for the active user."
    )
    bad = "No issues with my memory or database. I don't store personal information about users."
    assert cc.output_violates_evidence(bad, evidence) is True

    ok = "Yes — I have memory records for your profile. I don't have a confirmed name stored yet."
    assert cc.output_violates_evidence(ok, evidence) is False
