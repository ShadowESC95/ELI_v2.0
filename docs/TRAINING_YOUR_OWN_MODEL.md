# Training your own ELI model (LoRA / QLoRA) — A to Z

This guide fine-tunes a base model into an **ELI-native substrate** — teaching ELI's *voice and
behavioural contracts*, then producing a GGUF you drop into `models/`. It's the meticulous,
reason-from-it version; the quick command card is in `training/README.md`.

> **The one rule — persona stays dynamic.** ELI's persona is *dynamic, self-updating, and lives
> in the runtime* (`persona_updater` + the per-turn memory brief + the continuous User Model).
> So this trains **only the stable layer — ELI's voice/manner and contracts** — and **does NOT
> bake persona state, your name, or your memories into the weights.** Those stay in the runtime
> and are supplied fresh at inference. Freezing them into weights would make ELI confidently
> stale and kill the self-updating persona. Everything below preserves that.

---

## 0. What you are (and aren't) doing
- **Fine-tune, not pre-train.** You're nudging an already-capable model's *style*, not teaching
  it new world knowledge (that's what ELI's RAG/memory is for).
- **LoRA/QLoRA, not full fine-tune.** You train a small low-rank adapter (a few hundred MB) on
  a 4-bit-quantized base — feasible on a single consumer GPU.
- **Voice + contracts, not facts.** The dataset is ELI's *replies* (how it talks), with
  memory/state deliberately excluded.

## 1. Pick a base model
**Default: `Qwen/Qwen3-8B`** — it won ELI's bake-off, its 40,960 context comfortably holds ELI's
brief, and at 4-bit it fits an 8 GB card.
- **8 GB GPU is tight** for an 8B QLoRA (the scripts default to `--gpu-mem 5.5GiB` + CPU offload).
  If it crawls, use **`Qwen/Qwen3-4B`** (same commands) — far faster, still ≥16k context.
- Avoid tiny-context models (e.g. a 4k model) — they can't hold ELI's prompt and produce garbage.

## 2. Install the training stack (one-time, opt-in)
```bash
.venv/bin/pip install -e ".[training]"     # torch, transformers, peft, datasets, trl
.venv/bin/pip install unsloth              # fast QLoRA (pulls bitsandbytes/accelerate)
```
You also need a GGUF toolchain for the final convert/quantize: a local `llama.cpp` checkout
(for `convert_hf_to_gguf.py` + `llama-quantize`) — or Unsloth's one-shot `save_pretrained_gguf`.

## 3. Get the BASE weights (HF format — not a GGUF)
Training needs the unquantized Hugging Face weights, which are *separate* from the inference GGUF:
```bash
.venv/bin/huggingface-cli download Qwen/Qwen3-8B --local-dir training/base/Qwen3-8B
```
(~16 GB. Then pass `--base-model training/base/Qwen3-8B`, or just use the HF id `Qwen/Qwen3-8B`.)

## 4. Build the voice dataset (persona stays dynamic)
The extractor pulls ELI's **actual replies** and formats them with the model's chat template —
**voice only, state excluded.**
```bash
.venv/bin/python training/extract_eli_dataset.py \
    --base-model training/base/Qwen3-8B \
    --from-db artifacts/db/user.sqlite3 \
    --out training/datasets/eli_voice.jsonl
```
- **`--from-db`** reads the `conversation_turns` table (thousands of turns) — *only* that table;
  no `memories`, no KG, no profile, no system-prompt state injection.
- A **bad-pattern filter** (on by default) drops replies that are bugs, not voice: surfaced
  runtime errors (`GGUF streaming failed`, `exceed context window`), tracebacks, shell bleed, and
  world-room confabulations. `--keep-bad` disables it.
- `--system-mode none` (default) teaches the register from replies; `--dry-run` shows counts
  without writing.

### 4a. Curate (the step that actually decides quality)
Open `eli_voice.jsonl` and **delete the off-voice turns** — anything where ELI babbled,
fabricated an action, or yes-manned. The model imitates whatever you feed it; **50 clean
exchanges beat 500 dirty ones.** This is where your effort matters, not the hyperparameters.

