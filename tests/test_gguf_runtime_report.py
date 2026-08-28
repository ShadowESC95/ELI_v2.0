"""GGUF runtime report and preflight — portable, model-agnostic."""
from pathlib import Path

import pytest

from eli.cognition import model_load_diagnostics as mld
from eli.runtime import gguf_runtime_report as grr


def test_architecture_requires_modern_runtime_nemotron():
    assert mld.architecture_requires_modern_runtime("nemotron_h_moe") is True


def test_architecture_requires_modern_runtime_llama_legacy():
    assert mld.architecture_requires_modern_runtime("llama") is False
    assert mld.architecture_requires_modern_runtime("llama3") is False


def test_preflight_blocks_nemotron_on_old_runtime(monkeypatch, tmp_path):
    p = tmp_path / "hybrid.gguf"
    arch = b"nemotron_h_moe"
    key = b"general.architecture"
    with open(p, "wb") as f:
        f.write(b"GGUF")
        f.write(__import__("struct").pack("<I", 3))
        f.write(__import__("struct").pack("<Q", 0))
        f.write(__import__("struct").pack("<Q", 1))
        f.write(__import__("struct").pack("<Q", len(key)))
        f.write(key)
        f.write(__import__("struct").pack("<I", 8))
        f.write(__import__("struct").pack("<Q", len(arch)))
        f.write(arch)
    monkeypatch.setattr(mld, "installed_llama_version_tuple", lambda: (0, 3, 16))
    msg = mld.preflight_gguf_model(p)
    assert msg is not None
    assert "nemotron_h_moe" in msg
    assert "llama-cpp-python" in msg


def test_preflight_passes_on_modern_runtime(monkeypatch, tmp_path):
    p = tmp_path / "hybrid.gguf"
    arch = b"nemotron_h_moe"
    key = b"general.architecture"
    with open(p, "wb") as f:
        f.write(b"GGUF")
        f.write(__import__("struct").pack("<I", 3))
        f.write(__import__("struct").pack("<Q", 0))
        f.write(__import__("struct").pack("<Q", 1))
        f.write(__import__("struct").pack("<Q", len(key)))
        f.write(key)
        f.write(__import__("struct").pack("<I", 8))
        f.write(__import__("struct").pack("<Q", len(arch)))
        f.write(arch)
    monkeypatch.setattr(mld, "installed_llama_version_tuple", lambda: (0, 3, 35))
    assert mld.preflight_gguf_model(p) is None


def test_failure_log_report_mentions_executor_table(monkeypatch):
    monkeypatch.setattr(grr, "query_executor_failures", lambda limit=50: [])
    txt = grr.format_failure_log_report(limit=5)
    assert "agent.sqlite3" in txt
    assert "failures table" in txt
    assert "empty response after retry" in txt


def test_gguf_diagnostics_report_includes_runtime_version(monkeypatch):
    monkeypatch.setattr(mld, "installed_llama_version", lambda: "0.3.16")
    monkeypatch.setattr(mld, "installed_llama_version_tuple", lambda: (0, 3, 16))
    monkeypatch.setattr(mld, "gpu_pack_is_too_old", lambda: False)
    monkeypatch.setattr(
        "eli.runtime.deterministic_grounding_gate._inference_runtime_lines",
        lambda: "Inference runtime (live):",
    )
    txt = grr.format_gguf_diagnostics_report(question="nemotron")
    assert "llama-cpp-python: 0.3.16" in txt
    assert "unknown model architecture" in txt.lower() or "Common GGUF" in txt
