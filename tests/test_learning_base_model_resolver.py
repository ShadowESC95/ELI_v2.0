from eli.learning.base_model_resolver import resolve_base_model_path


def test_rejects_missing_explicit_base_without_default_fallback(tmp_path):
    r = resolve_base_model_path(
        tmp_path / "missing-phi-base",
        allow_default_candidates=False,
    )
    assert r["ok"] is False
    assert "No valid local trainable Phi-3 base model directory found." in r["problems"]


def test_rejects_gguf_file_without_default_fallback(tmp_path):
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(b"GGUF")

    r = resolve_base_model_path(gguf, allow_default_candidates=False)

    assert r["ok"] is False
    assert any(c.get("is_gguf") for c in r["checked"])


def test_rejects_lora_adapter_dir_without_default_fallback(tmp_path):
    d = tmp_path / "adapter"
    d.mkdir()
    (d / "adapter_config.json").write_text("{}", encoding="utf-8")
    (d / "adapter_model.safetensors").write_text("x", encoding="utf-8")

    r = resolve_base_model_path(d, allow_default_candidates=False)

    assert r["ok"] is False
    assert any(c.get("looks_like_lora_adapter") for c in r["checked"])


def test_resolves_downloaded_default_phi_base_when_available():
    r = resolve_base_model_path()

    assert r["ok"] is True
    assert "models/hf/Phi-3-mini-4k-instruct" in r["relative"]
    assert any(c.get("ok") for c in r["checked"])
