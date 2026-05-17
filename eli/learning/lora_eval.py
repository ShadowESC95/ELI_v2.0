from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from eli.learning.base_model_resolver import resolve_base_model_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_ROOT / "training/runs"

ALLOWED_TARGETS = {"eli_phi", "eli_phi_ultra"}
DEFAULT_EVAL_PATH = PROJECT_ROOT / "training/evals/eli_self_model_eval.jsonl"


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def _resolve(path: str | Path | None) -> Path:
    if path is None:
        return Path()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p



def _patch_dynamic_cache_seen_tokens() -> None:
    """
    Backward-compatible shim for older Phi-3 remote-code paths.

    Native Transformers loading should not need this, but keeping the shim
    prevents regressions when an older cached modeling_phi3.py expects
    DynamicCache.seen_tokens.
    """
    try:
        from transformers.cache_utils import DynamicCache
    except Exception:
        return

    if not hasattr(DynamicCache, "seen_tokens"):
        def _get_seen_tokens(self):
            try:
                return int(getattr(self, "_seen_tokens", 0) or 0)
            except Exception:
                return 0

        try:
            DynamicCache.seen_tokens = property(_get_seen_tokens)
        except Exception:
            pass


def _patch_transformers_cache_compat_v2() -> None:
    """
    Add legacy cache methods expected by some older Phi-3 remote-code files.
    Safe no-op on newer Transformers.
    """
    _patch_dynamic_cache_seen_tokens()

    try:
        from transformers.cache_utils import DynamicCache
    except Exception:
        return

    if not hasattr(DynamicCache, "get_max_length"):
        def _get_max_length(self):
            for name in ("max_cache_len", "max_length", "_max_length"):
                value = getattr(self, name, None)
                if value is not None:
                    return value
            return None

        try:
            DynamicCache.get_max_length = _get_max_length
        except Exception:
            pass


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def score_response(response: str, item_or_expected: Any = None, forbidden: Any = None) -> dict[str, Any]:
    if isinstance(item_or_expected, dict):
        expected_any = item_or_expected.get("expected_any", [])
        forbidden_items = item_or_expected.get("forbidden", [])
    else:
        expected_any = item_or_expected or []
        forbidden_items = forbidden or []

    text = response.lower()

    expected_hits = [x for x in expected_any if str(x).lower() in text]
    forbidden_hits = [x for x in forbidden_items if str(x).lower() in text]

    expected_ok = bool(expected_hits) if expected_any else True
    forbidden_ok = not forbidden_hits

    return {
        "passed": bool(expected_ok and forbidden_ok),
        "expected_ok": bool(expected_ok),
        "forbidden_ok": bool(forbidden_ok),
        "expected_hits": expected_hits,
        "forbidden_hits": forbidden_hits,
    }


def inspect_eval_suite(path: str | Path = DEFAULT_EVAL_PATH) -> dict[str, Any]:
    p = _resolve(path)
    problems: list[str] = []
    items = _load_jsonl(p)

    if not p.exists():
        problems.append(f"eval path missing: {_rel(p)}")
    if p.exists() and not items:
        problems.append("eval suite is empty")

    clean_items: list[dict[str, Any]] = []
    for i, row in enumerate(items, start=1):
        item_id = row.get("id") or f"row_{i}"
        instruction = str(row.get("instruction", "")).strip()
        expected_any = row.get("expected_any", [])
        forbidden = row.get("forbidden", [])

        if not instruction:
            problems.append(f"{item_id}: missing instruction")

        clean_items.append(
            {
                "id": item_id,
                "instruction": instruction,
                "expected_any": expected_any if isinstance(expected_any, list) else [expected_any],
                "forbidden": forbidden if isinstance(forbidden, list) else [forbidden],
            }
        )

    return {
        "path": str(p),
        "relative": _rel(p),
        "exists": p.exists(),
        "rows": len(clean_items),
        "ok": bool(p.exists() and clean_items and not problems),
        "problems": problems,
        "items": clean_items,
    }


