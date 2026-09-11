"""Inference RAM routing and live footprint reporting."""
from __future__ import annotations

from eli.runtime.inference_footprint import (
    format_inference_footprint_report,
    is_inference_ram_question,
    read_live_inference_memory,
    record_load_memory,
)


def test_is_inference_ram_question_detects_eli_runtime():
    assert is_inference_ram_question(
        "hey pal, how much ram are you utilising instead of a gpu?"
    )
    assert is_inference_ram_question(
        "how much of your RAM are you using to decrease latency?"
    )


def test_is_inference_ram_question_rejects_memory_db():
    assert not is_inference_ram_question("how many memories do you have in sqlite?")
    assert not is_inference_ram_question("what is in your memory database?")


def test_record_load_memory_uses_measured_delta(monkeypatch):
    class _FakeLlama:
        model = object()
        ctx = object()

    monkeypatch.setattr(
        "eli.runtime.inference_footprint._read_llama_live",
        lambda _llm: {"model_bytes": 1800 * 1024 * 1024, "n_ctx_live": 4092},
    )
    monkeypatch.setattr(
        "eli.runtime.inference_footprint._process_memory",
        lambda: {"rss_bytes": 2600 * 1024 * 1024},
    )
    rec = record_load_memory(_FakeLlama(), pre_load_rss_bytes=100 * 1024 * 1024)
    assert rec["load_delta_rss_bytes"] == 2500 * 1024 * 1024
    assert rec["model_bytes"] == 1800 * 1024 * 1024
    assert rec["context_alloc_bytes"] == 700 * 1024 * 1024


def test_read_live_inference_memory_not_loaded():
    live = read_live_inference_memory(llm=None, snap={"loaded": False})
    assert live["inference_active"] is False


def test_format_report_uses_live_language(monkeypatch):
    monkeypatch.setattr(
        "eli.runtime.inference_footprint.refresh_live_inference_memory",
        lambda **_: {
            "loaded": True,
            "inference_active": True,
            "model_name": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
            "model_bytes": 1800 * 1024 * 1024,
            "rss_bytes": 2600 * 1024 * 1024,
            "inference_rss_bytes": 2500 * 1024 * 1024,
            "load_mode": "CPU",
            "n_ctx": 4092,
            "n_ctx_live": 4092,
            "n_batch": 32,
            "n_gpu_layers": 0,
            "measured_at_load": {
                "load_delta_rss_bytes": 2500 * 1024 * 1024,
                "context_alloc_bytes": 700 * 1024 * 1024,
            },
        },
    )
    text = format_inference_footprint_report(
        question="hey pal, how much ram are you utilising instead of a gpu?"
    )
    low = text.lower()
    assert "estimate" not in low
    assert "measured live" in low
    assert "sqlite" in low
    assert "hey" in low
    assert "1800.0 mb" in low
    assert "llama.cpp" in low
