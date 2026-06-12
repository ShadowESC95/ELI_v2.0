"""Regression: turn-label stop sequences must not strangle a thinking model
mid-<think>.

Root bug (observed on a short, ambiguous "yes please"): the prompt renders chat
history as "[003] [ts] User: …" (engine.py:4412), and "User:" was a hard stop
sequence passed to llama.cpp on EVERY call. A reasoning model (Qwen3 / R1 / QwQ)
reconstructs the conversation inside its private <think> block; the moment it
emitted the token "User:" there, generation halted — before </think>, before any
answer — yielding an empty reply.

Fix: withhold the natural-language role-label stops ("User:" / "Assistant:") for
thinking models, while keeping the real chat-template terminators (<|im_end|> /
<|eot_id|>). Non-thinking models keep the label guard.
"""

import pytest

import eli.cognition.gguf_inference as g


def _capture_stop_list(monkeypatch, *, thinking: bool, model_path: str):
    captured = {}

    monkeypatch.setattr(g, "load_model", lambda *a, **k: object())
    monkeypatch.setattr(g, "_ctx_max_tokens", lambda *a, **k: 4096)
    monkeypatch.setattr(g, "_estimate_prompt_tokens", lambda *a, **k: 100)
    monkeypatch.setattr(g, "get_model_path", lambda: model_path)
    monkeypatch.setattr(g, "_is_thinking_model", lambda *a, **k: thinking)

    def fake_invoke(llm, full_prompt, *, stop, stream, **kw):
        captured["stop"] = list(stop)
        if stream:
            return iter([{"choices": [{"text": "hi"}]}])
        return {"choices": [{"text": "hi"}], "usage": {"completion_tokens": 1}}

    monkeypatch.setattr(g, "_safe_invoke_llm", fake_invoke)

    list(g._generate_legacy("hello", system="sys", max_tokens=2048, stream=False))
    return captured["stop"]


def test_thinking_model_drops_label_stops(monkeypatch):
    stop = _capture_stop_list(
        monkeypatch, thinking=True,
        model_path="models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    )
    # No natural-language turn labels — they'd fire inside <think>.
    assert "User:" not in stop
    assert "USER:" not in stop
    assert "Assistant:" not in stop
    assert "\nUser:" not in stop
    # The real terminator survives, so the turn still ends correctly.
    assert "<|im_end|>" in stop


def test_non_thinking_model_keeps_label_stops(monkeypatch):
    stop = _capture_stop_list(
        monkeypatch, thinking=False,
        model_path="models/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    )
    # Base / non-reasoning models keep the crude run-on guard.
    assert "User:" in stop
    assert "Assistant:" in stop
    assert "<|im_end|>" in stop


def test_streaming_path_uses_same_stop_policy(monkeypatch):
    # The stream branch shares the stop list — verify a thinking model is
    # protected there too (the live bug surfaced first on the streaming path).
    captured = {}
    monkeypatch.setattr(g, "load_model", lambda *a, **k: object())
    monkeypatch.setattr(g, "_ctx_max_tokens", lambda *a, **k: 4096)
    monkeypatch.setattr(g, "_estimate_prompt_tokens", lambda *a, **k: 100)
    monkeypatch.setattr(g, "get_model_path", lambda: "models/Qwen3.6-35B-A3B.gguf")
    monkeypatch.setattr(g, "_is_thinking_model", lambda *a, **k: True)

    def fake_invoke(llm, full_prompt, *, stop, stream, **kw):
        captured["stop"] = list(stop)
        return iter([{"choices": [{"text": "hi"}]}])

    monkeypatch.setattr(g, "_safe_invoke_llm", fake_invoke)
    list(g._generate_legacy("hello", system="sys", max_tokens=2048, stream=True))
    assert "User:" not in captured["stop"]
    assert "<|im_end|>" in captured["stop"]
