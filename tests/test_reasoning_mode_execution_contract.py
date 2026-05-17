from __future__ import annotations

import threading

import pytest

from eli.cognition.reasoning_modes import (
    build_mode_execution_contract,
    mode_instruction_list,
    mode_task_pipeline,
)
from eli.kernel.engine import CognitiveEngine


MODES = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]


@pytest.mark.parametrize("mode", MODES)
def test_mode_contract_has_instruction_stack_and_tasks(mode):
    contract = build_mode_execution_contract(
        mode,
        profile={"max_tokens": 1200, "temperature": 0.7, "top_p": 0.9},
        runtime_snapshot={"n_ctx": 16384, "n_batch": 384, "n_gpu_layers": 12, "n_threads": 8},
        query_text="Explain this architecture in depth with concrete checks.",
        memory_context="",
    )

    assert mode_instruction_list(mode)
    assert mode_task_pipeline(mode)
    assert contract["instructions"] == mode_instruction_list(mode)
    assert contract["tasks"] == mode_task_pipeline(mode)
    assert len(contract["instructions"]) >= 3
    assert len(contract["tasks"]) >= 3


def test_mode_contract_pressure_reduces_batch_and_gpu_layers():
    contract = build_mode_execution_contract(
        "tree_of_thoughts",
        profile={"max_tokens_develop": 1600, "temperature": 0.4, "top_p": 0.85},
        runtime_snapshot={"n_ctx": 8192, "n_batch": 512, "n_gpu_layers": 24, "n_threads": 10},
        query_text="Analyse every subsystem and produce a complete end-to-end answer.",
        memory_context="x" * 28000,  # force high prompt pressure
    )
    runtime = contract["runtime"]

    assert runtime["prompt_pressure"] >= 0.78
    assert runtime["target_n_batch"] <= 256
    assert runtime["target_n_gpu_layers"] <= 12
    assert runtime["reload_recommended"] is True


def test_mode_contract_low_pressure_keeps_runtime_targets_stable():
    contract = build_mode_execution_contract(
        "quick",
        profile={"max_tokens": 768, "temperature": 0.7, "top_p": 0.9},
        runtime_snapshot={"n_ctx": 24576, "n_batch": 384, "n_gpu_layers": 18, "n_threads": 12},
        query_text="What time is it?",
        memory_context="",
    )
    runtime = contract["runtime"]

    assert runtime["prompt_pressure"] < 0.78
    assert runtime["target_n_batch"] == runtime["n_batch"]
    assert runtime["target_n_gpu_layers"] == runtime["n_gpu_layers"]


@pytest.mark.parametrize(
    "mode,min_tokens",
    [
        ("quick", 256),
        ("chain_of_thought", 768),
        ("self_consistency", 896),
        ("tree_of_thoughts", 1024),
        ("constitutional_ai", 900),
    ],
)
def test_mode_contract_generation_overrides_have_mode_floor(mode, min_tokens):
    contract = build_mode_execution_contract(
        mode,
        profile={"max_tokens": 1400, "temperature": 0.7, "top_p": 0.9},
        runtime_snapshot={"n_ctx": 32768, "n_batch": 512, "n_gpu_layers": 28, "n_threads": 16},
        query_text="Provide a thorough explanation with concrete implementation details.",
        memory_context="",
    )

    overrides = contract["generation_overrides"]
    assert int(overrides["max_tokens"]) >= min_tokens
    assert 0.0 < float(overrides["temperature"]) <= 0.7


def test_nonquick_mode_contract_can_use_configured_4096_budget():
    prompt = "Provide a full in-depth comprehensive audit with concrete implementation details."
    runtime = {"n_ctx": 24576, "n_batch": 256, "n_gpu_layers": 8, "n_threads": 10}
    expected_profiles = {
        "chain_of_thought": {"max_tokens": 4096, "temperature": 0.5, "top_p": 0.85},
        "self_consistency": {"max_tokens_per_sample": 2048, "max_tokens_final": 4096, "temperature": 0.4, "top_p": 0.85},
        "tree_of_thoughts": {"max_tokens_develop": 4096, "temperature": 0.4, "top_p": 0.85},
        "constitutional_ai": {"max_tokens_revise": 4096, "max_tokens": 4096, "temperature": 0.35, "top_p": 0.85},
    }

    for mode, profile in expected_profiles.items():
        contract = build_mode_execution_contract(
            mode,
            profile=profile,
            runtime_snapshot=runtime,
            query_text=prompt,
            memory_context="",
        )
        max_tokens = int(contract["generation_overrides"]["max_tokens"])
        assert 3000 <= max_tokens <= 4096


