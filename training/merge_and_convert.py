#!/usr/bin/env python3
"""Merge an ELI LoRA adapter into its base, convert to GGUF, quantize, and install in models/.

Final step of the pipeline (after extract_eli_dataset.py + train_lora.py). Uses Unsloth's
one-shot `save_pretrained_gguf` (merge + llama.cpp convert + quantize). If that path isn't
available in your environment, see training/README.md for the manual llama.cpp commands.

Example:
  python training/merge_and_convert.py \
      --base-model Qwen/Qwen3-8B \
      --adapter training/runs/eli-qwen3-8b-lora \
      --out-name eli-qwen3-8b \
      --quant q4_k_m
"""
from __future__ import annotations
import argparse, shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge LoRA → GGUF → quantize → install in models/.")
    ap.add_argument("--base-model", default="Qwen/Qwen3-8B")
    ap.add_argument("--adapter", default="training/runs/eli-lora-adapter")
    ap.add_argument("--out-name", default="eli-qwen3-8b", help="Base name for the produced GGUF.")
    ap.add_argument("--quant", default="q4_k_m", help="q4_k_m (recommended for 8 GB) / q5_k_m / q8_0.")
    ap.add_argument("--max-seq-len", type=int, default=4096)
    ap.add_argument("--models-dir", default="models")
    ap.add_argument("--gpu-mem", default="5.5GiB")
    ap.add_argument("--cpu-mem", default="20GiB")
    args = ap.parse_args()

    import torch
    from unsloth import FastLanguageModel

    # Reload base + adapter (merge happens inside save_pretrained_gguf).
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model, max_seq_length=args.max_seq_len,
        dtype=None, load_in_4bit=True, device_map="sequential",
        max_memory={0: args.gpu_mem, "cpu": args.cpu_mem},
    )
    model.load_adapter(args.adapter)

    staging = Path(args.adapter).parent / f"{args.out_name}-gguf"
    staging.mkdir(parents=True, exist_ok=True)
    # Unsloth: merge to 16-bit, convert with llama.cpp, quantize.
    model.save_pretrained_gguf(str(staging), tokenizer, quantization_method=args.quant)

    # Install the produced GGUF into models/ so ELI's model-agnostic loader finds it.
    produced = sorted(staging.glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
    if not produced:
        raise SystemExit(f"no .gguf produced under {staging} — see training/README.md manual path")
    dest = Path(args.models_dir) / f"{args.out_name}-{args.quant}.gguf"
    shutil.copy2(produced[0], dest)
    print(f"✅ installed {dest}  ({dest.stat().st_size/1e9:.2f} GB)")
    print("   Load it in ELI (Model menu / Auto Detect). The ctx tuner will size it from its real "
          "n_ctx_train; the dynamic persona+memory still come from the runtime at inference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
