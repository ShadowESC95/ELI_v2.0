"""GUI launcher (`eli/gui/app.py`) pure helpers.

KV-cache math, runtime auto-tune (the loader's own plan, eli/core/load_plan.py) and config round-trip.
These are the launcher's *logic* — no Qt widgets, no display — so they run in the normal suite even
though they live under eli/gui.
"""
from __future__ import annotations

import pytest

from eli.gui import app


def test_kv_cache_mb_math_without_a_model_file():
    # only when no model file can be read: 2048 ctx * 32 layers * 6000 B / 1 MiB = 375 MB
    from eli.core.hardware_profile import _kv_cache_mb
    assert round(_kv_cache_mb(2048, 32), 1) == 375.0
    # the quantized cache ELI loads is q8_0: 34 bytes for 32 values, against fp16's 64
    assert _kv_cache_mb(2048, 32, quant=True) == _kv_cache_mb(2048, 32) * 34 / 64


# --------------------------------------------------------------------------- #
def _plan(**kw):
    from eli.core import load_plan
    base = dict(model_path="m.gguf", n_ctx=16384, n_gpu_layers=29, n_batch=256, n_threads=6,
                cache_type_k="q8_0", cache_type_v="q8_0", flash_attn=True, split_mode=1, main_gpu=0,
                tensor_split=[10, 19], experts_in_ram=None, blocks=28)
    base.update(kw)
    return load_plan.Plan(**base)


def test_auto_tune_shows_the_plan_the_loader_will_use(tmp_path, monkeypatch):
    from eli.core import load_plan
    model = tmp_path / "fake.gguf"
    model.write_bytes(b"\0" * 4096)
    monkeypatch.setattr(load_plan, "plan", lambda req: _plan())
    params = app._auto_tune(model)
    assert (params["n_ctx"], params["n_gpu_layers"], params["batch_size"], params["n_threads"]) == (16384, 29, 256, 6)
    assert params["cache_type_k"] == "q8_0" and params["max_tokens"] == -1


def test_auto_tune_of_an_unreadable_file_is_the_request_as_given(tmp_path, monkeypatch):
    from eli.core import load_plan
    model = tmp_path / "fake.gguf"
    model.write_bytes(b"\0" * 4096)
    monkeypatch.setattr(load_plan, "plan", lambda req: None)
    params = app._auto_tune(model)
    assert params["n_ctx"] >= 2048 and params["n_threads"] >= 1


# --------------------------------------------------------------------------- #
def test_the_terminal_setup_offers_chat_models_and_the_saved_one_wherever_it_is(tmp_path, monkeypatch):
    """`--setup` (and a start with the startup picker turned off) listed every *.gguf under ./models,
    the vision projector and the embedder among them, and stopped with "no models" when the saved
    model was kept anywhere else."""
    from tests.test_any_gguf import _gguf
    from eli.core import paths
    models, elsewhere = tmp_path / "models", tmp_path / "elsewhere"
    models.mkdir()
    elsewhere.mkdir()
    talker = {"general.architecture": "llama", "tokenizer.ggml.model": "gpt2"}
    chat = _gguf(models / "chat.gguf", talker)
    _gguf(models / "mmproj-chat-f16.gguf", {"general.architecture": "clip"})
    _gguf(models / "text-embedder.gguf", {"general.architecture": "bert", "tokenizer.ggml.model": "bert",
                                          "bert.pooling_type": 1})
    saved = _gguf(elsewhere / "kept-here.gguf", talker)
    monkeypatch.setenv("ELI_MODELS_DIR", str(models))
    monkeypatch.setattr(paths, "project_root", lambda: tmp_path / "program")   # its own models/: none
    names = lambda saved_model: [p.name for p in app._setup_models(saved_model)]
    assert names(None) == ["chat.gguf"]
    assert names(saved) == ["kept-here.gguf", "chat.gguf"]
    assert names(chat) == ["chat.gguf"]                          # found already: listed once
    for f in list(models.iterdir()):
        f.unlink()
    assert names(saved) == ["kept-here.gguf"]                    # not "no models"


# --------------------------------------------------------------------------- #
def test_the_launcher_keeps_the_users_config_folder_and_replaces_another_installs(tmp_path, monkeypatch):
    """The console-script launcher pinned the data, config and models folders to its own checkout
    whenever ELI_PROJECT_ROOT was not already its root: a config folder the user had set was
    replaced too, and ELI read the checkout's settings in its place."""
    import os
    this, other = tmp_path / "this-install", tmp_path / "other-install"
    for tree in (this, other):
        for folder in ("eli/cognition", "eli/gui"):
            (tree / folder).mkdir(parents=True)
    mine, models = tmp_path / "my-config", tmp_path / "shared-models"
    monkeypatch.setenv("ELI_CONFIG_DIR", str(mine))
    monkeypatch.setenv("ELI_DATA_DIR", str(other / "artifacts"))
    monkeypatch.setenv("ELI_MODELS_DIR", str(models))
    app._pin_this_install(this)
    assert os.environ["ELI_PROJECT_ROOT"] == str(this)
    assert os.environ["ELI_CONFIG_DIR"] == str(mine)
    assert os.environ["ELI_DATA_DIR"] == str(this / "artifacts")
    assert os.environ["ELI_MODELS_DIR"] == str(models)
    monkeypatch.delenv("ELI_CONFIG_DIR")
    monkeypatch.delenv("ELI_MODELS_DIR")
    app._pin_this_install(this)
    assert os.environ["ELI_CONFIG_DIR"] == str(this / "config")
    assert os.environ["ELI_MODELS_DIR"] == str(this / "models")


# --------------------------------------------------------------------------- #
def test_config_round_trip(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(app, "save_settings", lambda c: store.clear() or store.update(c))
    monkeypatch.setattr(app, "load_settings", lambda: dict(store))
    # _save_config strips legacy keys before persisting.
    app._save_config({"temperature": 0.5, "gpu_layers": 99, "context_size": 4096})
    assert "gpu_layers" not in store and "context_size" not in store
    assert store["temperature"] == 0.5
    assert app._load_config()["temperature"] == 0.5
