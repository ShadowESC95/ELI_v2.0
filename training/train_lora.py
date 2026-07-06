#!/usr/bin/env python3
"""Train an ELI LoRA adapter — parameterised, model-agnostic.

Consolidates models/train_lora_7b_optimized.py + train_phi3.py into one script. Defaults
target Qwen3-8B (the bake-off winner: 40k context holds ELI's brief; fits an 8 GB card).
Keeps the proven 4-bit + CPU-offload setup for low-VRAM GPUs.

This trains the STABLE voice/manner layer only (see extract_eli_dataset.py). The dynamic,
self-updating persona stays in ELI's runtime — do not bake it in here.

Prereqs: `pip install unsloth trl` and the base model's HF weights available locally or via
HF id (training needs HF weights, NOT the inference GGUF).

Example:
  python training/train_lora.py \
      --base-model Qwen/Qwen3-8B \
      --dataset training/datasets/eli_voice.jsonl \
      --out training/runs/eli-qwen3-8b-lora \
      --max-seq-len 4096 --max-steps 300
"""
from __future__ import annotations
import argparse, json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Train an ELI LoRA adapter (voice/manner only).")
    ap.add_argument("--base-model", default="Qwen/Qwen3-8B",
                    help="HF id or local path to the BASE model weights (not a GGUF).")
    ap.add_argument("--dataset", default="training/datasets/eli_voice.jsonl")
    ap.add_argument("--out", default="training/runs/eli-lora-adapter")
    ap.add_argument("--max-seq-len", type=int, default=4096,
                    help="Up from the old 1024 so multi-turn ELI examples aren't clipped.")
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=8)
    ap.add_argument("--lora-alpha", type=int, default=16)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--gpu-mem", default="5.5GiB", help="Max GPU memory for the model (8 GB card → ~5.5GiB).")
    ap.add_argument("--cpu-mem", default="20GiB")
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from unsloth import FastLanguageModel
    from transformers import TrainingArguments, BitsAndBytesConfig
    from trl import SFTTrainer

    rows = [json.loads(l)["text"] for l in Path(args.dataset).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        raise SystemExit(f"empty dataset: {args.dataset} (run extract_eli_dataset.py first)")
    dataset = Dataset.from_list([{"text": t} for t in rows])
    print(f"loaded {len(rows)} examples from {args.dataset}")

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
        llm_int8_enable_fp32_cpu_offload=True,
    )
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=args.max_seq_len,
        dtype=None, load_in_4bit=True,
        device_map="sequential",
        max_memory={0: args.gpu_mem, "cpu": args.cpu_mem},
        quantization_config=bnb,
    )
    model = FastLanguageModel.get_peft_model(
        model, r=args.lora_r, lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0, bias="none",
        use_gradient_checkpointing="unsloth", random_state=42,
    )
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=dataset,
        dataset_text_field="text", max_seq_length=args.max_seq_len, dataset_num_proc=2,
        args=TrainingArguments(
            per_device_train_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            warmup_steps=10, max_steps=args.max_steps, learning_rate=args.lr,
            fp16=True, bf16=False, logging_steps=1, optim="adamw_8bit",
            weight_decay=0.01, lr_scheduler_type="linear", seed=42,
            output_dir=str(Path(args.out) / "checkpoints"),
            report_to="none", dataloader_num_workers=0,
        ),
    )
    trainer.train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"✅ LoRA adapter saved → {args.out}\n   Next: training/merge_and_convert.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
