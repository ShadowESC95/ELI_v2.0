"""LoRA training pipeline — the DAG that chains the standalone learning stages.

The individual mechanisms (preflight, dataset, trainer, eval) were correct but
orphaned — nothing ran them in order. This is the explicit, ordered pipeline ELI
(and the GUI / scheduled task) drives:

    preflight → build job (dataset + base validation) → [train] → eval(inspect)

Dry-run by default (execute=False): runs every gate and reports readiness WITHOUT
touching the GPU or writing an adapter — safe to call from chat. Real training only
when execute=True (the overnight `lora` scheduled task / explicit GUI action), and
even then the trainer's own safety contract still applies (reviewed rows only, GGUF
never trained, adapter never overwritten). 100% local; model-agnostic target modules
(see lora_trainer._resolve_target_modules).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _stage(name: str, ok: bool, detail: Any) -> Dict[str, Any]:
    return {"stage": name, "ok": bool(ok), "detail": detail}


def run_pipeline(
    target: str = "eli_phi",
    *,
    execute: bool = False,
    max_steps: int = 1,
    seq_len: int = 384,
    batch_size: int = 1,
    grad_accum: int = 1,
    learning_rate: float = 2e-4,
    device: str = "auto",
    output_dir: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Run the LoRA DAG end to end. Returns {ok, executed, target, stages:[...],
    summary}. Stops at the first stage that makes training impossible (dry-run still
    reports every reachable gate)."""
    stages: List[Dict[str, Any]] = []

    # 1) PREFLIGHT — modules present + base model resolvable + reviewed rows.
    try:
        from eli.learning.training_preflight import preflight_target
        pf = preflight_target(target)
        can = bool(pf.get("can_train"))
        stages.append(_stage("preflight", can, {
            "can_train": can,
            "problems": pf.get("problems", []),
            "missing_modules": pf.get("missing_modules", []),
            "base_model_resolution": (pf.get("base_model_resolution") or {}).get("ok"),
        }))
    except Exception as e:
        stages.append(_stage("preflight", False, {"error": str(e)}))
        return _finish(target, execute, stages)

    # 2) BUILD JOB — validate dataset + base + output (dry-run unless execute).
    try:
        from eli.learning.lora_trainer import build_training_job
        job = build_training_job(
            target, execute=execute, max_steps=max_steps, seq_len=seq_len,
            batch_size=batch_size, grad_accum=grad_accum, learning_rate=learning_rate,
            device=device, output_dir=output_dir, overwrite=overwrite)
        job_ok = bool(job.get("ok")) and not job.get("problems")
        stages.append(_stage("build_job", job_ok, {
            "will_train": job.get("will_train"),
            "problems": job.get("problems", []),
            "dataset_rows": (job.get("dataset") or {}).get("rows"),
            "base_model_path": job.get("base_model_path"),
            "output_dir": job.get("output_dir"),
        }))
    except Exception as e:
        stages.append(_stage("build_job", False, {"error": str(e)}))
        return _finish(target, execute, stages)

    # 3) TRAIN — only when execute=True AND the job passed safety validation.
    executed_training = False
    if execute and job.get("will_train"):
        try:
            from eli.learning.lora_trainer import run_training
            trained = run_training(job)
            res = trained.get("result") or {}
            executed_training = bool(res.get("ok"))
            stages.append(_stage("train", executed_training, {
                "output_dir": res.get("output_dir"),
                "metrics": res.get("metrics"),
                "trainable_parameters": (res.get("trainable_parameters") or {}).get("summary"),
                "skipped": res.get("skipped"),
            }))
        except Exception as e:
            stages.append(_stage("train", False, {"error": str(e)}))
    else:
        stages.append(_stage("train", True, {
            "skipped": True,
            "reason": "dry-run (execute=False)" if not execute else "job failed safety validation",
        }))

    # 4) EVAL — inspect the eval suite + the (new or active) adapter.
    try:
        from eli.learning import lora_eval
        adapter_dir = (job.get("output_dir") if executed_training else job.get("adapter_path")) or None
        suite = lora_eval.inspect_eval_suite() if hasattr(lora_eval, "inspect_eval_suite") else {}
        adapter = lora_eval.inspect_adapter(adapter_dir) if hasattr(lora_eval, "inspect_adapter") else {}
        stages.append(_stage("eval", True, {
            "eval_suite_ok": suite.get("ok"),
            "eval_items": suite.get("items") or suite.get("count"),
            "adapter_dir": adapter_dir,
            "adapter_ok": adapter.get("ok"),
        }))
    except Exception as e:
        stages.append(_stage("eval", False, {"error": str(e)}))

    return _finish(target, execute, stages, executed_training)


def _finish(target: str, execute: bool, stages: List[Dict[str, Any]],
            executed_training: bool = False) -> Dict[str, Any]:
    ok = all(s["ok"] for s in stages)
    done = [s["stage"] for s in stages]
    summary = (f"LoRA pipeline for '{target}': "
               + (" → ".join(f"{s['stage']}{'✓' if s['ok'] else '✗'}" for s in stages))
               + (" (dry-run)" if not execute else
                  (" (trained)" if executed_training else " (execute requested but training gated)")))
    return {"ok": ok, "executed": executed_training, "target": target,
            "dry_run": not execute, "stages": stages, "summary": summary, "ran": done}


__all__ = ["run_pipeline"]
