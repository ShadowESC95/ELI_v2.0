#!/usr/bin/env python3
"""Official academic benchmarks (lm-evaluation-harness) against a local GGUF.

This benchmarks the MODEL ITSELF — the raw capability ceiling — NOT ELI's
route/ground/execute pipeline. Use it for model selection (the A3B-vs-7B
bake-off). For benchmarking ELI-the-assistant, use the promptfoo provider
(tools/eval/promptfoo/) or the in-house board (tools/eval/run_eval.py).

100% local: spins up a llama.cpp OpenAI-compatible server for the GGUF, points
lm-eval at it, tears the server down, and writes results under
artifacts/eval/benchmarks/lm_eval/<model_stem>/.

ELI-aligned task groups (pick with --suite):
  gen   (default)  ifeval, gsm8k
                   → instruction-following + multi-step reasoning. Generation
                     tasks, so NO HF tokenizer download is needed.
  mc               truthfulqa_mc2, arc_easy, hellaswag
                   → anti-confabulation + commonsense. These are loglikelihood
                     tasks: they need token logprobs, so pass --tokenizer <hf-repo>
                     (a small download, e.g. Qwen/Qwen2.5-7B-Instruct).
  knowledge        mmlu  (large; use --limit)

Examples:
  # fast, no tokenizer download — prove a model on instruction-following + math
  python tools/eval/benchmarks/run_lm_eval.py \
      --model models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --suite gen --limit 50

  # anti-confabulation (TruthfulQA) + commonsense — needs the HF tokenizer
  python tools/eval/benchmarks/run_lm_eval.py \
      --model models/Qwen2.5-7B-Instruct-Q4_K_M.gguf --suite mc \
      --tokenizer Qwen/Qwen2.5-7B-Instruct --limit 100

Exit code is non-zero if the harness fails. Designed to be run per-model and the
result JSONs compared (model bake-off).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT_ROOT = REPO / "artifacts" / "eval" / "benchmarks" / "lm_eval"

SUITES = {
    "gen": "ifeval,gsm8k",
    "mc": "truthfulqa_mc2,arc_easy,hellaswag",
    "knowledge": "mmlu",
}

# lm-eval's local-completions always needs a tokenizer (for prompt accounting on
# generation tasks, and for loglikelihood scoring on mc/knowledge). Map the GGUFs
# in models/ to their matching HF tokenizer repo (tiny download, cached offline
# after first use). Substring match on the model file stem; --tokenizer overrides.
_TOKENIZER_MAP = {
    "smollm2-1.7b": "HuggingFaceTB/SmolLM2-1.7B-Instruct",
    "qwen2.5-coder-7b": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen2.5-7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5-3b": "Qwen/Qwen2.5-3B-Instruct",
    "qwen3-32b": "Qwen/Qwen3-32B",
    "qwen3.6-35b-a3b": "Qwen/Qwen3-30B-A3B",   # closest published A3B tokenizer
    "mistral-7b-instruct-v0.2": "mistralai/Mistral-7B-Instruct-v0.2",
    "mistral-small-3.1-24b": "mistralai/Mistral-Small-3.1-24B-Instruct-2503",
    "mixtral-8x7b": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "ministral-3b": "ministral/Ministral-3b-instruct",
    "openhermes-2.5-mistral-7b": "teknium/OpenHermes-2.5-Mistral-7B",
    "deepseek-r1-distill-qwen-1.5b": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
}


def _resolve_tokenizer(model_stem: str, override: str) -> str:
    if override:
        return override
    low = model_stem.lower()
    for key, repo in _TOKENIZER_MAP.items():
        if key in low:
            return repo
    return ""


def _wait_for_server(port: int, timeout_s: float = 600.0) -> bool:
    url = f"http://127.0.0.1:{port}/v1/models"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(2.0)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="path to a .gguf model")
    ap.add_argument("--suite", choices=sorted(SUITES), default="gen")
    ap.add_argument("--tasks", default="", help="override the suite with an explicit lm-eval task list")
    ap.add_argument("--tokenizer", default="", help="HF tokenizer repo (required for mc/knowledge suites)")
    ap.add_argument("--limit", type=int, default=0, help="cap examples per task (0 = full)")
    ap.add_argument("--gpu-layers", type=int, default=int(os.environ.get("ELI_BENCH_GPU_LAYERS", "20")))
    ap.add_argument("--ctx", type=int, default=4096)
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--name", default="", help="label for the model in results (default: file stem)")
    # Thinking-aware mode: route through the CHAT endpoint + chat template so a
    # reasoning model's <think> output stops at the turn boundary (not the few-shot
    # "\n\n"), with a large generation budget so it can think AND emit the answer.
    ap.add_argument("--chat", action="store_true",
                    help="use the chat endpoint + chat template (correct for instruct/reasoning models)")
    ap.add_argument("--max-gen-toks", type=int, default=0,
                    help="generation budget per item (default 2048 in --chat mode, else task default)")
    ap.add_argument("--no-think", action="store_true",
                    help="inject a /no_think system instruction (Qwen3) to disable reasoning")
    ap.add_argument("--fewshot", type=int, default=-1, help="override num_fewshot (-1 = task default)")
    args = ap.parse_args(argv)

    model_path = Path(args.model).expanduser().resolve()
    if not model_path.exists():
        print(f"[bench] model not found: {model_path}", file=sys.stderr)
        return 2
    name = args.name or model_path.stem
    tasks = args.tasks or SUITES[args.suite]
    tokenizer = _resolve_tokenizer(name, args.tokenizer)
    if not tokenizer:
        print(f"[bench] no tokenizer mapping for {name!r}; pass --tokenizer <hf-repo> "
              f"(the model's matching HF tokenizer).", file=sys.stderr)
        return 2

    # KNOWN LIMITATION: lm-eval's mc/knowledge tasks are loglikelihood-scored,
    # which needs correct echo+prompt-logprobs. The bundled llama_cpp.server
    # returns BROKEN prompt logprobs (verified: it ranks " Berlin" above " Paris"
    # for France's capital), so these suites produce garbage (~0 acc) over this
    # backend. And the `gen` suite under-measures *reasoning/think* models (Qwen3),
    # whose <think> output trips the few-shot stop-sequences. See README.
    _is_ll = bool(set(tasks.split(",")) & {
        "truthfulqa_mc1", "truthfulqa_mc2", "arc_easy", "arc_challenge",
        "hellaswag", "winogrande", "mmlu", "piqa", "openbookqa"})
    if _is_ll and os.environ.get("ELI_BENCH_ALLOW_LOGLIKELIHOOD") != "1":
        print("[bench] REFUSING: loglikelihood tasks ("+tasks+") are unreliable over "
              "llama_cpp.server (broken echo-logprobs). Use the promptfoo/ELI route for "
              "truthfulness, or set ELI_BENCH_ALLOW_LOGLIKELIHOOD=1 to override.",
              file=sys.stderr)
        return 2

    out_dir = OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Launch the llama.cpp OpenAI-compatible server for this GGUF.
    print(f"[bench] starting llama_cpp.server for {name} (gpu_layers={args.gpu_layers}, ctx={args.ctx})")
    server = subprocess.Popen(
        [sys.executable, "-m", "llama_cpp.server",
         "--model", str(model_path),
         "--n_gpu_layers", str(args.gpu_layers),
         "--n_ctx", str(args.ctx),
         "--host", "127.0.0.1", "--port", str(args.port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        if not _wait_for_server(args.port):
            print("[bench] server did not become ready", file=sys.stderr)
            return 3
        print(f"[bench] server ready on :{args.port}")

        # 2) Build lm-eval model_args + command. Two modes:
        #    completions (default) — raw /v1/completions, few-shot, fast for
        #      non-thinking models.
        #    chat (--chat)         — /v1/chat/completions + chat template, so a
        #      reasoning model's <think> stops at the turn boundary (not "\n\n")
        #      and a large gen budget lets it think AND answer. Correct for
        #      instruct/reasoning models (Qwen3 A3B / 32B).
        endpoint = "chat/completions" if args.chat else "completions"
        model_type = "local-chat-completions" if args.chat else "local-completions"
        # tokenized_requests=False → send STRING prompts (llama.cpp server rejects
        # token-id arrays with a 500); the HF tokenizer is still used for accounting.
        ma = [f"base_url=http://127.0.0.1:{args.port}/v1/{endpoint}",
              f"model={name}", f"tokenizer={tokenizer}", "tokenized_requests=False",
              "num_concurrent=1", "max_retries=2"]
        model_args = ",".join(ma)
        print(f"[bench] mode={'chat' if args.chat else 'completions'} tokenizer={tokenizer}")

        cmd = [sys.executable, "-m", "lm_eval",
               "--model", model_type,
               "--model_args", model_args,
               "--tasks", tasks,
               "--output_path", str(out_dir),
               "--log_samples"]
        if args.limit:
            cmd += ["--limit", str(args.limit)]
        if args.chat:
            cmd += ["--apply_chat_template", "--fewshot_as_multiturn"]
        if args.fewshot >= 0:
            cmd += ["--num_fewshot", str(args.fewshot)]
        gen_toks = args.max_gen_toks or (2048 if args.chat else 0)
        if gen_toks:
            cmd += ["--gen_kwargs", f"max_gen_toks={gen_toks}"]
        if args.no_think:
            cmd += ["--system_instruction", "/no_think"]

        print(f"[bench] lm_eval tasks={tasks} limit={args.limit or 'full'} "
              f"gen_toks={gen_toks or 'task-default'} no_think={args.no_think}")
        t_eval = time.time()
        rc = subprocess.call(cmd)
        eval_wall = time.time() - t_eval
        if rc != 0:
            print(f"[bench] lm_eval exited rc={rc}", file=sys.stderr)
            return rc

        # 3) Surface a one-line rollup + append to the bake-off ledger. eval_wall
        #    is the throughput signal (the deciding axis on GPU-poor hardware,
        #    where a dense 32B's per-token compute dwarfs a 3B-active MoE's).
        _summarise(out_dir, name, tasks, eval_wall, args.limit)
        return 0
    finally:
        try:
            os.killpg(os.getpgid(server.pid), signal.SIGTERM)
        except Exception:
            try:
                server.terminate()
            except Exception:
                pass


def _summarise(out_dir: Path, name: str, tasks: str,
               eval_wall_s: float = 0.0, limit: int = 0) -> None:
    """Find lm-eval's results json, print headline metrics, append to ledger."""
    results = sorted(out_dir.rglob("results_*.json"), key=lambda p: p.stat().st_mtime)
    if not results:
        print("[bench] no results json found")
        return
    data = json.loads(results[-1].read_text())
    res = data.get("results", {})
    print(f"\n  lm-eval — {name}\n  " + "─" * 46)
    flat = {}
    for task, metrics in res.items():
        for k, v in metrics.items():
            if isinstance(v, (int, float)) and not k.endswith("_stderr") and k != "alias":
                print(f"  {task:22} {k:22} {v:.4f}")
                flat[f"{task}/{k}"] = round(float(v), 4)
    # Throughput: total examples scored across tasks ÷ wall-time → ex/min.
    n_ex = max(1, len(res)) * (limit or 0)
    sec_per_ex = round(eval_wall_s / n_ex, 1) if (n_ex and eval_wall_s) else None
    print(f"  {'(throughput)':22} {'eval_wall_s':22} {eval_wall_s:.1f}"
          + (f"  (~{sec_per_ex}s/example)" if sec_per_ex else ""))
    ledger = OUT_ROOT / "bakeoff.jsonl"
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y%m%dT%H%M%S"),
                            "model": name, "tasks": tasks,
                            "eval_wall_s": round(eval_wall_s, 1),
                            "sec_per_example": sec_per_ex,
                            "metrics": flat}) + "\n")
    print(f"\n  ledger: {ledger}")


if __name__ == "__main__":
    raise SystemExit(main())
