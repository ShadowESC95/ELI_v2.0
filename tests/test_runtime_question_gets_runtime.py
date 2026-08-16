"""Locks on "what is your context window?" being answered with the number.

Live at 2.2.0, running a 30B model with 8 of 99 layers on GPU:

    user> What is your current context window? You should have a reasonably
          high context window, no?
    ELI > Cognition runtime: /…/engine.py
          Memory module: /…/memory.py
          - gguf: lines [67, 69, 1712, 3775, …]      <- 60 grep line numbers
          - active_db: capability_proposals(0), conversation_turns(672), …
    user> What is your current context window?
    ELI > The provided evidence does not specify the current context window size.

It did not — and n_ctx was 12192, written to runtime_snapshot.json at startup
and printed six times in the same log. EXPLAIN_COGNITION_RUNTIME, the action
named for the runtime, described the ARCHITECTURE: module paths, grep hits and
SQLite table counts, with no field anywhere for the inference parameters.

The router had already worked it out — it routed with
``diagnostic_focus: "inference_runtime"`` — and both evidence producers ignored
that argument and returned the same text for every question.

Requested and effective are both reported because their divergence is usually
the real answer: that session asked for 99 GPU layers and got 8, which is why
single replies took 136 seconds.
"""
import json

import pytest

from eli.runtime import deterministic_grounding_gate as G

SNAPSHOT = {
    "provider": "gguf",
    "model_name": "NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q4_K_XL.gguf",
    "n_ctx": 12192, "n_gpu_layers": 8, "n_batch": 128, "load_mode": "GPU",
    "requested": {"n_ctx": 12192, "n_gpu_layers": 99, "n_threads": 10, "n_batch": 128},
    "effective": {"n_ctx": 12192, "n_gpu_layers": 8, "n_threads": 10, "n_batch": 128},
}


@pytest.fixture
def live_snapshot(monkeypatch):
    monkeypatch.setattr(G, "_runtime_snapshot", lambda: dict(SNAPSHOT))


# ── the question must be answerable from the evidence ───────────────────────
def test_the_context_window_is_in_the_evidence(live_snapshot):
    assert "12192" in G._inference_runtime_lines()


def test_the_model_is_named(live_snapshot):
    assert "Nemotron" in G._inference_runtime_lines()


def test_requested_and_effective_gpu_layers_are_both_shown(live_snapshot):
    """8 of a requested 99 is the reason a reply took over two minutes. Showing
    only the effective number hides the cause; only the requested one lies."""
    out = G._inference_runtime_lines()
    assert "8" in out and "99" in out


def test_a_divergence_is_explained_not_just_printed(live_snapshot):
    out = G._inference_runtime_lines()
    assert "CPU" in out, "the reason the missing layers cost time is not stated"


def test_no_divergence_means_no_noise(monkeypatch):
    """When requested == effective there is nothing to explain."""
    snap = dict(SNAPSHOT)
    snap["requested"] = dict(snap["effective"])
    monkeypatch.setattr(G, "_runtime_snapshot", lambda: snap)
    assert "requested" not in G._inference_runtime_lines()


# ── the focus the router already computed must be honoured ──────────────────
def test_an_inference_question_leads_with_the_numbers(live_snapshot):
    out = G._eli_cognition_pipeline_v2("inference_runtime")
    assert out.index("12192") < out.index("Cognition pipeline"), \
        "still leading with the architecture description"


def test_the_architecture_description_is_not_lost(live_snapshot):
    """Someone asking how ELI works still needs the pipeline text."""
    out = G._eli_cognition_pipeline_v2("inference_runtime")
    assert "Cognition pipeline" in out
    assert "Router" in out


def test_the_runtime_is_present_even_without_a_focus(live_snapshot):
    """A report named for the runtime should carry it regardless."""
    assert "12192" in G._eli_cognition_pipeline_v2("")


# ── the executor's copy of the report, which is what the user saw ──────────
def test_the_executor_report_also_leads_with_the_runtime(live_snapshot):
    from eli.execution.executor_enhanced import _format_cognition_runtime
    out = _format_cognition_runtime({
        "ok": True, "path": "engine.py", "memory_path": "memory.py",
        "router_path": "router.py", "executor_path": "executor.py", "checks": {},
    })
    assert "12192" in out
    assert out.index("12192") < out.index("Cognition runtime:")


# ── failure modes ──────────────────────────────────────────────────────────
def test_a_missing_snapshot_does_not_break_the_report(monkeypatch):
    monkeypatch.setattr(G, "_runtime_snapshot", lambda: {})
    out = G._eli_cognition_pipeline_v2("inference_runtime")
    assert "Cognition pipeline" in out, "lost the whole report over a missing snapshot"
    assert "unknown" in out


def test_a_raising_snapshot_does_not_break_the_report(monkeypatch):
    def boom():
        raise RuntimeError("snapshot unreadable")
    monkeypatch.setattr(G, "_runtime_snapshot", boom)
    out = G._eli_cognition_pipeline_v2("inference_runtime")
    assert "Cognition pipeline" in out


def test_the_pipeline_text_is_a_constant_not_rebuilt_per_call():
    """It is static prose; only the runtime block is live."""
    assert isinstance(G._COGNITION_PIPELINE_TEXT, str)
    assert "Cognition pipeline" in G._COGNITION_PIPELINE_TEXT
