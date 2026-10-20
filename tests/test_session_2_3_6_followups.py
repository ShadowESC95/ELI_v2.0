"""Three faults from a live 2.3.6 session.

1. ELI offered "Want to know how it compares to other setups?", the user said
   "yeah, why not", and ELI answered with no idea what it had offered.
2. Every session logged `summary written (llm=False)` — the LLM hand-off note
   the feature exists to produce never ran, at any depth.
3. The GPU report said "1493 MiB free: headroom available for a larger context
   or batch" while that memory was already committed to generation.
"""
import inspect
import pathlib
import re

import pytest


# ── 1. an acceptance keeps the thread ─────────────────────────────────────
@pytest.mark.parametrize("text", [
    "yeah, why not", "yes", "yep", "sure", "go on", "go ahead", "do it",
    "ok then", "please do", "carry on", "sounds good", "tell me",
])
def test_accepting_an_offer_pulls_the_previous_turn(text):
    from eli.cognition.agent_bus import _eli_memory_should_run
    assert _eli_memory_should_run(text, "CHAT") is True


@pytest.mark.parametrize("text", ["here i will", "hey", "hmm", "what is a tensor"])
def test_real_fragments_still_skip_recall(text):
    """The rule exists so "tiny fragments after wake" don't drag in memory."""
    from eli.cognition.agent_bus import _eli_memory_should_run
    assert _eli_memory_should_run(text, "CHAT") is False


# ── 2. the end-of-session summary can actually run ────────────────────────
def test_shutdown_only_blocks_background_generation():
    """engine shutdown signals abort at step 2 and writes the LLM session
    summary at step 3.5. An unconditional shutdown short-circuit in the broker
    meant that summary could never generate — llm=False on every session."""
    from eli.cognition import inference_broker
    src = inspect.getsource(inference_broker.InferenceBroker.infer)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "background and self._gguf.is_shutting_down()" in code, (
        "shutdown still blocks foreground generation, killing the session summary"
    )


def test_gguf_ready_calls_is_loaded_rather_than_truth_testing_it():
    """`bool(module.is_loaded)` is True for the FUNCTION OBJECT whether or not a
    model is resident — the same defect as int(<bound method>) in the runtime
    snapshot."""
    from eli.cognition import inference_broker
    src = inspect.getsource(inference_broker.InferenceBroker)
    i = src.index("def gguf_ready")
    body = src[i:i + 700]
    assert "callable(_probe)" in body and "_probe()" in body
    assert "return bool(self._gguf.is_loaded)" not in body


def test_the_summary_still_refuses_to_cold_load():
    """It must summarise with an already-resident model, never load one just to
    write a note at shutdown."""
    from eli.runtime import profile_extractor
    src = inspect.getsource(profile_extractor._llm_summarise_session)
    assert "is_loaded" in src and "COLD-LOAD" in src.upper() or "cold-load" in src.lower()


# ── 3. the GPU report must not advertise committed memory ─────────────────
def test_free_vram_is_reported_net_of_what_llamacpp_still_takes():
    """What reads free is spare except what llama.cpp was measured to add as it works (its compute
    buffers are allocated with the model); the old fixed formula (graph reserve, 350 MB overhead and
    a 700 MB reserve) is gone."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "eli" / "execution"
           / "executor_enhanced.py").read_text(encoding="utf-8")
    i = src.index("MiB VRAM free")
    window = src[max(0, i - 2000):i + 1500]
    assert "vram_reserve_mb" in window
    assert "_compute_graph_reserve_mb" not in window and "_CUDA_OVERHEAD_MB" not in window
