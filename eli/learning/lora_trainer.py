from __future__ import annotations

import argparse
import inspect
import json
import time
from pathlib import Path
from typing import Any

from eli.learning.dataset_filters import is_bad_response, load_jsonl, row_is_reviewed
from eli.learning.training_preflight import preflight_target


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_ROOT / "training/runs"

ALLOWED_TARGETS = {"eli_phi", "eli_phi_ultra"}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def _resolve_project_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    p = Path(value)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def _stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not row.get("instruction") or not row.get("response"):
            continue
        clean.append(row)
    return clean


def _dataset_report(path: Path, target: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "relative": _rel(path),
            "exists": False,
            "rows": 0,
            "reviewed_rows": 0,
            "targeted_rows": 0,
            "bad_response_rows": 0,
            "needs_review_rows": 0,
            "wrong_target_rows": 0,
            "ok": False,
            "problems": ["dataset path does not exist"],
        }

    rows = _load_rows(path)
    reviewed_rows = 0
    targeted_rows = 0
    bad_response_rows = 0
    needs_review_rows = 0
    wrong_target_rows = 0

    for row in rows:
        reviewed = row_is_reviewed(row)
        if reviewed:
            reviewed_rows += 1
        else:
            needs_review_rows += 1

        targets = row.get("targets") or []
        if target in targets:
            targeted_rows += 1
        else:
            wrong_target_rows += 1

        if is_bad_response(str(row.get("response", ""))):
            bad_response_rows += 1

    problems = []
    if not rows:
        problems.append("dataset has no usable rows")
    if needs_review_rows:
        problems.append(f"dataset contains unreviewed rows: {needs_review_rows}")
    if wrong_target_rows:
        problems.append(f"dataset contains rows not scoped to {target}: {wrong_target_rows}")
    if bad_response_rows:
        problems.append(f"dataset contains bad response rows: {bad_response_rows}")

    return {
        "path": str(path),
        "relative": _rel(path),
        "exists": True,
        "rows": len(rows),
        "reviewed_rows": reviewed_rows,
        "targeted_rows": targeted_rows,
        "bad_response_rows": bad_response_rows,
        "needs_review_rows": needs_review_rows,
        "wrong_target_rows": wrong_target_rows,
        "ok": not problems,
        "problems": problems,
    }


def _pick_device(requested: str = "auto") -> dict[str, Any]:
    requested = requested.lower().strip()
    if requested not in {"auto", "cpu", "cuda"}:
        return {
            "requested": requested,
            "selected": "cpu",
            "cuda_available": False,
            "reason": "invalid device request; using cpu",
        }

    if requested == "cpu":
        return {
            "requested": requested,
            "selected": "cpu",
            "cuda_available": False,
            "reason": "cpu explicitly requested",
        }

    try:
        import torch
    except Exception as exc:
        return {
            "requested": requested,
            "selected": "cpu",
            "cuda_available": False,
            "reason": f"torch unavailable: {exc}",
        }

    cuda_available = bool(torch.cuda.is_available())
    if requested == "cuda":
        return {
            "requested": requested,
            "selected": "cuda" if cuda_available else "cpu",
            "cuda_available": cuda_available,
            "reason": "cuda explicitly requested" if cuda_available else "cuda requested but unavailable",
        }

    if not cuda_available:
        return {
            "requested": requested,
            "selected": "cpu",
            "cuda_available": False,
            "reason": "cuda unavailable",
        }

    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        free_gb = free_bytes / 1024**3
        total_gb = total_bytes / 1024**3
    except Exception:
        free_gb = 0.0
        total_gb = 0.0

    # Phi-3 full HF LoRA can OOM on 8 GB cards. Default to CPU unless enough
    # free VRAM is available. User can still force --device cuda.
    if free_gb >= 10.0:
        selected = "cuda"
        reason = f"auto selected cuda; free VRAM {free_gb:.2f} GiB"
    else:
        selected = "cpu"
        reason = f"auto selected cpu; free VRAM {free_gb:.2f} GiB below 10 GiB safety floor"

    return {
        "requested": requested,
        "selected": selected,
        "cuda_available": cuda_available,
        "free_vram_gb": round(free_gb, 3),
        "total_vram_gb": round(total_gb, 3),
        "reason": reason,
    }


