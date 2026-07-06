# ELI LoRA Fine-Tuning Pipeline

One consolidated, parameterised pipeline to fine-tune a base model into an **ELI-native
substrate** — and drop the resulting GGUF straight into `models/`.

**Default target: `Qwen/Qwen3-8B`** — the bake-off winner. Its 40,960 context holds ELI's
full ~7–9k brief (unlike the 4k phi-3, which produced garbage), and at Q4 it fits an 8 GB card.

## The one rule: persona stays dynamic
ELI's persona is **dynamic, self-updating, and lives in the runtime** (`persona_updater` +
overlay + the per-turn memory brief). So this pipeline trains **only the stable layer** —
ELI's *voice / manner / behavioral contracts* as expressed in its actual replies — and
**does not bake persona state or memories into the weights**. Concretely:
- `extract_eli_dataset.py` trains on the USER↔ELI turns themselves (the assistant's replies
  teach the register), with **`--system-mode none`** by default and **memory-state injection
  excluded** (the old `models/extract_training_data*.py` dumped `memories[-50:]` in as system
  prompts — that froze time-specific user facts; we don't).
- At inference, the live persona + memory are supplied fresh by the runtime, on top of the
  fine-tuned voice. Evolving persona preserved.

## Prerequisites
- `pip install unsloth trl transformers datasets` (LoRA training stack; already used by the
  legacy scripts).
- **Base weights = HF, not GGUF.** Training needs `Qwen/Qwen3-8B` HF weights (≈16 GB):
  `huggingface-cli download Qwen/Qwen3-8B --local-dir training/base/Qwen3-8B`
  (then pass `--base-model training/base/Qwen3-8B`), or just use the HF id `Qwen/Qwen3-8B`.
- A GPU. The defaults (`--gpu-mem 5.5GiB`, 4-bit, CPU-offload) are tuned for an 8 GB card.

## Run it (3 steps)
```bash
# 1. Extract the voice dataset (persona stays dynamic).
#    --from-db pulls the full turn log (thousands of ELI replies) instead of the few
#    dozen JSON snapshots — VOICE ONLY: it reads exactly one table (conversation_turns);
#    no memories/KG/state. A bad-pattern filter drops error-leakage / confab / fragment
#    replies (bugs, not voice). Add --dry-run first to inspect counts; curate the .jsonl
#    by hand after (delete any remaining off-voice turns).
python training/extract_eli_dataset.py \
    --base-model Qwen/Qwen3-8B \
    --from-db artifacts/db/user.sqlite3 \
    --out training/datasets/eli_voice.jsonl

# 2. Train the LoRA adapter
python training/train_lora.py \
    --base-model Qwen/Qwen3-8B \
    --dataset training/datasets/eli_voice.jsonl \
    --out training/runs/eli-qwen3-8b-lora \
    --max-seq-len 4096 --max-steps 300

# 3. Merge → GGUF → quantize → install into models/
python training/merge_and_convert.py \
    --base-model Qwen/Qwen3-8B \
    --adapter training/runs/eli-qwen3-8b-lora \
    --out-name eli-qwen3-8b --quant q4_k_m
```
Result: `models/eli-qwen3-8b-q4_k_m.gguf`. Load it in ELI (Model menu / Auto Detect) — the
ctx tuner sizes it from its real `n_ctx_train` and keeps the layers on GPU; the dynamic
persona/memory still come from the runtime.

## Manual GGUF conversion (fallback)
If Unsloth's `save_pretrained_gguf` isn't available, merge in Python then convert with
llama.cpp:
```bash
# merge adapter -> 16-bit HF dir (small python: FastLanguageModel.from_pretrained +
#   model.load_adapter(...) ; model.save_pretrained_merged("merged", tok, save_method="merged_16bit"))
python /path/to/llama.cpp/convert_hf_to_gguf.py merged --outfile eli-qwen3-8b-f16.gguf
/path/to/llama.cpp/llama-quantize eli-qwen3-8b-f16.gguf models/eli-qwen3-8b-q4_k_m.gguf Q4_K_M
```

## Tuning knobs (`train_lora.py`)
`--max-seq-len` (4096), `--max-steps` (300), `--lr` (2e-4), `--lora-r/--lora-alpha` (8/16),
`--batch/--grad-accum` (1/8), `--gpu-mem/--cpu-mem`. Start small (a short `--max-steps` smoke
run) to confirm the loop before a full run.

## Verify (after producing the GGUF)
Load it and confirm it (a) holds the full brief at its real ctx, (b) speaks in ELI's voice,
(c) **still respects the dynamic persona overlay/memory** (persona keeps evolving — not
frozen), (d) obeys No-Fake-Actions.

## Supersedes (legacy, kept for reference, not deleted)
`models/extract_training_data*.py`, `models/train_lora_7b*.py`, `models/train_phi3.py` — the
scattered phi-3/7B generations with hardcoded paths and `max_seq_length=1024`. Use this
`training/` pipeline instead.
