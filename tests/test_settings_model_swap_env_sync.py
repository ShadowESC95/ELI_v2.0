"""Settings model swap must update ELI_GGUF_MODEL_PATH, not reload the old GGUF."""
from __future__ import annotations

import os
import threading
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


def test_a_model_outside_elis_folder_that_exists_is_kept(tmp_path, monkeypatch):
    """A browsed-to model (~/Downloads, another drive) was wiped from the settings at the next load:
    two guards each cleared a full path outside the install folder. Only a path that no longer exists
    is stale. Read through load_settings(), as the app reads it."""
    import json
    from eli.core import runtime_settings as rs
    for name in ("ELI_ALLOW_EXTERNAL_MODEL_PATHS", "ELI_SETTINGS_FILE", "ELI_SETTINGS_PATH", "ELI_GGUF_MODEL_PATH",
                 "ELI_MODEL_PATH", "ELI_CUSTOM_MODEL_PATH", "ELI_BUNDLED_MODEL_PATH", "ELI_GGUF_MODEL"):
        monkeypatch.delenv(name, raising=False)
    root, downloads = tmp_path / "ELI_v2", tmp_path / "Downloads"
    (root / "config").mkdir(parents=True)
    downloads.mkdir()
    model = downloads / "chosen.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setenv("ELI_CONFIG_DIR", str(root / "config"))
    for fn in ("_eli_runtime_physical_project_root", "_eli_final_project_root"):
        monkeypatch.setattr(rs, fn, lambda: root)
    (root / "config" / "settings.json").write_text(json.dumps(
        {"provider": "custom_gguf", "model_path": str(model), "custom_model_path": str(downloads / "gone.gguf"),
         "gguf_model_path": "../elsewhere.gguf"}), encoding="utf-8")
    loaded = rs.load_settings()
    assert loaded["model_path"] == str(model.resolve())
    assert loaded["custom_model_path"] == "" and loaded["gguf_model_path"] == ""


def test_a_path_set_while_running_stays_through_later_settings_reads(tmp_path, monkeypatch):
    """A test pointed ELI_CONFIG_DIR at its own folder, another thread read the settings, and the
    check for paths a copied install inherits took the variable away: the writes went to the project."""
    from eli.core import runtime_settings as rs
    rs.load_settings()
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path / "cfg"))
    reader = threading.Thread(target=rs.load_settings)
    reader.start()
    reader.join()
    assert os.environ["ELI_CONFIG_DIR"] == str(tmp_path / "cfg")


def test_a_path_inherited_from_another_install_is_dropped_at_start(tmp_path, monkeypatch, caplog):
    """Another ELI install's folders are its own (every ELI product keeps its own): a config folder
    inside one is dropped, and the log says which and why."""
    import logging
    from eli.core import runtime_settings as rs
    other = tmp_path / "another-install"
    for folder in ("eli/cognition", "eli/gui", "config"):
        (other / folder).mkdir(parents=True)
    monkeypatch.setattr(rs, "_STALE_ENV_CHECKED", False)
    monkeypatch.setenv("ELI_CONFIG_DIR", str(other / "config"))
    with caplog.at_level(logging.WARNING, logger="eli.core.runtime_settings"):
        rs.load_settings()
    assert "ELI_CONFIG_DIR" not in os.environ
    assert "ELI_CONFIG_DIR" in caplog.text and str(other) in caplog.text


def test_a_config_folder_the_user_set_outside_the_install_is_kept_and_read(tmp_path, monkeypatch):
    """The check dropped every folder variable outside the checkout when the process started, so an
    ELI_CONFIG_DIR the user had set was taken away without a word and the checkout's own
    config/settings.json was read in its place."""
    import json
    from eli.core import runtime_settings as rs
    mine = tmp_path / "my-eli-settings"          # the user's own folder, in no ELI install
    mine.mkdir()
    (mine / "settings.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    for name in ("ELI_SETTINGS_FILE", "ELI_SETTINGS_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(rs, "_STALE_ENV_CHECKED", False)
    monkeypatch.setenv("ELI_CONFIG_DIR", str(mine))
    assert rs.load_settings()["theme"] == "light"
    assert os.environ["ELI_CONFIG_DIR"] == str(mine)
    assert rs.inherited_from_another_install(mine / "not-made-yet") is None


# ── The environment and the saved settings: which value governs (runtime_settings, above apply_env) ──
_LOAD_VARS = ("ELI_N_CTX", "ELI_GGUF_N_CTX", "ELI_GGUF_N_BATCH", "ELI_BATCH_SIZE", "ELI_SETTINGS_PUBLISHED")


@pytest.fixture()
def saved_auto_ctx(tmp_path, monkeypatch):
    for name in _LOAD_VARS:
        monkeypatch.delenv(name, raising=False)
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"n_ctx": 0, "batch_size": 512}\n', encoding="utf-8")
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings_file))
    return settings_file