def _format_example(row: dict[str, Any]) -> str:
    instruction = str(row.get("instruction", "")).strip()
    response = str(row.get("response", "")).strip()
    return (
        "<|user|>\n"
        f"{instruction}\n"
        "<|assistant|>\n"
        f"{response}"
    )


def build_training_job(
    target: str,
    *,
    execute: bool = False,
    max_steps: int = 1,
    seq_len: int = 384,
    batch_size: int = 1,
    grad_accum: int = 1,
    learning_rate: float = 2e-4,
    device: str = "auto",
    output_dir: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if target not in ALLOWED_TARGETS:
        return {
            "ok": False,
            "execute": execute,
            "will_train": False,
            "target": target,
            "problems": [f"target not allowed: {target}"],
        }

    preflight = preflight_target(target)
    guard_plan = preflight.get("guard_plan") or {}
    config = guard_plan.get("config") or {}
    resolved = guard_plan.get("resolved_paths") or {}

    base_model_path = (
        _resolve_project_path(resolved.get("base_model_path"))
        or _resolve_project_path(config.get("base_model_path"))
    )
    dataset_path = (
        _resolve_project_path(resolved.get("dataset_path"))
        or _resolve_project_path(config.get("dataset_path"))
    )
    adapter_path = (
        _resolve_project_path(resolved.get("adapter_path"))
        or _resolve_project_path(config.get("adapter_path"))
    )

    if output_dir:
        out_path = _resolve_project_path(output_dir)
    else:
        out_path = _resolve_project_path(config.get("output_dir"))

    dataset = _dataset_report(dataset_path, target) if dataset_path else {
        "ok": False,
        "problems": ["dataset path missing from guard plan"],
    }

    device_plan = _pick_device(device)

    problems: list[str] = []
    warnings: list[str] = []

    if not preflight.get("can_train"):
        problems.extend(preflight.get("problems") or ["preflight says training is not ready"])

    if not base_model_path or not base_model_path.exists():
        problems.append("base model path missing")
    elif base_model_path.suffix.lower() == ".gguf":
        problems.append("base model is GGUF; training requires Hugging Face model directory")

    if not dataset.get("ok"):
        problems.extend(dataset.get("problems") or ["dataset failed validation"])

    if not out_path:
        problems.append("output_dir missing")
    elif adapter_path and out_path.resolve() == adapter_path.resolve():
        problems.append("output_dir must not equal active adapter_path")
    elif out_path.exists() and any(out_path.iterdir()) and not overwrite:
        problems.append("output_dir already exists and is not empty; pass --overwrite or choose a new output dir")

    if max_steps < 1:
        problems.append("max_steps must be >= 1")
    if seq_len < 64:
        problems.append("seq_len must be >= 64")
    if batch_size < 1:
        problems.append("batch_size must be >= 1")
    if grad_accum < 1:
        problems.append("grad_accum must be >= 1")

    will_train = bool(execute and not problems)

    job = {
        "ok": True,
        "execute": execute,
        "will_train": will_train,
        "target": target,
        "max_steps": max_steps,
        "seq_len": seq_len,
        "batch_size": batch_size,
        "grad_accum": grad_accum,
        "learning_rate": learning_rate,
        "device": device_plan,
        "overwrite": overwrite,
        "base_model_path": str(base_model_path) if base_model_path else "",
        "dataset_path": str(dataset_path) if dataset_path else "",
        "adapter_path": str(adapter_path) if adapter_path else "",
        "output_dir": str(out_path) if out_path else "",
        "dataset": dataset,
        "preflight": {
            "can_train": preflight.get("can_train"),
            "problems": preflight.get("problems", []),
            "missing_modules": preflight.get("missing_modules", []),
            "base_model_resolution": preflight.get("base_model_resolution", {}),
        },
        "adapter_config": guard_plan.get("adapter_config", {}),
        "problems": problems,
        "warnings": warnings,
        "safety_contract": [
            "Default mode is dry-run only.",
            "--execute is required for training.",
            "Only eli_phi and eli_phi_ultra are allowed.",
            "Only reviewed target-scoped rows are trainable.",
            "GGUF files are never trained directly.",
            "Output adapter path must not overwrite the active adapter.",
            "Default max_steps=1 is a smoke-test, not a real fine-tune.",
        ],
    }

    return job



def _normalize_phi3_rope_scaling_dict(rope: Any) -> Any:
    """
    Compatibility shim for Phi-3 configs.

    Native Transformers Phi-3 expects default 4k RoPE to remain default.
    Long-context Phi-3 configs with short_factor/long_factor need longrope
    compatibility for older remote-code paths.

    This is in-memory only. Do not mutate downloaded model files.
    """
    if not isinstance(rope, dict):
        return rope

    fixed = dict(rope)

    has_longrope_factors = "short_factor" in fixed or "long_factor" in fixed
    if has_longrope_factors:
        fixed["type"] = "longrope"
        fixed["rope_type"] = "longrope"
        return fixed

    if "type" not in fixed and "rope_type" in fixed:
        fixed["type"] = fixed["rope_type"]

    return fixed


def _load_model_config(base_model_path: Path):
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(
        str(base_model_path),
        trust_remote_code=False,
    )

    rope = getattr(config, "rope_scaling", None)
    fixed_rope = _normalize_phi3_rope_scaling_dict(rope)
    if fixed_rope is not rope:
        config.rope_scaling = fixed_rope

    return config



# LoRA target-module names across common causal-LM architectures (phi/llama/qwen/
# mistral/gptneox/falcon/gpt2). Used to derive target_modules from whatever base is
# loaded — NEVER hardcode one architecture (model-agnostic).
_LORA_PROJ_LEAVES = {
    "qkv_proj", "q_proj", "k_proj", "v_proj", "o_proj", "out_proj",
    "gate_proj", "up_proj", "down_proj", "wqkv", "w1", "w2", "w3",
    "c_attn", "c_proj", "c_fc", "query_key_value", "dense_h_to_4h",
    "dense_4h_to_h", "fc_in", "fc_out", "Wqkv",
}


def _resolve_target_modules(model: Any, adapter_cfg: dict[str, Any]) -> Any:
    """Derive LoRA target modules from the LOADED model's architecture instead of
    hardcoding phi-3's ``qkv_proj``. Honours an explicit adapter_config override;
    otherwise scans the model for known projection Linear leaves; falls back to
    PEFT's architecture-agnostic ``"all-linear"``."""
    explicit = adapter_cfg.get("target_modules")
    if explicit:
        return list(explicit)
    found: set[str] = set()
    try:
        import torch.nn as nn
        for name, mod in model.named_modules():
            if isinstance(mod, nn.Linear):
                leaf = name.split(".")[-1]
                if leaf in _LORA_PROJ_LEAVES:
                    found.add(leaf)
    except Exception:
        pass
    return sorted(found) if found else "all-linear"


def _peft_trainable_parameter_report(model: Any) -> dict[str, Any]:
    """
    Return PEFT trainable parameter counts without relying on
    print_trainable_parameters(), because that helper prints and returns None.
    """
    trainable = 0
    total = 0

    for _, param in model.named_parameters():
        n = int(param.numel())
        total += n
        if bool(getattr(param, "requires_grad", False)):
            trainable += n

    pct = (100.0 * trainable / total) if total else 0.0
    summary = (
        f"trainable params: {trainable:,} || "
        f"all params: {total:,} || "
        f"trainable%: {pct:.4f}"
    )

    return {
        "trainable": trainable,
        "total": total,
        "trainable_percent": round(pct, 6),
        "summary": summary,
    }

def _training_args_kwargs(cls, raw: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(cls.__init__)
    return {k: v for k, v in raw.items() if k in sig.parameters}


# ELI_PHI3_NATIVE_TRANSFORMERS_LOAD_V1
# Phi-3 must load through native transformers code here. The downloaded
# remote modeling_phi3.py path rejects default RoPE in this environment.
def run_training(job: dict[str, Any]) -> dict[str, Any]:
    if not job.get("execute"):
        job["result"] = {"skipped": True, "reason": "dry-run; pass --execute to train"}
        return job

    if not job.get("will_train"):
        job["result"] = {"skipped": True, "reason": "job failed safety validation"}
        return job

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    base_model_path = Path(job["base_model_path"])
    dataset_path = Path(job["dataset_path"])
    output_dir = Path(job["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_rows(dataset_path)
    texts = [_format_example(row) for row in rows]
    ds = Dataset.from_list([{"text": t} for t in texts])

    tokenizer = AutoTokenizer.from_pretrained(
        str(base_model_path),
        trust_remote_code=False,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    seq_len = int(job["seq_len"])

    def tokenize(batch):
        out = tokenizer(
            batch["text"],
            truncation=True,
            padding="max_length",
            max_length=seq_len,
        )
        out["labels"] = list(out["input_ids"])
        return out

    ds = ds.map(tokenize, batched=True, remove_columns=["text"])

    selected_device = job["device"]["selected"]
    dtype = torch.float32
    config = _load_model_config(base_model_path)

    model_kwargs: dict[str, Any] = {
        "trust_remote_code": False,
        "low_cpu_mem_usage": True,
        "config": config,
        "attn_implementation": "eager",
    }

    if selected_device == "cuda" and torch.cuda.is_available():
        dtype = torch.float16
        model_kwargs["dtype"] = dtype
    else:
        model_kwargs["dtype"] = dtype

    model = AutoModelForCausalLM.from_pretrained(str(base_model_path), **model_kwargs)
    model.config.use_cache = False

    if selected_device == "cuda" and torch.cuda.is_available():
        model.to("cuda")

    if hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable()

    adapter_cfg = job.get("adapter_config") or {}
    # Model-agnostic: derive target modules from the loaded architecture instead of
    # the previous phi-3-only hardcoded default.
    target_modules = _resolve_target_modules(model, adapter_cfg)

    lora_config = LoraConfig(
        r=int(adapter_cfg.get("r", 4)),
        lora_alpha=int(adapter_cfg.get("lora_alpha", 4)),
        lora_dropout=float(adapter_cfg.get("lora_dropout", 0.0)),
        bias=str(adapter_cfg.get("bias", "none")),
        task_type="CAUSAL_LM",
        target_modules=target_modules if isinstance(target_modules, str) else list(target_modules),
    )

    model = get_peft_model(model, lora_config)
    trainable_parameter_report = _peft_trainable_parameter_report(model)
    print(trainable_parameter_report["summary"])

    raw_args = {
        "output_dir": str(output_dir),
        "overwrite_output_dir": bool(job["overwrite"]),
        "per_device_train_batch_size": int(job["batch_size"]),
        "gradient_accumulation_steps": int(job["grad_accum"]),
        "max_steps": int(job["max_steps"]),
        "learning_rate": float(job["learning_rate"]),
        "logging_steps": 1,
        "save_steps": int(job["max_steps"]),
        "save_total_limit": 1,
        "report_to": [],
        "remove_unused_columns": False,
        "optim": "adamw_torch",
        "fp16": bool(selected_device == "cuda"),
        "use_cpu": bool(selected_device == "cpu"),
        "no_cuda": bool(selected_device == "cpu"),
    }

    args = TrainingArguments(**_training_args_kwargs(TrainingArguments, raw_args))

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )

    train_result = trainer.train()
    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    job["result"] = {
        "skipped": False,
        "ok": True,
        "output_dir": str(output_dir),
        "metrics": getattr(train_result, "metrics", {}),
        "trainable_parameters": trainable_parameter_report,
    }
    return job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gated ELI Phi LoRA trainer")
    parser.add_argument("--target", choices=sorted(ALLOWED_TARGETS), required=True)
    parser.add_argument("--execute", action="store_true", help="Actually run training")
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--seq-len", type=int, default=384)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    job = build_training_job(
        args.target,
        execute=args.execute,
        max_steps=args.max_steps,
        seq_len=args.seq_len,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.learning_rate,
        device=args.device,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
    )

    try:
        job = run_training(job)
    except Exception as exc:
        job["will_train"] = False
        job["result"] = {
            "skipped": False,
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = RUNS_DIR / f"lora_train_{args.target}_{_stamp()}.json"
    job["plan_path"] = str(plan_path)
    _safe_write_json(plan_path, job)

    print(json.dumps(job, indent=2, ensure_ascii=False))
    return 0 if job.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
