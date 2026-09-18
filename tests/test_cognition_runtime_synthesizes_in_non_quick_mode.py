"""Field report (2026-09-18): a Normal-mode question mentioning "gpu layers" /
"batch size" / "n_ctx" routes to EXPLAIN_COGNITION_RUNTIME with
diagnostic_focus in {inference_ram, latency_timing, inference_runtime}
(router_enhanced.py). engine.py had a SECOND, narrower verbatim-bypass check
(`_inference_ram_verbatim`) that forced the raw structured diagnostic dump
as the final answer in EVERY mode for exactly this diagnostic_focus subset --
even though EXPLAIN_COGNITION_RUNTIME's general case was already fixed on
2026-06-08 to synthesise in non-Quick modes ("gather-then-summarise, never a
raw dump", moved out of _verbatim_always_actions at the user's request).

User, live, Normal mode, asking about ctx/gpu_layers/batch:
    ELI > Provider: gguf
          Model: Qwen3.6-35B-A3B-Q4_K_M.gguf
          Effective — ctx: 12200, gpu_layers: 9, threads: 10, batch: 128
          GPU: NVIDIA GeForce RTX 2060 SUPER
    user> no, where the fuck is my llm synthesis, you are not in quick mode!

This is a regression guard: the narrower bypass must not come back, in this
form or a new one, for this action.
"""
from pathlib import Path

ENGINE_PY = Path(__file__).resolve().parents[1] / "eli" / "kernel" / "engine.py"


def test_no_diagnostic_focus_specific_verbatim_bypass():
    text = ENGINE_PY.read_text(encoding="utf-8")
    assert "_inference_ram_verbatim" not in text, (
        "the diagnostic_focus-specific verbatim-always bypass for "
        "EXPLAIN_COGNITION_RUNTIME is back -- it forces the raw diagnostic "
        "dump as the final answer in every mode, not just quick, for "
        "questions about gpu_layers/batch/n_ctx specifically"
    )


def test_bypass_persona_gate_has_no_focus_gated_shortcut():
    """The _bypass_persona computation must gate EXPLAIN_COGNITION_RUNTIME the
    same way as every other _deterministic_direct_payload_actions member:
    verbatim only when _direct_mode == "quick"."""
    text = ENGINE_PY.read_text(encoding="utf-8")
    start = text.index("_bypass_persona = bool(")
    end = text.index("\n                        )", start)
    block = text[start:end]
    assert "diagnostic_focus" not in block
    assert "inference_ram" not in block
    assert "latency_timing" not in block