def test_a_save_keeps_the_context_and_batch_the_operator_exported(saved_auto_ctx, monkeypatch):
    """Every save wrote the file's values over the load variables: with the saved context on auto
    an exported ELI_N_CTX=16384 was removed, and ELI_GGUF_N_BATCH=1024 became the saved 512."""
    from eli.core import runtime_settings as rs
    monkeypatch.setenv("ELI_N_CTX", "16384")
    monkeypatch.setenv("ELI_GGUF_N_BATCH", "1024")
    rs.save_settings({"theme": "light"})
    assert os.environ["ELI_N_CTX"] == os.environ["ELI_GGUF_N_CTX"] == "16384"   # the loader's name too
    assert os.environ["ELI_GGUF_N_BATCH"] == os.environ["ELI_BATCH_SIZE"] == "1024"
    rs.apply_env(rs.load_settings_from_disk())              # what a reload does
    assert os.environ["ELI_N_CTX"] == os.environ["ELI_GGUF_N_CTX"] == "16384"
    assert os.environ["ELI_GGUF_N_BATCH"] == "1024"
    loaded = rs.load_settings()
    assert (loaded["n_ctx"], loaded["batch_size"]) == (16384, 1024)


def test_the_user_changing_a_setting_in_the_app_takes_over_from_the_export(saved_auto_ctx, monkeypatch):
    from eli.core import runtime_settings as rs
    monkeypatch.setenv("ELI_N_CTX", "16384")
    monkeypatch.setenv("ELI_GGUF_N_BATCH", "1024")
    rs.save_settings({"n_ctx": 16384, "batch_size": 1024})     # what was in force, saved back: no change
    assert os.environ["ELI_N_CTX"] == "16384" and os.environ["ELI_GGUF_N_BATCH"] == "1024"
    rs.save_settings({"n_ctx": 8192})
    assert os.environ["ELI_N_CTX"] == os.environ["ELI_GGUF_N_CTX"] == "8192"
    assert os.environ["ELI_GGUF_N_BATCH"] == "1024"             # not changed, still the export
    rs.save_settings({"n_ctx": 0})                               # auto
    assert "ELI_N_CTX" not in os.environ and "ELI_GGUF_N_CTX" not in os.environ
    rs.save_settings({"theme": "dark"})
    assert "ELI_N_CTX" not in os.environ and rs.load_settings()["n_ctx"] == 0


def test_an_exported_model_outlasts_saves_until_a_model_is_picked_in_the_app(settings_home, monkeypatch):
    """The fixture exports ELI_GGUF_MODEL_PATH (old-model). Saves of other settings and a reload
    wrote the file's model over it; picking a model in the app is what replaces it."""
    _tmp_path, _old_model, new_model, settings_file = settings_home
    from eli.core import runtime_settings as rs
    monkeypatch.delenv("ELI_SETTINGS_PUBLISHED", raising=False)
    settings_file.write_text('{"provider":"custom_gguf","model_path":"models/new-model.gguf"}\n', encoding="utf-8")
    rs.save_settings({"theme": "light"})
    assert os.environ["ELI_GGUF_MODEL_PATH"] == "models/old-model.gguf"     # the export, not the file
    rs.apply_env(rs.load_settings_from_disk())
    assert os.environ["ELI_GGUF_MODEL_PATH"] == "models/old-model.gguf"
    rs.save_settings({"model_path": "models/new-model.gguf"})              # picked in the app
    assert Path(os.environ["ELI_GGUF_MODEL_PATH"]).name == new_model.name
    rs.save_settings({"theme": "dark"})
    assert Path(os.environ["ELI_GGUF_MODEL_PATH"]).name == new_model.name


def test_the_think_switch_follows_a_change_made_through_the_settings(saved_auto_ctx, monkeypatch):
    """ELI_MODEL_THINK was written once and then never again: turning deep thinking off through the
    settings (the API, the dashboard) had no effect until a restart."""
    from eli.core import runtime_settings as rs
    monkeypatch.delenv("ELI_MODEL_THINK", raising=False)
    rs.save_settings({"model_thinking": True})
    assert os.environ["ELI_MODEL_THINK"] == "1"
    rs.save_settings({"model_thinking": False})
    assert os.environ["ELI_MODEL_THINK"] == "0"
