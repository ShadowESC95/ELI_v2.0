"""Settings model swap must update ELI_GGUF_MODEL_PATH, not reload the old GGUF."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def settings_home(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    old_model = models / "old-model.gguf"
    new_model = models / "new-model.gguf"
    old_model.write_bytes(b"GGUF")
    new_model.write_bytes(b"GGUF")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        '{"provider":"custom_gguf","model_path":"models/old-model.gguf",'
        '"custom_model_path":"models/old-model.gguf","n_ctx":2048,"n_gpu_layers":0,'
        '"batch_size":64,"n_threads":4}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings_file))
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("ELI_ALLOW_EXTERNAL_MODEL_PATHS", "1")
    # Relative env pin (same shape the GUI/apply_env write) so the portability
    # guard does not treat it as a foreign-machine absolute path.
    monkeypatch.setenv("ELI_GGUF_MODEL_PATH", "models/old-model.gguf")

    from eli.core import runtime_settings as rs
    monkeypatch.setattr(rs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rs, "_eli_runtime_physical_project_root", lambda: tmp_path)
    monkeypatch.setattr(rs, "_eli_final_project_root", lambda: tmp_path)
    return tmp_path, old_model, new_model, settings_file


def test_save_settings_updates_gguf_model_path_env(settings_home):
    _tmp_path, _old_model, new_model, _settings_file = settings_home
    from eli.core import runtime_settings as rs
    from eli.core.paths import resolve_runtime_path

    rs.save_settings({
        "model_path": "models/new-model.gguf",
        "custom_model_path": "models/new-model.gguf",
        "provider": "custom_gguf",
    })
    env_raw = os.environ.get("ELI_GGUF_MODEL_PATH", "")
    assert "new-model.gguf" in env_raw.replace("\\", "/")
    # Prefer basename check — resolve may map through install root depending
    # on path helpers, but apply_env must have flipped away from old-model.
    assert "old-model.gguf" not in env_raw.replace("\\", "/")
    assert new_model.name in Path(env_raw).name


def test_load_settings_from_disk_ignores_stale_env(settings_home, monkeypatch):
    _tmp_path, _old_model, _new_model, settings_file = settings_home
    from eli.core import runtime_settings as rs

    settings_file.write_text(
        '{"provider":"custom_gguf","model_path":"models/new-model.gguf",'
        '"custom_model_path":"models/new-model.gguf"}\n',
        encoding="utf-8",
    )
    # Env still points at the old model (GUI pin).
    monkeypatch.setenv("ELI_GGUF_MODEL_PATH", "models/old-model.gguf")
    poisoned = rs.load_settings()
    assert "old-model" in str(poisoned.get("model_path") or "")
    disk = rs.load_settings_from_disk()
    assert "new-model" in str(disk.get("model_path") or "")


def test_phatic_how_are_you_this_evening():
    from eli.kernel.engine import _is_brief_phatic_prompt

    assert _is_brief_phatic_prompt("hey eli, how are you this evening?")
    assert _is_brief_phatic_prompt("how are you today")
    assert _is_brief_phatic_prompt("how are you this morning")


def test_phatic_speaking_in_tongues_meta():
    from eli.kernel.engine import _is_brief_phatic_prompt

    assert _is_brief_phatic_prompt("hey buddy, you still speaking in tounges?")
    assert _is_brief_phatic_prompt("you still speaking in tongues?")
    assert not _is_brief_phatic_prompt(
        "search for why the model is speaking in tongues and fix the router"
    )


def test_draft_only_gguf_preflight(tmp_path):
    from eli.cognition.model_load_diagnostics import (
        draft_only_load_message,
        is_draft_only_gguf,
        preflight_gguf_model,
    )

    p = tmp_path / "Kimi-K3-DSpark-Q8_0.gguf"
    p.write_bytes(b"GGUF")
    assert is_draft_only_gguf(p, "dflash-draft")
    msg = draft_only_load_message(p, "dflash-draft")
    assert "draft" in msg.lower()
    assert "chat" in msg.lower()
    # preflight needs a real readable header for arch; filename markers still work
    assert is_draft_only_gguf(p)