def inspect_adapter(adapter_dir: str | Path | None, *, base_only: bool = False) -> dict[str, Any]:
    if base_only:
        base = resolve_base_model_path(None, allow_default_candidates=True)
        return {
            "base_only": True,
            "path": "",
            "relative": "",
            "exists": False,
            "has_config": False,
            "has_model": False,
            "config": {},
            "base_model_resolution": base,
            "ok": bool(base.get("ok")),
            "problems": [] if base.get("ok") else ["base model unresolved"],
        }

    p = _resolve(adapter_dir)
    cfg_path = p / "adapter_config.json"
    model_path = p / "adapter_model.safetensors"

    problems: list[str] = []
    cfg: dict[str, Any] = {}

    if not p.exists():
        problems.append(f"adapter dir missing: {_rel(p)}")
    if not cfg_path.exists():
        problems.append("adapter_config.json missing")
    if not model_path.exists():
        problems.append("adapter_model.safetensors missing")

    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"adapter_config.json unreadable: {type(e).__name__}: {e}")

    base_model_name = cfg.get("base_model_name_or_path") or None
    base = resolve_base_model_path(base_model_name, allow_default_candidates=True)

    if not base.get("ok"):
        problems.append("adapter base model unresolved")

    summary_cfg = {
        "base_model_name_or_path": cfg.get("base_model_name_or_path"),
        "peft_type": cfg.get("peft_type"),
        "task_type": cfg.get("task_type"),
        "r": cfg.get("r"),
        "lora_alpha": cfg.get("lora_alpha"),
        "target_modules": cfg.get("target_modules"),
    }

    return {
        "base_only": False,
        "path": str(p),
        "relative": _rel(p),
        "exists": p.exists(),
        "has_config": cfg_path.exists(),
        "has_model": model_path.exists(),
        "config": summary_cfg,
        "base_model_resolution": base,
        "ok": bool(p.exists() and cfg_path.exists() and model_path.exists() and base.get("ok") and not problems),
        "problems": problems,
    }


def _select_device(requested: str) -> dict[str, Any]:
    if requested == "cpu":
        return {"requested": requested, "selected": "cpu", "reason": "cpu explicitly requested"}

    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False

    if requested == "cuda":
        return {
            "requested": requested,
            "selected": "cuda" if cuda_available else "cpu",
            "cuda_available": cuda_available,
            "reason": "cuda explicitly requested" if cuda_available else "cuda requested but unavailable; falling back to cpu",
        }

    return {
        "requested": requested,
        "selected": "cuda" if cuda_available else "cpu",
        "cuda_available": cuda_available,
        "reason": "auto selected cuda" if cuda_available else "auto selected cpu",
    }


def build_eval_job(
    target: str = "eli_phi",
    adapter_dir: str | Path | None = None,
    eval_path: str | Path = DEFAULT_EVAL_PATH,
    execute: bool = False,
    device: str = "auto",
    max_new_tokens: int = 128,
    temperature: float = 0.0,
    base_only: bool = False,
) -> dict[str, Any]:
    problems: list[str] = []

    if target not in ALLOWED_TARGETS:
        problems.append(f"unsupported target: {target}")

    adapter = inspect_adapter(adapter_dir, base_only=base_only)
    eval_suite = inspect_eval_suite(eval_path)
    device_report = _select_device(device)

    if not adapter.get("ok"):
        problems.extend(adapter.get("problems", []))
    if not eval_suite.get("ok"):
        problems.extend(eval_suite.get("problems", []))

    will_evaluate = bool(execute and not problems)

    return {
        "ok": not problems,
        "execute": bool(execute),
        "will_evaluate": will_evaluate,
        "target": target,
        "base_only": bool(base_only),
        "adapter": adapter,
        "eval": eval_suite,
        "device": device_report,
        "max_new_tokens": int(max_new_tokens),
        "temperature": float(temperature),
        "problems": problems,
        "warnings": [],
        "safety_contract": [
            "Default mode is dry-run only.",
            "--execute is required for model generation.",
            "Only eli_phi and eli_phi_ultra adapters are evaluated here.",
            "--base-only evaluates the HF base without loading a PEFT adapter.",
            "Eval checks expected and forbidden strings; it is not a full benchmark.",
            "GGUF files are not loaded here; this evaluates HF base and optional PEFT adapter.",
        ],
        "result": {"skipped": True, "reason": "dry-run; pass --execute to run generation"},
    }


def _format_prompt(tokenizer: Any, instruction: str) -> str:
    messages = [{"role": "user", "content": instruction}]
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception:
        return f"<|user|>\n{instruction}<|end|>\n<|assistant|>\n"


