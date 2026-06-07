"""Diffusion backend + VRAM swap: weights detection, missing-weights messaging,
and the unload-LLM → generate → reload-LLM ordering around a diffusion job.

Deterministic — no real model load; generate_batch and the GGUF loader are mocked.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from eli.tools.image_engine.image_engine.visual_core import weights_present
from eli.tools.image_engine import gui_bridge as GB
from eli.tools.image_engine import ImageGenerationRequest, generate_images


def test_weights_present(tmp_path):
    # configs-only scaffold → False
    (tmp_path / "model_index.json").write_text("{}", encoding="utf-8")
    assert weights_present(str(tmp_path)) is False
    # add a weight file → True
    (tmp_path / "unet").mkdir()
    (tmp_path / "unet" / "diffusion_pytorch_model.safetensors").write_bytes(b"x")
    assert weights_present(str(tmp_path)) is True
    assert weights_present(str(tmp_path / "missing")) is False


def test_missing_weights_returns_fetch_message(tmp_path):
    # A diffusion model dir with configs but NO weight files → clear fetch note,
    # no images, no crash. Use a temp scaffold (not the real models/image/ssd-1b,
    # whose weights may now be downloaded locally) so the missing-weights path is
    # exercised deterministically regardless of the machine.
    (tmp_path / "model_index.json").write_text("{}", encoding="utf-8")
    req = ImageGenerationRequest(prompt="a lake", backend="diffusion",
                                 model=str(tmp_path), count=1,
                                 width=512, height=512, seed=1)
    res = generate_images(req, settings={"image_auto_personalize": False})
    assert res.saved_paths == []
    assert any("no weights downloaded" in n for n in res.personalization_notes)
    assert any("fetch_model" in n for n in res.personalization_notes)


def test_vram_swap_order_when_weights_present(tmp_path, monkeypatch):
    # Fake a model dir with weights so the diffusion branch + swap engage.
    (tmp_path / "model_index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "x.safetensors").write_bytes(b"x")

    calls = []
    monkeypatch.setattr(GB, "generate_batch", lambda args: (calls.append("generate"), [])[1])

    import eli.cognition.gguf_inference as gguf
    monkeypatch.setattr(gguf, "unload_model", lambda: calls.append("unload"))
    monkeypatch.setattr(gguf, "reload_model", lambda **k: calls.append("reload"))

    req = ImageGenerationRequest(prompt="a lake", backend="diffusion",
                                 model=str(tmp_path), count=1, width=512, height=512, seed=1)
    res = generate_images(req, settings={"image_auto_personalize": False})
    assert calls == ["unload", "generate", "reload"], calls
    assert res.saved_paths == []


def test_no_swap_for_procedural(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(GB, "generate_batch", lambda args: (calls.append("generate"), [])[1])
    import eli.cognition.gguf_inference as gguf
    monkeypatch.setattr(gguf, "unload_model", lambda: calls.append("unload"))
    monkeypatch.setattr(gguf, "reload_model", lambda **k: calls.append("reload"))

    req = ImageGenerationRequest(prompt="a lake", backend="procedural", count=1,
                                 width=512, height=512, seed=1)
    generate_images(req, settings={"image_auto_personalize": False})
    assert "unload" not in calls and "reload" not in calls
    assert calls == ["generate"]


def test_fetch_model_importable():
    from eli.tools.image_engine import fetch_model
    assert hasattr(fetch_model, "fetch")
