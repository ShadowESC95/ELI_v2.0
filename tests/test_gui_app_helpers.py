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
def test_config_round_trip(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(app, "save_settings", lambda c: store.clear() or store.update(c))
    monkeypatch.setattr(app, "load_settings", lambda: dict(store))
    # _save_config strips legacy keys before persisting.
    app._save_config({"temperature": 0.5, "gpu_layers": 99, "context_size": 4096})
    assert "gpu_layers" not in store and "context_size" not in store
    assert store["temperature"] == 0.5
    assert app._load_config()["temperature"] == 0.5
