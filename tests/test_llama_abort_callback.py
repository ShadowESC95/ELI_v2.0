"""Shutdown/cancel must register llama_set_abort_callback for prefill abort."""
from pathlib import Path


def test_gguf_inference_installs_abort_callback():
    src = Path("eli/cognition/gguf_inference.py").read_text(encoding="utf-8")
    assert "def _install_llama_abort_callback" in src
    assert "llama_set_abort_callback" in src
    assert "_install_llama_abort_callback(_llm)" in src
