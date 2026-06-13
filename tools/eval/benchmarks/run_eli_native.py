#!/usr/bin/env python3
"""Score GSM8K through ELI's OWN inference (not the generic lm-eval/llama.cpp path).

WHY: lm-eval + llama_cpp.server cannot drive the Qwen3 *thinking* GGUFs — they emit
<|im_end|> after a fragment (A3B "scored" 0.05, an artifact). ELI's gguf_inference
loads the same model with the embedded-chat-template detection + <think> handling
those models need, so it elicits real reasoning. This harness reuses that exact path.

Per model (selected by ELI_GGUF_MODEL_PATH): build a headless CognitiveEngine so the
model loads with ELI's smart-fit GPU layout, then call gguf_inference.generate()
directly (clean inference, no router). Writes results incrementally so an overnight
crash never loses completed items.

Usage:
  python tools/eval/benchmarks/run_eli_native.py --model models/<x>.gguf --name <label> --limit 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "artifacts" / "eval" / "benchmarks" / "eli_native"

_SYS = ("You are a careful math problem solver. Reason step by step, then end your "
        "reply with the final answer on its own line as: #### <number>")


def _load_gsm8k_docs(limit: int) -> list[dict]:
    """Reuse the exact GSM8K items already logged by the lm-eval 7B run, so all
    models are scored on identical questions. Falls back to the HF dataset."""
    import glob
    cand = sorted(glob.glob(str(REPO / "artifacts/eval/benchmarks/lm_eval/**/samples_gsm8k_*.jsonl"),
                            recursive=True), key=os.path.getmtime)
    docs, seen = [], set()
    for f in reversed(cand):
        for line in Path(f).read_text().splitlines():
            try:
                d = json.loads(line).get("doc", {})
            except Exception:
                continue
            q = d.get("question"); a = d.get("answer")
            if q and a and q not in seen:
                seen.add(q); docs.append({"question": q, "answer": a})
        if docs:
            break
    if not docs:  # fallback: HF dataset
        from datasets import load_dataset
        ds = load_dataset("gsm8k", "main", split="test")
        docs = [{"question": r["question"], "answer": r["answer"]} for r in ds]
    return docs[:limit] if limit else docs


def _gold(answer: str):
    m = re.search(r"####\s*(-?[\d,]+(?:\.\d+)?)", answer or "")
    return float(m.group(1).replace(",", "")) if m else None


def _pred(text: str):
    nums = re.findall(r"-?\$?\d[\d,]*\.?\d*", text or "")
    if not nums:
        return None
    n = nums[-1].lstrip("$").replace(",", "").rstrip(".")
    try:
        return float(n)
    except Exception:
        return None


def _gen(question: str, max_tokens: int) -> str:
    from eli.cognition import gguf_inference as gi
    out = gi.generate(question, system=_SYS, max_tokens=max_tokens,
                      temperature=0.0, stream=False)
    if isinstance(out, str):
        return out
    chunks = []  # consume a generator if that's what we got
    for c in out:
        chunks.append(c.get("response") or c.get("token") or "" if isinstance(c, dict) else str(c))
    return "".join(chunks)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max-tokens", type=int, default=3072)
    args = ap.parse_args(argv)

    model_path = Path(args.model).expanduser().resolve()
    if not model_path.exists():
        print(f"[eli-native] model not found: {model_path}", file=sys.stderr)
        return 2
    name = args.name or model_path.stem
    os.environ["ELI_GGUF_MODEL_PATH"] = str(model_path)
    os.environ.setdefault("ELI_HEADLESS", "1")
    os.environ.setdefault("ELI_MODEL_THINK", "1")  # keep reasoning ON for the main call

    OUT.mkdir(parents=True, exist_ok=True)
    samples_path = OUT / f"{name}.samples.jsonl"
    samples_path.write_text("")  # fresh

    # Load the model directly via gguf_inference (NOT the full CognitiveEngine) so
    # ELI's background daemons don't compete for the model lock or pollute timing —
    # gguf_inference itself carries the chat-template + <think> handling these models need.
    print(f"[eli-native] loading {name} via gguf_inference.load_model()…", flush=True)
    t_load = time.time()
    from eli.cognition import gguf_inference as gi
    gi.load_model()
    if not gi.is_loaded():
        print("[eli-native] model failed to load", file=sys.stderr)
        return 3
    print(f"[eli-native] loaded in {time.time()-t_load:.0f}s", flush=True)

    docs = _load_gsm8k_docs(args.limit)
    print(f"[eli-native] gsm8k items: {len(docs)}", flush=True)

    correct = 0
    t_eval = time.time()
    for i, d in enumerate(docs, 1):
        t0 = time.time()
        try:
            ans = _gen(d["question"], args.max_tokens)
        except Exception as e:
            ans = f"[error] {e}"
        dt = time.time() - t0
        gold, pred = _gold(d["answer"]), _pred(ans)
        ok = (gold is not None and pred is not None and abs(gold - pred) < 1e-6)
        correct += int(ok)
        rec = {"i": i, "question": d["question"], "gold": gold, "pred": pred,
               "ok": ok, "sec": round(dt, 1), "answer": ans}
        with samples_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  [{i}/{len(docs)}] {'✓' if ok else '✗'} pred={pred} gold={gold} {dt:.0f}s", flush=True)

    wall = time.time() - t_eval
    acc = correct / len(docs) if docs else 0.0
    result = {"model": name, "task": "gsm8k", "n": len(docs), "accuracy": round(acc, 4),
              "correct": correct, "eval_wall_s": round(wall, 1),
              "sec_per_example": round(wall / len(docs), 1) if docs else None,
              "ts": time.strftime("%Y%m%dT%H%M%S"), "via": "eli_native_inference"}
    (OUT / f"{name}.result.json").write_text(json.dumps(result, indent=2))
    with (OUT / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")
    print(f"\n[eli-native] {name}: GSM8K acc={acc:.3f} ({correct}/{len(docs)})  "
          f"{result['sec_per_example']}s/example  wall={wall:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
