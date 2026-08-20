from __future__ import annotations

import argparse
import inspect
import json
import time
from pathlib import Path
from typing import Any

from eli.learning.dataset_filters import is_bad_response, load_jsonl, row_is_reviewed
from eli.utils.log import get_logger
from eli.learning.training_preflight import preflight_target


def _eli_canonical_root_PROJECT_ROOT() -> Path:
    # Canonical env-honoring root — __file__ resolves into the read-only
    # bundle in frozen builds (identical to this path in source installs).
    try:
        from eli.core.paths import project_root
        return Path(project_root())
    except Exception:
        return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _eli_canonical_root_PROJECT_ROOT()

log = get_logger(__name__)
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


def _as_gb(value: Any) -> float:
    """Bytes → GiB, but only for a real number.

    torch is stubbed in the test suite and mocked attributes return Mock objects,
    not ints. Comparing one of those against a VRAM threshold raises TypeError deep
    inside job building, which the pipeline then swallows as a failed stage.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        return round(float(value) / 1024 ** 3, 2)
    except Exception:
        return 0.0


def _accelerator() -> dict[str, Any]:
    """What this machine can actually train on, named honestly.

    torch reports ROCm through the `torch.cuda` API — a HIP build answers
    `torch.cuda.is_available()` with True — so the same code path serves NVIDIA and
    AMD. The vendor is read from the device name so the operator is told which one is
    in use rather than being shown "CUDA" on a Radeon. Apple (mps) and Intel (xpu)
    are reported too, and both are honestly marked as unable to run this trainer.
    """
    info = {"kind": "cpu", "vendor": "cpu", "name": "CPU", "free_gb": 0.0,
            "total_gb": 0.0, "trainable": False, "note": ""}
    try:
        import torch
    except Exception as exc:
        info["note"] = f"torch unavailable: {exc}"
        return info

    if torch.cuda.is_available():
        try:
            name = torch.cuda.get_device_name(0)
            name = name if isinstance(name, str) else "GPU"
        except Exception:
            name = "GPU"
        is_rocm = bool(getattr(torch.version, "hip", None))
        info.update({
            "kind": "cuda",
            "vendor": "amd" if is_rocm else "nvidia",
            "name": name,
            "trainable": True,
            "note": "ROCm/HIP build" if is_rocm else "CUDA build",
        })
        try:
            free_b, total_b = torch.cuda.mem_get_info()
            info["free_gb"] = _as_gb(free_b)
            info["total_gb"] = _as_gb(total_b)
        except Exception:
            log.debug("[lora] torch.cuda.mem_get_info unavailable", exc_info=True)
        if not info["total_gb"]:
            # ROCm on some cards has no mem_get_info; fall back to the card total.
            try:
                total = torch.cuda.get_device_properties(0).total_memory
                info["total_gb"] = _as_gb(total)
                info["free_gb"] = _as_gb(total) * 0.85 if info["total_gb"] else 0.0
                if info["total_gb"]:
                    info["note"] += " (free VRAM unavailable; estimated)"
            except Exception:
                log.debug("[lora] could not read device properties", exc_info=True)
        return info

    if getattr(getattr(torch, "backends", None), "mps", None) and torch.backends.mps.is_available():
        info.update({"kind": "mps", "vendor": "apple", "name": "Apple Silicon (MPS)",
                     "trainable": False,
                     "note": "MPS cannot run 4-bit quantised LoRA; training would fall to CPU"})
        return info

    if hasattr(torch, "xpu") and torch.xpu.is_available():
        info.update({"kind": "xpu", "vendor": "intel", "name": "Intel GPU (XPU)",
                     "trainable": False,
                     "note": "Intel XPU is not supported by the LoRA training stack"})
        return info

    info["note"] = "no GPU visible to torch"
    return info


def bitsandbytes_available() -> bool:
    """4-bit quantised training. NVIDIA-only in practice: AMD needs a ROCm build of
    bitsandbytes that ships separately, and there is none for macOS."""
    try:
        import bitsandbytes  # noqa: F401
        return True
    except Exception:
        return False


def estimate_vram_gb(base_model_path: Any = None, *, four_bit: bool = False,
                     seq_len: int = 384, batch_size: int = 1) -> float:
    """Rough VRAM needed to LoRA-tune the base model at these settings.

    Derived from the checkpoint's real size on disk rather than a hardcoded figure,
    so it holds for a 1B and for a 35B. Deliberately generous — telling someone it
    will fit and then OOMing forty minutes in is the worse failure.
    """
    weights_gb = 3.8  # fallback ~ a 2B fp16 checkpoint
    try:
        p = Path(str(base_model_path))
        if p.is_dir():
            total = sum(f.stat().st_size for f in p.rglob("*")
                        if f.is_file() and f.suffix in (".safetensors", ".bin"))
            if isinstance(total, (int, float)) and total > 0:
                weights_gb = float(total) / 1024 ** 3
    except Exception:
        log.debug("[lora] could not size the checkpoint; using the default estimate",
                  exc_info=True)
    resident = weights_gb * (0.30 if four_bit else 1.0)
    activations = 0.5 + (seq_len / 1024.0) * 0.6 * max(1, batch_size)
    overhead = 1.2  # optimiser states for the adapter, cuda context, fragmentation
    return round(resident + activations + overhead, 2)


def _pick_device(requested: str = "auto", *, base_model_path: Any = None,
                 four_bit: bool | None = None, seq_len: int = 384,
                 batch_size: int = 1) -> dict[str, Any]:
    """Choose the training device and say why, in terms the operator can act on.

    The old rule was a flat `free_vram >= 10 GiB` floor written for a Phi-3 on an
    8 GB card. It refused a 1B model on a 6 GB card that would have fit easily, and
    silently selected CPU — where a run takes days and looks like a hang. The floor
    is now the model's own estimated requirement.
    """
    requested = str(requested or "auto").lower().strip()
    if requested not in {"auto", "cpu", "cuda", "gpu"}:
        requested = "auto"
    if requested == "gpu":
        requested = "cuda"

    acc = _accelerator()
    if four_bit is None:
        four_bit = bool(acc["kind"] == "cuda" and acc["vendor"] == "nvidia" and bitsandbytes_available())
    need_gb = estimate_vram_gb(base_model_path, four_bit=four_bit,
                               seq_len=seq_len, batch_size=batch_size)

    out = {
        "requested": requested,
        "selected": "cpu",
        "cuda_available": acc["kind"] == "cuda",
        "accelerator": acc,
        "vendor": acc["vendor"],
        "gpu_name": acc["name"],
        "free_vram_gb": acc["free_gb"],
        "total_vram_gb": acc["total_gb"],
        "four_bit": bool(four_bit),
        "estimated_need_gb": need_gb,
        "reason": "",
    }

    if requested == "cpu":
        out["reason"] = "cpu explicitly requested"
        out["four_bit"] = False
        return out

    if acc["kind"] != "cuda":
        out["reason"] = acc["note"] or "no trainable GPU detected; using cpu"
        out["four_bit"] = False
        return out

    fits = acc["free_gb"] <= 0 or acc["free_gb"] >= need_gb
    if requested == "cuda":
        out["selected"] = "cuda"
        out["reason"] = (f"gpu explicitly requested ({acc['name']}); "
                         f"{acc['free_gb']} GiB free vs ~{need_gb} GiB needed")
        if not fits:
            out["reason"] += " — this may run out of memory"
        return out

    if fits:
        out["selected"] = "cuda"
        out["reason"] = (f"{acc['name']} — {acc['free_gb']} GiB free covers the "
                         f"~{need_gb} GiB this run needs"
                         + (" (4-bit)" if four_bit else ""))
    else:
        out["reason"] = (f"{acc['name']} has {acc['free_gb']} GiB free but this run "
                         f"needs ~{need_gb} GiB. CPU training is possible but takes "
                         f"hours to days — free VRAM, shorten the sequence length, "
                         f"or install bitsandbytes for 4-bit training.")
        out["four_bit"] = False
    return out


def _format_example(row: dict[str, Any], tokenizer: Any = None) -> str:
    """Render one row in the base model's OWN prompt format.

    The literal `<|user|>/<|assistant|>` below is Phi-3's. Training a Qwen or Llama
    checkpoint on Phi-3 turn markers teaches it tokens its chat template never uses,
    so the adapter degrades the model instead of tuning it. When the tokenizer
    carries a chat template — nearly all instruct checkpoints do — that template is
    the source of truth; the literal stays as the fallback for base models without one.
    """
    instruction = str(row.get("instruction", "")).strip()
    response = str(row.get("response", "")).strip()

    if tokenizer is not None and getattr(tokenizer, "chat_template", None):
        try:
            return tokenizer.apply_chat_template(
                [{"role": "user", "content": instruction},
                 {"role": "assistant", "content": response}],
                tokenize=False,
            )
        except Exception:
            log.debug("[lora] chat template failed; using the fallback prompt format",
                      exc_info=True)

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
    from eli.learning.lora_trainer_guard import allowed_targets as _allowed
    if target not in _allowed():
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

    # Build the dataset from reviewed conversation rows if it hasn't been built yet.
    # The LoRA is human-gated, so an unbuilt/empty dataset just means "no curated
    # training data yet", not an error — but without building it the build_job stage
    # reported "dataset path does not exist" forever (a recurring proactive-log error).
    if dataset_path and not dataset_path.exists():
        try:
            from eli.learning.dataset_builder import build_dataset
            build_dataset(out_path=dataset_path)
        except Exception:
            pass
    dataset = _dataset_report(dataset_path, target) if dataset_path else {
        "ok": False,
        "problems": ["dataset path missing from guard plan"],
    }

    device_plan = _pick_device(
        device, base_model_path=base_model_path, seq_len=seq_len, batch_size=batch_size)

    problems: list[str] = []
    warnings: list[str] = []

    if not preflight.get("can_train"):
        problems.extend(preflight.get("problems") or ["preflight says training is not ready"])

    if not base_model_path or not base_model_path.exists():
        problems.append("base model path missing")
    elif base_model_path.suffix.lower() == ".gguf":
        problems.append("base model is GGUF; training requires Hugging Face model directory")

    # Data-readiness (no reviewed rows yet / unreviewed / wrong-target / bad rows) is
    # the NORMAL resting state of a human-gated LoRA: it must BLOCK training, but it is
    # NOT a pipeline failure. Track it separately from structural problems so a dry-run
    # build_job stays green (will_train=False) when there's simply nothing curated yet,
    # instead of logging a recurring error every proactive tick. (A completely missing
    # dataset_path is still a config/structural problem and stays below.)
    data_not_ready: list[str] = []
    if not dataset.get("ok"):
        if not dataset_path:
            problems.extend(dataset.get("problems") or ["dataset path missing from guard plan"])
        else:
            data_not_ready.extend(dataset.get("problems") or ["dataset not ready"])

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

    # Training requires BOTH no structural problems AND curated/ready data.
    will_train = bool(execute and not problems and not data_not_ready)

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
        "data_not_ready": data_not_ready,
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
def run_training(job: dict[str, Any], on_event=None) -> dict[str, Any]:
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

    tokenizer = AutoTokenizer.from_pretrained(
        str(base_model_path),
        trust_remote_code=False,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    rows = _load_rows(dataset_path)
    texts = [_format_example(row, tokenizer) for row in rows]
    ds = Dataset.from_list([{"text": t} for t in texts])

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

    four_bit = bool((job.get("device") or {}).get("four_bit"))

    if selected_device == "cuda" and torch.cuda.is_available():
        dtype = torch.float16
        model_kwargs["dtype"] = dtype
    else:
        model_kwargs["dtype"] = dtype

    # QLoRA — load the frozen base in 4-bit so a card that cannot hold the fp16
    # weights can still train the adapter. Only the base is quantised; the adapter
    # itself trains in fp16, so quality is close to a full-precision LoRA.
    if four_bit and selected_device == "cuda":
        try:
            from transformers import BitsAndBytesConfig
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
            model_kwargs["device_map"] = {"": 0}
        except Exception as _q_err:
            print(f"[lora] 4-bit unavailable ({_q_err}); loading in fp16")
            four_bit = False

    model = AutoModelForCausalLM.from_pretrained(str(base_model_path), **model_kwargs)
    model.config.use_cache = False

    if four_bit:
        try:
            from peft import prepare_model_for_kbit_training
            model = prepare_model_for_kbit_training(model)
        except Exception as _k_err:
            print(f"[lora] prepare_model_for_kbit_training failed: {_k_err}")
    elif selected_device == "cuda" and torch.cuda.is_available():
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
        "optim": "paged_adamw_8bit" if four_bit else "adamw_torch",
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

    # Live progress for the Training tab. A LoRA run is minutes to hours; without
    # per-step feedback the window is indistinguishable from a hang.
    if on_event is not None:
        try:
            from transformers import TrainerCallback

            class _EliProgress(TrainerCallback):
                def on_log(self, args, state, control, logs=None, **kw):
                    if not logs:
                        return
                    on_event({"type": "step",
                              "step": int(getattr(state, "global_step", 0) or 0),
                              "max_steps": int(getattr(state, "max_steps", 0) or 0),
                              "loss": logs.get("loss"),
                              "learning_rate": logs.get("learning_rate")})

            trainer.add_callback(_EliProgress())
        except Exception as _cb_err:
            print(f"[lora] progress callback unavailable: {_cb_err}")

    train_result = trainer.train()
    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    job["result"] = {
        "skipped": False,
        "ok": True,
        "output_dir": str(output_dir),
        "metrics": getattr(train_result, "metrics", {}),
        "trainable_parameters": trainable_parameter_report,
        "device": selected_device,
        "four_bit": bool(four_bit),
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