def test_engine_self_consistency_profile_carries_final_budget(monkeypatch):
    from eli.core import runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "load_settings",
        lambda: {
            "max_tokens": 4096,
            "mode_presets": {
                "self_consistency": {
                    "samples": 3,
                    "max_tokens": 2252,
                    "temperature": 0.7,
                    "top_p": 0.85,
                }
            },
            "hardware_profile": {
                "mode_presets": {
                    "self_consistency": {
                        "max_tokens_per_sample": 2048,
                        "max_tokens_final": 4096,
                    }
                }
            },
        },
    )
    eng = CognitiveEngine.__new__(CognitiveEngine)
    profile = CognitiveEngine._mode_profile(eng, "self_consistency")

    assert profile["max_tokens_per_sample"] == 2048
    assert profile["max_tokens_final"] == 4096


def test_runtime_orchestrator_plan_includes_mode_contract_matrix():
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._intent_requires_grounding = lambda intent, user_input: False
    eng._mode_profile = lambda mode: {"max_tokens": 1400, "temperature": 0.5, "top_p": 0.9}
    eng._live_runtime_snapshot = lambda: {"n_ctx": 16384, "n_batch": 384, "n_gpu_layers": 12, "n_threads": 8}

    plan = CognitiveEngine._build_runtime_orchestrator_plan(
        eng,
        user_input="Explain the full pipeline with concrete stages.",
        action="CHAT",
        reasoning_mode="tree_of_thoughts",
        query_class="DEEP_TECHNICAL",
        bus_result=None,
    )

    assert plan["reasoning_mode"] == "tree_of_thoughts"
    assert isinstance(plan.get("mode_instructions"), list) and plan["mode_instructions"]
    assert isinstance(plan.get("mode_tasks"), list) and plan["mode_tasks"]
    assert isinstance(plan.get("mode_runtime_targets"), dict)
    assert isinstance(plan.get("mode_generation_overrides"), dict)
    assert isinstance(plan.get("stage_matrix"), list) and plan["stage_matrix"]
    assert plan.get("final_stage_guarantee") == "stage_12_learning_and_state_commit_must_run"
    stage12 = [s for s in plan["stage_matrix"] if s.get("stage") == 12]
    assert stage12 and stage12[0].get("required") is True


def test_runtime_adaptation_reloads_model_when_contract_requests(monkeypatch):
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._gguf_available = True
    eng._gguf_lock = threading.RLock()
    eng._last_runtime_retune_ts = 0.0
    eng._ctx = 16384
    eng._gpu_layers = 16
    eng._live_runtime_snapshot = lambda: {"n_ctx": 16384, "batch": 512, "gpu_layers": 16}

    called = {}

    class _DummyGGUF:
        def load_model(self, **kwargs):
            called.update(kwargs)
            return object()

    monkeypatch.setattr("eli.kernel.engine.gguf_inference", _DummyGGUF())

    contract = {
        "mode": "tree_of_thoughts",
        "runtime": {
            "reload_recommended": True,
            "target_n_ctx": 16384,
            "target_n_batch": 256,
            "target_n_gpu_layers": 8,
        },
    }
    CognitiveEngine._maybe_apply_mode_runtime_adaptation(eng, "tree_of_thoughts", contract)

    assert called.get("force_reload") is True
    assert called.get("n_ctx") == 16384
    assert called.get("n_batch") == 256
    assert called.get("n_gpu_layers") == 8


def test_runtime_adaptation_skips_quick_mode(monkeypatch):
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._gguf_available = True
    eng._gguf_lock = threading.RLock()
    eng._last_runtime_retune_ts = 0.0
    eng._ctx = 16384
    eng._gpu_layers = 16
    eng._live_runtime_snapshot = lambda: {"n_ctx": 16384, "batch": 512, "gpu_layers": 16}

    class _DummyGGUF:
        def load_model(self, **kwargs):
            raise AssertionError("quick mode must not trigger runtime reload")

    monkeypatch.setattr("eli.kernel.engine.gguf_inference", _DummyGGUF())

    contract = {
        "mode": "quick",
        "runtime": {
            "reload_recommended": True,
            "target_n_ctx": 16384,
            "target_n_batch": 128,
            "target_n_gpu_layers": 0,
        },
    }
    CognitiveEngine._maybe_apply_mode_runtime_adaptation(eng, "quick", contract)
