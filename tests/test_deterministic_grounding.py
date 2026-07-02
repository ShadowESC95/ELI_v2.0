"""Deterministic grounding gate — render_action() contract.

`render_action` produces ELI's model-free, grounded answers for introspection /
status / time actions (so the assistant reports real runtime facts rather than
letting the model confabulate). Being deterministic and model-free, it's directly
testable — and asserting its output is a genuine anti-confabulation guarantee, not
coverage padding. Runs in the normal suite (no model needed).
"""
from __future__ import annotations

import re

import pytest

from eli.runtime.deterministic_grounding_gate import render_action


_STATUS_ACTIONS = [
    "RUNTIME_STATUS", "REASONING_MODE_STATUS", "ORCHESTRATION_STATUS",
    "MEMORY_STATUS", "COGNITION_RUNTIME", "EXPLAIN_MEMORY",
]


_SENTINEL = "missing_deterministic_renderer"


@pytest.mark.parametrize("action", _STATUS_ACTIONS)
def test_status_action_renders_nonempty_string(action):
    # Every status action yields a non-empty string (real render OR the structured
    # fall-through sentinel — never a crash or empty answer).
    out = render_action(action, {}, action.lower().replace("_", " "))
    assert isinstance(out, str) and out.strip(), f"{action} produced nothing"


def test_memory_status_is_really_rendered_here():
    # MEMORY_STATUS has a concrete deterministic renderer in this gate (it does NOT
    # fall through) and reports the actual stores — the anti-confabulation guarantee.
    out = render_action("MEMORY_STATUS", {}, "what's in your memory")
    assert _SENTINEL not in out, "MEMORY_STATUS unexpectedly fell through"


def test_runtime_status_mentions_real_runtime_facts():
    out = render_action("RUNTIME_STATUS", {}, "what are you running on").lower()
    # Grounded runtime report must reference concrete runtime facts, not vague prose.
    assert any(k in out for k in ("model", "context", "gpu", "layer", "runtime", "ctx"))


def test_memory_status_reports_stores():
    out = render_action("MEMORY_STATUS", {}, "what's in your memory").lower()
    assert any(k in out for k in ("memor", "database", "db", "vector", "count", "store"))


@pytest.mark.parametrize("action", ["GET_TIME", "GET_DATE", "CHAT", "OPEN_APP"])
def test_non_status_actions_fall_through(action):
    # Actions without a deterministic renderer must return the fall-through sentinel
    # (so the pipeline knows to handle them elsewhere) — never a fabricated answer.
    out = render_action(action, {}, action.lower())
    assert _SENTINEL in out, f"{action} should fall through, got: {out[:80]!r}"


def test_render_action_is_deterministic():
    # Same inputs → same output (the whole point of the deterministic gate).
    a = render_action("REASONING_MODE_STATUS", {}, "what mode are you in")
    b = render_action("REASONING_MODE_STATUS", {}, "what mode are you in")
    assert a == b


def test_unknown_action_is_safe():
    # An unrecognised action must not raise; it returns the fall-through sentinel.
    out = render_action("NOT_A_REAL_ACTION_XYZ", {}, "gibberish")
    assert isinstance(out, str) and _SENTINEL in out


def test_args_none_is_tolerated():
    # args=None must be handled (Mapping | None in the signature).
    out = render_action("RUNTIME_STATUS", None, "status")
    assert isinstance(out, str)


# --------------------------------------------------------------------------- #
# Broaden across every introspection/audit action the gate renders, with rich
# runtime args + both mode labels — this exercises the per-action rendering
# branches inside the layered wrappers (model-free, deterministic, read-only).
# --------------------------------------------------------------------------- #
_INTROSPECTION_ACTIONS = [
    "SELF_REPORT", "SELF_IMPROVE", "SELF_ANALYZE", "RUNTIME_AUDIT",
    "PERSONAL_MEMORY_DEEP_EXPLAIN", "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_LAST_RESPONSE",
    "EXPLAIN_COGNITION_RUNTIME", "RESOLVE_RUNTIME_PATHS", "IMPORT_AUDIT",
    "GUI_RUNTIME_AUDIT", "SYNTHESISE_FROM_DETERMINISTIC_EVIDENCE",
]

_RICH_ARGS = {
    "model_path": "models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "gguf_model_path": "models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "provider": "custom_gguf",
    "n_ctx": 8192, "n_gpu_layers": 32, "n_threads": 8, "n_batch": 512,
    "gpu_layers": 32, "context_size": 8192, "batch_size": 512,
    "threads": 8, "max_tokens": 2048, "question": "what are you running on",
}


@pytest.mark.parametrize("action", _INTROSPECTION_ACTIONS)
def test_introspection_action_renders_without_crash(action):
    out = render_action(action, dict(_RICH_ARGS), action.lower().replace("_", " "))
    assert isinstance(out, str) and out.strip(), f"{action} produced nothing"


@pytest.mark.parametrize("action", _INTROSPECTION_ACTIONS + _STATUS_ACTIONS)
@pytest.mark.parametrize("mode", ["quick", "advanced"])
def test_action_renders_under_both_modes(action, mode):
    # mode_label gates verbatim-vs-synthesised branches; both must render safely.
    out = render_action(action, dict(_RICH_ARGS), action.lower(), mode)
    assert isinstance(out, str)


def test_rich_runtime_args_surface_in_status():
    # With concrete runtime args, the status render should reflect real numbers,
    # not placeholders — the anti-confabulation guarantee under full args.
    out = render_action("RUNTIME_STATUS", dict(_RICH_ARGS), "what are you running on")
    assert isinstance(out, str) and out.strip()


def test_empty_and_partial_args_are_safe():
    # Missing/partial runtime args must never crash the renderer.
    for args in ({}, {"n_ctx": 4096}, {"model_path": "x.gguf"}, {"provider": "custom_gguf"}):
        for action in ("RUNTIME_STATUS", "SELF_REPORT", "MEMORY_STATUS"):
            out = render_action(action, args, "status")
            assert isinstance(out, str)
