# Model & Voice License Manifest — ELI v2.0

ELI distributes **third-party** GGUF, embedding, vision, and Piper voice files
separately from source (GitHub Release assets — tag e.g. `local-assets-v2.1`)
because they exceed git size limits. **You are responsible for complying with
each upstream license** when you download or use these files.

This manifest covers the curated catalog in `eli/core/model_download.py`,
default voice assets, and common bundled release files.

---

## Chat GGUF models (installer catalog)

| Key | Upstream | License | Redistribution |
|---|---|---|---|
| `qwen2.5-3b` | [bartowski/Qwen2.5-3B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF) | Apache-2.0 (Qwen2.5) | HF GGUF community repacks — verify model card |
| `qwen2.5-7b` | [bartowski/Qwen2.5-7B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF) | Apache-2.0 | Same |
| `qwen3-8b` | [bartowski/Qwen_Qwen3-8B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-8B-GGUF) | Apache-2.0 | Same |
| `falcon3-10b` | [bartowski/Falcon3-10B-Instruct-GGUF](https://huggingface.co/bartowski/Falcon3-10B-Instruct-GGUF) | Apache-2.0 (Falcon3) | Same |
| `phi-4` | [bartowski/phi-4-GGUF](https://huggingface.co/bartowski/phi-4-GGUF) | MIT (Microsoft Phi-4) | Same |
| `qwen3.6-35b-a3b` | [unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) | Apache-2.0 | Same |
| `falcon-h1-34b` | [tiiuae/Falcon-H1-34B-Instruct-GGUF](https://huggingface.co/tiiuae/Falcon-H1-34B-Instruct-GGUF) | **TII Falcon License** — read upstream model card | Verify before commercial use |

---

## Auxiliary models (auto-downloaded)

| Key | Upstream | License |
|---|---|---|
| `embedder` (nomic-embed-text-v1.5) | [nomic-ai/nomic-embed-text-v1.5-GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF) | Apache-2.0 |
| `vision` (Qwen2.5-VL-7B) | [unsloth/Qwen2.5-VL-7B-Instruct-GGUF](https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF) | Apache-2.0 |
| `vision-mmproj` | Same repo | Apache-2.0 |

---

## Speech models

| Asset | Upstream | License |
|---|---|---|
| **faster-whisper** `small.en` (STT weights) | [Systran/faster-whisper-small.en](https://huggingface.co/Systran/faster-whisper-small.en) | MIT |
| **Piper** `en_US-amy-medium` (default TTS fetch) | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) | See per-voice model card (typically CC BY 4.0) |

### Bundled voice pack (`tts_piper/`) — review before wide redistribution

| Voice | Classification | Notes |
|---|---|---|
| `en_GB-cori-high` | Review before ship | LibriVox-derived dataset per upstream card — retain evidence |
| `en_US-lessac-high` | **License review required** | Blizzard 2013 Lessac dataset — check upstream MODEL_CARD |
| `en_US-ryan-high` | **Non-commercial risk** | Upstream CC BY-NC-SA 4.0 — **exclude from commercial bundles** |

See `packaging/VOICE_LICENSE_REVIEW.md` for maintainer guidance.

---

## Vendored tokenizer / config (in git, not weights)

| Path | License |
|---|---|
| `models/phi-3-mini-base/` | MIT — see `models/phi-3-mini-base/LICENSE` |

Weight files for Phi-3 are **not** committed; download separately under Microsoft terms.

---

## Image generation (optional)

| Model | Upstream | License |
|---|---|---|
| SSD-1B (fetched on demand) | [segmind/SSD-1B](https://huggingface.co/segmind/SSD-1B) | See HF model card |

---

## Maintainer release checklist

1. Attach this file to every model/voice GitHub Release.
2. Do not upload `--include-runtime` or `--include-venv` private data (see `scripts/upload_github_asset_files.py`).
3. Exclude `en_US-ryan-high` from any commercial redistribution unless legally cleared.

Questions: **jaybridgeman0095@gmail.com**
