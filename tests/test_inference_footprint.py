"""Inference RAM routing and footprint reporting."""
from __future__ import annotations

from eli.runtime.inference_footprint import (
    estimate_inference_ram_mb,
    format_inference_footprint_report,
    is_inference_ram_question,
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


def test_estimate_inference_ram_includes_weights_and_kv():
    snap = {
        "model_path": "/tmp/fake.gguf",
        "model_name": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "model_size_gb": 1.8,
        "n_ctx": 4092,
        "n_batch": 32,
        "n_gpu_layers": 0,
        "load_mode": "CPU",
        "cache_type_k": "q4_0",
        "cache_type_v": "q4_0",
    }
    est = estimate_inference_ram_mb(snap)
    assert est["weights_ram_mb"] > 1500
    assert est["kv_cache_mb"] > 100
    assert est["estimated_total_mb"] > est["weights_ram_mb"]


def test_format_report_distinguishes_inference_from_sqlite():
    text = format_inference_footprint_report(
        question="hey pal, how much ram are you utilising instead of a gpu?"
    )
    low = text.lower()
    assert "sqlite" in low
    assert "inference ram" in low or "inference" in low
    assert "hey" in low
