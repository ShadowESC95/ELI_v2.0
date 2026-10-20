"""Every model is prompted in its own format, rendered from the template in its GGUF file.

The templates here are cut down from real ones (Gemma 4, Qwen3, SmolLM3, DeepSeek-R1) to the parts
that decide the format: turn markers, the system turn, the thinking switch and the reasoning field.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import eli.cognition.gguf_inference as GI
from eli.cognition import chat_template as CT

GEMMA4 = (
    "{%- set enable_thinking = enable_thinking | default(false) -%}"
    "{{- bos_token -}}"
    "{%- set loop_messages = messages -%}"
    "{%- if enable_thinking or (messages and messages[0]['role'] == 'system') -%}"
    "{{- '<|turn>system\\n' -}}{%- if enable_thinking -%}{{- '<|think|>\\n' -}}{%- endif -%}"
    "{%- if messages[0]['role'] == 'system' -%}{{- messages[0]['content'] | trim -}}"
    "{%- set loop_messages = messages[1:] -%}{%- endif -%}{{- '<turn|>\\n' -}}{%- endif -%}"
    "{%- for message in loop_messages -%}"
    "{%- set role = 'model' if message['role'] == 'assistant' else message['role'] -%}"
    "{{- '<|turn>' + role + '\\n' -}}"
    "{%- set thinking_text = message.get('reasoning') or message.get('reasoning_content') -%}"
    "{%- if thinking_text -%}{{- '<|channel>thought\\n' + thinking_text + '\\n<channel|>' -}}{%- endif -%}"
    "{{- message['content'] | trim -}}{{- '<turn|>\\n' -}}"
    "{%- endfor -%}"
    "{%- if add_generation_prompt -%}{{- '<|turn>model\\n' -}}{%- endif -%}"
)

QWEN3 = (
    "{%- for message in messages -%}"
    "{%- if message.role == 'assistant' and message.reasoning_content -%}"
    "{{- '<|im_start|>assistant\\n<think>\\n' + message.reasoning_content + '\\n</think>\\n\\n' + message.content + '<|im_end|>\\n' -}}"
    "{%- else -%}{{- '<|im_start|>' + message.role + '\\n' + message.content + '<|im_end|>\\n' -}}{%- endif -%}"
    "{%- endfor -%}"
    "{%- if add_generation_prompt -%}{{- '<|im_start|>assistant\\n' -}}"
    "{%- if enable_thinking is defined and enable_thinking is false -%}{{- '<think>\\n\\n</think>\\n\\n' -}}{%- endif -%}"
    "{%- endif -%}"
)

NO_SYSTEM = (
    "{%- for message in messages -%}"
    "{%- if message['role'] == 'system' -%}{{- raise_exception('System role not supported') -}}{%- endif -%}"
    "{{- '<start_of_turn>' + message['role'] + '\\n' + message['content'] + '<end_of_turn>\\n' -}}"
    "{%- endfor -%}{%- if add_generation_prompt -%}{{- '<start_of_turn>model\\n' -}}{%- endif -%}"
)

GENERATION_TAG = (
    "{%- for message in messages -%}"
    "{%- if message.role == 'assistant' -%}{{- '<|im_start|>assistant\\n' -}}"
    "{% generation %}{{- message.content + '<|im_end|>\\n' -}}{% endgeneration %}"
    "{%- else -%}{{- '<|im_start|>' + message.role + '\\n' + message.content + '<|im_end|>\\n' -}}{%- endif -%}"
    "{%- endfor -%}{%- if add_generation_prompt -%}{{- '<|im_start|>assistant\\n' -}}{%- endif -%}"
)

R1_STYLE = (
    "{%- for message in messages -%}{{- '<|User|>' + message['content'] -}}{%- endfor -%}"
    "{%- if add_generation_prompt -%}{{- '<|Assistant|><think>\\n' -}}{%- endif -%}"
)


def _tpl(source):
    return CT.for_model(None, {"tokenizer.chat_template": source})


def test_gemma4_is_prompted_in_its_own_format_with_thinking_switched_by_its_template():
    t = _tpl(GEMMA4)
    assert t.reasoning == ("<|channel>thought", "<channel|>")
    assert t.turn_end == "<turn|>" and t.thinking_switch
    off = CT.render_prompt(t, "You are ELI.", "Morning", think=False)
    assert off == "<|turn>system\nYou are ELI.<turn|>\n<|turn>user\nMorning<turn|>\n<|turn>model\n"
    on = CT.render_prompt(t, "You are ELI.", "Morning", think=True)
    assert on.startswith("<|turn>system\n<|think|>\nYou are ELI.")
    assert "<start_of_turn>" not in off + on


def test_qwen3_reasoning_markers_come_from_its_template():
    t = _tpl(QWEN3)
    assert t.reasoning == ("<think>", "</think>")
    assert t.turn_end == "<|im_end|>"
    assert CT.render_prompt(t, "S", "hi", think=False).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert CT.render_prompt(t, "S", "hi", think=True).endswith("<|im_start|>assistant\n")


def test_a_template_that_refuses_a_system_turn_gets_it_inside_the_user_turn():
    t = _tpl(NO_SYSTEM)
    assert t.folds_system
    out = CT.render_prompt(t, "You are ELI.", "hey", think=None)
    assert out == "<start_of_turn>user\nYou are ELI.\n\nhey<end_of_turn>\n<start_of_turn>model\n"


def test_the_generation_block_tag_renders_its_body():
    t = _tpl(GENERATION_TAG)
    assert t is not None and t.turn_end == "<|im_end|>"
    assert CT.render_prompt(t, "S", "hi", think=None).endswith("<|im_start|>assistant\n")


def test_reasoning_a_template_opens_itself_is_closed_when_not_wanted():
    t = _tpl(R1_STYLE)
    assert not t.thinking_switch
    assert CT.render_prompt(t, "", "hi", think=False).endswith("<|Assistant|><think>\n\n</think>\n\n")
    assert CT.render_prompt(t, "", "hi", think=True).endswith("<|Assistant|><think>\n")


def test_bos_is_left_to_llama_cpp_when_it_adds_it_itself():
    t = CT.Template(source="{{- bos_token -}}{{- messages[0]['content'] -}}", bos="<bos>", eos="",
                    strip_bos=True, thinking_switch=False, folds_system=False, reasoning=None, turn_end="")
    assert CT.render_prompt(t, "", "hi", think=None) == "hi"


def test_a_file_without_a_template_uses_the_family_formats():
    assert CT.for_model(None, {}) is None
    assert CT.for_model(None, {"tokenizer.chat_template": "{% if %}"}) is None


@pytest.fixture
def gemma_loaded():
    with patch.object(GI, "_gguf_model_metadata", return_value={"tokenizer.chat_template": GEMMA4,
                                                                "general.architecture": "gemma4"}):
        yield


def test_gguf_inference_prompts_gemma4_in_its_own_format(gemma_loaded, monkeypatch):
    monkeypatch.setenv("ELI_MODEL_THINK", "1")
    out = GI._prompt_for_call("You are ELI.", "Morning", structured=False, max_tokens=4096)
    assert out.startswith("<|turn>system\n<|think|>")
    quick = GI._prompt_for_call("You are ELI.", "Morning", structured=True, max_tokens=4096)
    assert "<|think|>" not in quick and quick.endswith("<|turn>model\n")
    assert "<turn|>" in CT.stop_markers()


def test_gemma4_reasoning_never_reaches_the_reply(gemma_loaded):
    GI._format_prompt("S", "hi")
    assert GI._strip_think_text("<|channel>thought\nPlan: greet.\n<channel|>Morning.") == "Morning."
    assert GI._strip_think_text("Plan: be brisk.\nDrafting...<channel|>Morning.") == "Morning."
    streamed = "".join(c["response"] for c in GI._strip_think_stream(
        [{"response": "<|channel>"}, {"response": "thought\nPlan"}, {"response": "\n<channel|>Morn"},
         {"response": "ing."}]))
    assert streamed == "Morning."
