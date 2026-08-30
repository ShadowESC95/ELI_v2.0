"""Cross-family GGUF output token stripping and template routing."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import eli.cognition.gguf_inference as GI
from eli.cognition.model_output_tokens import (
    detect_template_family_from_embedded,
    is_persona_drift,
    strip_special_tokens,
    stop_tokens_for_family,
)


@pytest.mark.parametrize("raw,expected_fragment", [
    ("Hey there!<|end_of_turn|>", "Hey there!"),
    ("Answer here<|user|>next turn", "Answer here"),
    ("[gMASK]<|assistant|>Hi", "Hi"),
    ("Done.<|im_end|>", "Done."),
    ("Gemma reply<end_of_turn>", "Gemma reply"),
    ("Llama ok<|eot_id|>", "Llama ok"),
    ("Mistral [/INST] actual answer", "actual answer"),
    ("Phi end<|end|> tail", "Phi end tail"),
    ("GLM done<|endoftext|>", "GLM done"),
])
def test_strip_special_tokens_all_families(raw, expected_fragment):
    out = strip_special_tokens(raw)
    assert expected_fragment in out
    assert "<|end_of_turn|>" not in out
    assert "<|user|>" not in out


@pytest.mark.parametrize("text", [
    "I'm just a large language model, so I don't have feelings.",
    "As a large language model, I cannot help with that.",
    "How can I help you today?",
])
def test_is_persona_drift(text):
    assert is_persona_drift(text)


def test_is_not_persona_drift_for_eli_voice():
    assert not is_persona_drift("Yeah, memory's working — Fallout's still in there too.")


@pytest.mark.parametrize("tmpl,expect", [
    ("<|im_start|>system", "chatml"),
    ("[gMASK]<|user|>", "glm"),
    ("<|observation|>tool", "glm"),
    ("<|start_header_id|>system", "llama"),
    ("<start_of_turn>user", "gemma"),
    ("[INST] hello", "mistral"),
    ("<|assistant|> only phi", "phi"),
])
def test_embedded_template_family_detection(tmpl, expect):
    assert detect_template_family_from_embedded(tmpl) == expect


def test_glm_format_prompt():
    path = Path("GLM-4.7-Flash-Q4_K_M.gguf")
    with patch.object(GI, "get_model_path", return_value=path), \
         patch.object(GI, "_gguf_template_family", return_value="glm"):
        out = GI._format_prompt("You are ELI.", "hey")
    assert out.startswith("[gMASK]")
    assert "<|system|>You are ELI." in out
    assert "<|user|>hey" in out
    assert out.endswith("<|assistant|>")


def test_glm_filename_fallback_when_no_embedded_template():
    path = Path("GLM-4.7-Flash-Q4_K_M.gguf")
    with patch.object(GI, "get_model_path", return_value=path), \
         patch.object(GI, "_gguf_template_family", return_value=None):
        out = GI._format_prompt("SYS", "hi")
    assert out.startswith("[gMASK]")


def test_glm_stops_in_family_list():
    stops = stop_tokens_for_family("glm", include_label_stops=False)
    assert "<|observation|>" in stops
    assert "[gMASK]" in stops


def test_clean_eli_output_strips_glm_leak():
    leaked = "Sure thing.<|end_of_turn|>"
    assert "<|end_of_turn|>" not in GI._clean_eli_output(leaked)