## 5. Smoke-test the loop (catch errors before the hours)
```bash
.venv/bin/python training/train_lora.py \
    --base-model training/base/Qwen3-8B \
    --dataset training/datasets/eli_voice.jsonl \
    --out training/runs/eli-smoke \
    --max-seq-len 4096 --max-steps 10
```
If 10 steps complete and a loss prints, the pipeline works.

## 6. Train the adapter
```bash
.venv/bin/python training/train_lora.py \
    --base-model training/base/Qwen3-8B \
    --dataset training/datasets/eli_voice.jsonl \
    --out training/runs/eli-qwen3-8b-lora \
    --max-seq-len 4096 --max-steps 300
```
Defaults: LoRA `r=8` / `alpha=16`, `lr=2e-4`, 4-bit nf4 + CPU offload.

| Knob | Default | When to change |
|---|---|---|
| `--max-steps` | 300 | More data → more steps; watch the loss (below). |
| `--lr` | 2e-4 | Lower (1e-4) if loss is unstable. |
| `--lora-r` / `--lora-alpha` | 8 / 16 | Raise r (16/32) for a stronger imprint; lower if it overfits. |
| `--max-seq-len` | 4096 | Cover your longest representative ELI turns. |
| `--gpu-mem` / `--cpu-mem` | 5.5GiB / 20GiB | Tune for your card. |

**Reading the loss:** it should drift down to ~0.8–1.2 and flatten. If it dives toward ~0.1
you're **overfitting** (memorizing) — cut `--max-steps` or lower `r`.

## 7. Merge → GGUF → quantize → install
```bash
.venv/bin/python training/merge_and_convert.py \
    --base-model Qwen/Qwen3-8B \
    --adapter training/runs/eli-qwen3-8b-lora \
    --out-name eli-qwen3-8b --quant q4_k_m
```
Produces `models/eli-qwen3-8b-q4_k_m.gguf`. If Unsloth's one-shot GGUF export isn't available,
`training/README.md` has the manual `llama.cpp` `convert_hf_to_gguf.py` + `llama-quantize` path.

## 8. Load it in ELI
Pick it in the startup model picker (or Model menu / Auto-Detect). ELI's context tuner sizes it
from its real `n_ctx_train` (40,960 → requests ~16k, all layers on an 8 GB card, no brief
truncation); the **dynamic persona + memory + User Model come from the runtime** on top of the
fine-tuned voice.

## 9. Verify — check behaviour, not the loss
1. **Voice** — sounds like ELI (dry, direct, no corporate filler).
2. **Contracts hold** — doesn't fake actions; doesn't yes-man.
3. **Persona still dynamic** — adapts to new memory / the User Model; not frozen to training-day
   facts.
4. **No capability regression** — routing/commands still work.

## 10. Troubleshooting
| Symptom | Cause | Fix |
|---|---|---|
| OOM during training | 8 GB + 8B too tight | lower `--gpu-mem`, or use Qwen3-4B |
| Garbage output after load | ctx/template mismatch or a too-small base | use a ≥16k base; confirm the GGUF's chat template |
| Replies are stiff / robotic | overfit / too few examples | fewer steps, lower `r`, add cleaner data |
| ELI repeats canned lines | trained on low-variety data | curate (step 4a), add diverse turns |
| Fabricates actions | trained on buggy replies | keep the bad-pattern filter on; curate harder |

## 11. Why this stays ELI
The fine-tune **reinforces voice**; the runtime **enforces behaviour** (No-Fake-Actions guard,
grounding, the dynamic persona/User Model). They're complementary — never bake the persona into
the weights. A stock Qwen3-8B already runs ELI well; the LoRA is *polish* (a more consistent
register and tighter contract-adherence), not a dependency.

## 12. Files
- `training/extract_eli_dataset.py` — voice dataset extractor (`--from-db`, filtered, state-excluded).
- `training/train_lora.py` — QLoRA trainer (Unsloth + TRL).
- `training/merge_and_convert.py` — merge adapter → GGUF → quantize → install in `models/`.
- `training/README.md` — quick command card.
