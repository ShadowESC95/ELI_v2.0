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


def test_a_picture_asked_for_in_chat_is_made_with_the_saved_settings(monkeypatch):
    """Only the desktop chat box could make a picture; GENERATE_IMAGE makes one for every surface,
    with the size and personalisation the image settings hold, and says where it went."""
    from eli.execution import executor_enhanced as ex
    import eli.tools.image_engine as ie
    settings = {"image_default_width": 640, "image_default_height": 480, "image_auto_personalize": False}
    req = GB.request_from_settings("a lighthouse", settings, seed=5)
    assert (req.prompt, req.width, req.height, req.count, req.seed, req.auto_personalize) == (
        "a lighthouse", 640, 480, 1, 5, False)
    assert (req.backend, req.model, req.steps) == ("", "", 0)        # generate_images takes the saved ones

    made = []

    def fake_generate(request, settings=None, **_k):
        made.append(request.prompt)
        return GB.ImageGenerationResult(saved_paths=["/out/eli_chat_lighthouse.png"], contact_sheet=None,
                                        manifest_path=None, out_dir="/out", applied_prompt=request.prompt)

    monkeypatch.setattr(ie, "generate_images", fake_generate)
    out = ex.execute("GENERATE_IMAGE", {"prompt": "a lighthouse"})
    assert out["ok"] and made == ["a lighthouse"] and out["path"] == "/out/eli_chat_lighthouse.png"
    assert "/out/eli_chat_lighthouse.png" in out["response"]

    def nothing_made(request, settings=None, **_k):
        return GB.ImageGenerationResult(saved_paths=[], contact_sheet=None, manifest_path=None, out_dir="/out",
                                        applied_prompt=request.prompt, problem="no weights downloaded")

    monkeypatch.setattr(ie, "generate_images", nothing_made)
    out = ex.execute("GENERATE_IMAGE", {"prompt": "a lighthouse"})
    assert not out["ok"] and out["response"] == "no weights downloaded"
