"""Model-agnostic identity: template/arch beat filename brands."""
from __future__ import annotations

from pathlib import Path

import eli.cognition.gguf_inference as GI
from eli.cognition.model_identity import (
    family_from_architecture,
    is_thinking_model,
    resolve_chat_family,
    template_enables_thinking,
)


def test_family_from_architecture_not_filename():
    assert family_from_architecture("gemma4") == "gemma"
    assert family_from_architecture("smollm3") == "chatml"
    assert family_from_architecture("dflash-draft") is None
    assert family_from_architecture("qwen3moe") == "chatml"
    assert family_from_architecture("llama") == "llama"


def test_resolve_chat_family_template_beats_filename():
    # Filename says mistral; template is ChatML → ChatML wins.
    fam = resolve_chat_family(
        template="<|im_start|>user\n{{message}}<|im_end|>",
        path="Mistral-7B-Instruct-v0.2.gguf",
    )
    assert fam == "chatml"


def test_resolve_chat_family_arch_beats_filename():
    fam = resolve_chat_family(
        architecture="gemma4",
        path="totally-renamed-weights.gguf",
    )
    assert fam == "gemma"


def test_thinking_from_template_not_brand_name():
    tmpl = (
        "{%- if enable_thinking is not defined -%}"
        "{%- set enable_thinking = true -%}"
        "{%- endif -%}"
        "{% if enable_thinking %}<think>{% endif %}"
    )
    assert template_enables_thinking(tmpl)
    assert is_thinking_model(template=tmpl, path="renamed-mystery.gguf")
    # No template, no thinking arch → False even with qwen3 in the *name*
    # wait — arch default still applies for qwen3; use a neutral arch:
    assert not is_thinking_model(
        template="",
        architecture="llama",
        path="qwen3-deepseek-r1-ornith-twil.gguf",
    )


def test_thinking_arch_default_smollm3():
    assert is_thinking_model(architecture="smollm3", path="renamed.gguf")


def test_gguf_inference_thinking_uses_metadata(monkeypatch):
    monkeypatch.setattr(
        GI,
        "_gguf_model_metadata",
        lambda: {
            "tokenizer.chat_template": "{%- set enable_thinking = true -%}<think>",
            "general.architecture": "unknown-custom",
        },
    )
    monkeypatch.setattr(GI, "_loaded_model_path_str", lambda: "renamed.gguf")
    assert GI._is_thinking_model() is True


def test_gguf_inference_family_from_arch(monkeypatch):
    monkeypatch.setattr(
        GI,
        "_gguf_model_metadata",
        lambda: {"general.architecture": "gemma4", "tokenizer.chat_template": ""},
    )
    monkeypatch.setattr(GI, "get_model_path", lambda: Path("renamed.gguf"))
    out = GI._format_prompt("sys", "hi")
    assert "<start_of_turn>" in out


def test_twil_on_disk_identity_if_present():
    p = Path("models/TwIL-LM3-Q8_0.gguf")
    if not p.exists():
        return
    from eli.cognition.model_identity import read_gguf_identity
    ident = read_gguf_identity(p)
    assert ident["architecture"] == "smollm3"
    assert ident["thinking"] is True
    assert ident["family"] in ("chatml", "phi", "llama", "gemma", "mistral", "glm")