def _load_generation_stack(job: dict[str, Any]) -> tuple[Any, Any]:
    import torch
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

    base_path = Path(job["adapter"]["base_model_resolution"]["path"])

    tokenizer = AutoTokenizer.from_pretrained(
        str(base_path),
        trust_remote_code=False,
    )

    cfg = AutoConfig.from_pretrained(
        str(base_path),
        trust_remote_code=False,
    )
    cfg.use_cache = False

    model = AutoModelForCausalLM.from_pretrained(
        str(base_path),
        config=cfg,
        trust_remote_code=False,
        attn_implementation="eager",
        torch_dtype=torch.float32,
        device_map=None,
    )

    if not job.get("base_only"):
        from peft import PeftModel

        adapter_path = Path(job["adapter"]["path"])
        model = PeftModel.from_pretrained(model, str(adapter_path))

    selected_device = job["device"]["selected"]
    if selected_device == "cuda":
        model = model.to("cuda")
    else:
        model = model.to("cpu")

    model.eval()
    return tokenizer, model


def run_eval(job: dict[str, Any]) -> dict[str, Any]:
    if not job.get("will_evaluate"):
        return job

    try:
        import torch

        tokenizer, model = _load_generation_stack(job)
        selected_device = job["device"]["selected"]

        results: list[dict[str, Any]] = []

        for item in job["eval"]["items"]:
            prompt = _format_prompt(tokenizer, item["instruction"])
            inputs = tokenizer(prompt, return_tensors="pt")

            if selected_device == "cuda":
                inputs = {k: v.to("cuda") for k, v in inputs.items()}

            generation_kwargs: dict[str, Any] = {
                **inputs,
                "max_new_tokens": int(job["max_new_tokens"]),
                "use_cache": False,  # use_cache=False,
                "repetition_penalty": 1.15,
                "no_repeat_ngram_size": 4,
                "eos_token_id": tokenizer.eos_token_id,
                "pad_token_id": tokenizer.eos_token_id,
            }

            if float(job["temperature"]) > 0:
                generation_kwargs["do_sample"] = True
                generation_kwargs["temperature"] = float(job["temperature"])
            else:
                generation_kwargs["do_sample"] = False

            with torch.no_grad():
                out = model.generate(**generation_kwargs)

            response = tokenizer.decode(
                out[0][inputs["input_ids"].shape[-1]:],
                skip_special_tokens=True,
            ).strip()

            score = score_response(response, item)

            results.append(
                {
                    "id": item["id"],
                    "instruction": item["instruction"],
                    "response": response,
                    "score": score,
                }
            )

        passed = sum(1 for x in results if x["score"]["passed"])
        total = len(results)
        pass_rate = passed / total if total else 0.0

        job["result"] = {
            "ok": passed == total,
            "passed": passed,
            "total": total,
            "pass_rate": pass_rate,
            "items": results,
        }
        job["ok"] = bool(job["result"]["ok"])
        return job

    except Exception as e:
        job["ok"] = False
        job["result"] = {
            "skipped": False,
            "ok": False,
            "error_type": type(e).__name__,
            "error": str(e),
        }
        return job


def write_report(job: dict[str, Any]) -> dict[str, Any]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    mode = "base" if job.get("base_only") else "adapter"
    path = RUNS_DIR / f"lora_eval_{job['target']}_{mode}_{stamp}.json"
    path.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
    job["report_path"] = str(path)
    return job


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate ELI Phi LoRA adapter or base model against self-model probes.")
    ap.add_argument("--target", choices=sorted(ALLOWED_TARGETS), default="eli_phi")
    ap.add_argument("--adapter-dir", default="")
    ap.add_argument("--eval-path", default=str(DEFAULT_EVAL_PATH))
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--base-only", action="store_true")
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args(argv)

    job = build_eval_job(
        target=args.target,
        adapter_dir=args.adapter_dir or None,
        eval_path=args.eval_path,
        execute=args.execute,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        base_only=args.base_only,
    )

    job = run_eval(job)
    job = write_report(job)

    print(json.dumps(job, indent=2, ensure_ascii=False))
    return 0 if job.get("ok") or job.get("result", {}).get("ok") is False else 1


if __name__ == "__main__":
    raise SystemExit(main())
