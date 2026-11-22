"""LoRA wiring tests — pipeline stage order, model-agnostic target modules, actions, routing.

Model-free (torch is mocked by conftest). Asserts the pipeline is WIRED and runs the
correct stages in order as a dry-run, never training. The actual fine-tune
(execute=True) is exercised only by the overnight `lora` scheduled task.
"""
from __future__ import annotations

import pytest


# ── model-agnostic target modules ────────────────────────────────────────────
def test_target_modules_honours_explicit_override():
    from eli.learning.lora_trainer import _resolve_target_modules
    assert _resolve_target_modules(object(), {"target_modules": ["qkv_proj"]}) == ["qkv_proj"]


def test_target_modules_falls_back_to_all_linear_when_unknown():
    # with torch mocked / no recognisable Linear leaves → architecture-agnostic default
    from eli.learning.lora_trainer import _resolve_target_modules
    assert _resolve_target_modules(object(), {}) == "all-linear"


def test_target_modules_not_hardcoded_to_phi():
    # the old hardcoded ["qkv_proj"] default must be gone from the train path
    import inspect
    from eli.learning import lora_trainer
    src = inspect.getsource(lora_trainer.run_training)
    assert '["qkv_proj"]' not in src and "_resolve_target_modules(model" in src


# ── pipeline stages in order (dry-run) ───────────────────────────────────────
def test_pipeline_runs_stages_in_order_dry_run():
    from eli.learning.lora_pipeline import run_pipeline
    r = run_pipeline("eli_phi", execute=False)
    assert r["dry_run"] is True and r["executed"] is False
    order = [s["stage"] for s in r["stages"]]
    # preflight first, build_job second, train + eval present
    assert order[:2] == ["preflight", "build_job"]
    assert "train" in order and "eval" in order


def test_pipeline_does_not_train_in_dry_run():
    from eli.learning.lora_pipeline import run_pipeline
    r = run_pipeline("eli_phi", execute=False)
    train = next(s for s in r["stages"] if s["stage"] == "train")
    assert train["detail"].get("skipped") is True


def test_pipeline_bad_target_handled():
    from eli.learning.lora_pipeline import run_pipeline
    r = run_pipeline("not_a_real_target", execute=False)
    assert isinstance(r, dict) and "stages" in r and r["dry_run"] is True


# ── actions ──────────────────────────────────────────────────────────────────
def test_lora_status_action_reports_readiness():
    from eli.execution.executor_enhanced import execute
    r = execute("LORA_STATUS", {})
    assert r["ok"] is True and "readiness" in r["content"].lower()
    assert r.get("evidence_source") == "lora_preflight"


def test_lora_train_action_dry_run_by_default():
    from eli.execution.executor_enhanced import execute
    r = execute("LORA_TRAIN", {"target": "eli_phi"})
    assert "action" in r and r["action"] == "LORA_TRAIN"
    assert (r.get("result") or {}).get("dry_run") is True
    assert (r.get("result") or {}).get("executed") is False


def _pipeline_seen(monkeypatch, ready):
    import eli.learning.lora_pipeline as lp
    import eli.learning.lora_trainer_guard as guard
    import eli.learning.training_preflight as tp
    seen = []
    monkeypatch.setattr(guard, "allowed_targets", lambda: {"eli_phi", "eli_phi_ultra", "garden_model"})
    monkeypatch.setattr(tp, "preflight_all", lambda: {"reports": [
        {"target": t, "can_train": t in ready, "problems": [] if t in ready else ["base model not found"]}
        for t in ("eli_phi", "eli_phi_ultra", "garden_model")]})
    monkeypatch.setattr(lp, "run_pipeline", lambda target, **kw: seen.append((target, kw.get("execute"))) or
                        {"ok": True, "target": target, "dry_run": not kw.get("execute"), "executed": False,
                         "summary": f"dry run for {target}", "stages": []})
    return seen


@pytest.mark.parametrize("said,ready,expect", [
    ("train a lora", {"eli_phi_ultra"}, ["eli_phi_ultra"]),          # the first declared one that is ready
    ("train a lora for garden_model", set(), ["garden_model"]),      # the one named
])
def test_lora_train_from_chat_takes_the_target_the_scheduled_job_would(monkeypatch, said, ready, expect):
    """From chat, LORA_TRAIN always took eli_phi, declared and ready or not."""
    from eli.execution.executor_enhanced import execute
    from eli.execution.router_enhanced import route
    seen = _pipeline_seen(monkeypatch, ready)
    routed = route(said)
    assert routed["action"] == "LORA_TRAIN"
    out = execute("LORA_TRAIN", routed["args"])
    assert [t for t, _ in seen] == expect and all(e is False for _, e in seen), seen   # still a dry run
    assert out["ok"] is True


def test_lora_train_from_chat_says_when_no_target_is_ready(monkeypatch):
    from eli.execution.executor_enhanced import execute
    seen = _pipeline_seen(monkeypatch, set())
    out = execute("LORA_TRAIN", {"text": "train a lora"})
    assert seen == [] and out["ok"] is False and out["error"] == "no_target_ready"
    assert out["response"].startswith("No declared LoRA target is ready to train (")
    assert "garden_model: base model not found" in out["response"]


def test_lora_actions_supported():
    from eli.execution.executor_enhanced import SUPPORTED_ACTIONS
    assert "LORA_STATUS" in SUPPORTED_ACTIONS and "LORA_TRAIN" in SUPPORTED_ACTIONS


# ── routing + scheduling ─────────────────────────────────────────────────────
@pytest.mark.parametrize("phrase,expected", [
    ("lora status", "LORA_STATUS"),
    ("is lora ready", "LORA_STATUS"),
    ("train a lora", "LORA_TRAIN"),
    ("fine-tune yourself", "LORA_TRAIN"),
    ("run lora training", "LORA_TRAIN"),
])
def test_lora_routing(phrase, expected):
    from eli.execution.router_enhanced import route
    assert route(phrase).get("action") == expected


def test_lora_scheduled_kind_and_worker():
    from eli.runtime.scheduled_tasks import infer_kind, _WORKERS
    assert infer_kind("train a lora overnight") == "lora"
    assert "lora" in _WORKERS and callable(_WORKERS["lora"])
