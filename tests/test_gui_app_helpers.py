"""GUI launcher (`eli/gui/app.py`) pure helpers.

Hardware detection, model-size bucketing, KV-cache math, runtime auto-tune, and
config round-trip. These are the launcher's *logic* — no Qt widgets, no display —
so they run in the normal suite even though they live under eli/gui.
"""
from __future__ import annotations

import pytest

from eli.gui import app


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("gb,expected", [
    (0.5, "tiny"), (1.4, "tiny"), (2.0, "small"),
    (4.0, "medium"), (8.0, "large"), (20.0, "large"),
])
def test_model_size_category(gb, expected):
    assert app._model_size_category(int(gb * 1e9)) == expected


def test_kv_cache_mb_math():
    # 2048 ctx * 32 layers * 6000 B / 1 MiB = 375 MB.
    assert round(app._kv_cache_mb(2048, 32), 1) == 375.0
    # quant quarters the estimate.
    assert app._kv_cache_mb(2048, 32, quant=True) == app._kv_cache_mb(2048, 32) / 4


# --------------------------------------------------------------------------- #
def test_detect_hardware_shape():
    hw = app._detect_hardware()
    for k in ("cpu_cores", "total_ram_gb", "available_ram_gb", "has_gpu", "vram_mb", "gpu_name"):
        assert k in hw
    assert isinstance(hw["cpu_cores"], int) and hw["cpu_cores"] >= 1
    assert isinstance(hw["has_gpu"], bool)
    assert hw["total_ram_gb"] > 0


# --------------------------------------------------------------------------- #
def test_auto_tune_no_gpu(tmp_path):
    model = tmp_path / "fake-7b.gguf"
    model.write_bytes(b"\0" * 4096)
    hw = {"cpu_cores": 8, "total_ram_gb": 16.0, "available_ram_gb": 12.0,
          "has_gpu": False, "gpu_name": "", "vram_mb": 0, "vram_total_mb": 0}
    params = app._auto_tune(model, hw)
    for k in ("n_ctx", "n_gpu_layers", "n_threads", "batch_size", "max_tokens", "temperature"):
        assert k in params
    assert params["n_ctx"] >= 2048
    assert params["n_gpu_layers"] == 0            # no VRAM → no offload
    assert params["n_threads"] >= 1


def test_auto_tune_low_ram_smaller_ctx(tmp_path):
    model = tmp_path / "fake.gguf"
    model.write_bytes(b"\0" * 4096)
    low = {"cpu_cores": 4, "total_ram_gb": 8.0, "available_ram_gb": 6.0,
           "has_gpu": False, "gpu_name": "", "vram_mb": 0, "vram_total_mb": 0}
    high = {"cpu_cores": 16, "total_ram_gb": 64.0, "available_ram_gb": 48.0,
            "has_gpu": False, "gpu_name": "", "vram_mb": 0, "vram_total_mb": 0}
    assert app._auto_tune(model, low)["n_ctx"] <= app._auto_tune(model, high)["n_ctx"]


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
