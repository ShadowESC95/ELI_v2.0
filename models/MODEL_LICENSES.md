# Model & Voice License Manifest — ELI v2.0

ELI distributes **third-party** GGUF, embedding, vision, and Piper voice files
separately from source (GitHub Release assets — tag `local-assets-v2.1`)
because they exceed git size limits. **You are responsible for complying with
each upstream license** when you download or use these files.

This manifest covers the installer catalog (`eli/core/model_download.py`),
the **`local-assets-v2.1` GitHub Release pack**, default voice assets, and
restore exclusions enforced by `scripts/asset_release_policy.py`.

---

## GitHub Release pack (`local-assets-v2.1`)

Files at the release root (flat layout). Restore via:

`./RUN_ELI.sh --with-github-assets` or `scripts/restore_github_asset_files.py`

### Required auxiliary

| File | Upstream | License |
|---|---|---|
| `nomic-embed-text-v1.5.Q4_K_M.gguf` | [nomic-ai/nomic-embed-text-v1.5-GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF) | Apache-2.0 |

**Required for memory / RAG / research vector search.** Also auto-fetched by `install.sh`
from Hugging Face when network is allowed.

### Starter chat GGUF (pick one or more)

| File | Upstream | License | Notes |
|---|---|---|---|
| `tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf` | [TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF) | Apache-2.0 | TinyLlama base |
| `SmolLM2-1.7B-Instruct-Q4_K_M.gguf` | [HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF) | Apache-2.0 | |
| `DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf` | [deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B-GGUF](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B-GGUF) | [DeepSeek License](https://github.com/deepseek-ai/DeepSeek-R1/blob/main/LICENSE) | Read upstream terms |
| `ministral-3b-instruct-q4_k_m.gguf` | [mistralai/Ministral-3B-Instruct-GGUF](https://huggingface.co/mistralai/Ministral-3B-Instruct-GGUF) | Apache-2.0 | Mistral AI |
| `Palmyra-mini-Q8_0.gguf` | [Writer/palmyra-mini-GGUF](https://huggingface.co/Writer/palmyra-mini-GGUF) | **Writer / Palmyra terms** — read HF model card | Verify before commercial use |

7B+ chat models are **not** on this tag (GitHub 2 GB/file limit). Use `install.sh` or
copy your own `.gguf` into `models/`.

### Piper voices on the release (auto-restore)

| Voice | Upstream | License | Auto-restore |
|---|---|---|---|
| `en_US-amy-medium` | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) | Per voice card (typically CC BY 4.0) | **Yes** (ELI default TTS) |
| `en_GB-alan-medium` | rhasspy/piper-voices | Per voice card | Yes |
| `en_GB-cori-high` | rhasspy/piper-voices | LibriVox-derived dataset per card — retain evidence | Yes |
| `en_GB-northern_english_male-medium` | rhasspy/piper-voices | Per voice card | Yes |
| `de_DE-thorsten-medium`, `fr_FR-siwis-medium`, `es_ES-carlfm-x_low`, `it_IT-riccardo-x_low`, `cs_CZ-jirka-medium`, `nl_NL-mls-medium`, `pl_PL-gosia-medium`, `ru_RU-ruslan-medium`, `zh_CN-huayan-x_low` | rhasspy/piper-voices | Per voice card | Yes |

### Voices excluded from auto-restore (`--with-github-assets`)

These may still exist as **manual** downloads on the release page for advanced users,
but ELI **skips** them during restore (see `EXCLUDED_VOICE_BASENAMES`):

| Voice | Reason |
|---|---|
| `en_US-ryan-high`, `en_US-ryan-medium` | CC BY-NC-SA 4.0 upstream — non-commercial |
| `en_US-lessac-high`, `en_US-lessac-medium` | Blizzard 2013 Lessac dataset — redistribution not cleared for public bundle |

Install cleared voices only, or fetch alternatives from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) directly.

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

## Auxiliary models (auto-downloaded via `model_download --aux`)

| Key | Upstream | License |
|---|---|---|
| `embedder` (nomic-embed-text-v1.5) | [nomic-ai/nomic-embed-text-v1.5-GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF) | Apache-2.0 |
| `vision` (Qwen2.5-VL-7B) | [unsloth/Qwen2.5-VL-7B-Instruct-GGUF](https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF) | Apache-2.0 |
| `vision-mmproj` | Same repo | Apache-2.0 |

---

## Speech models (runtime fetch)

| Asset | Upstream | License |
|---|---|---|
| **faster-whisper** `small.en` (STT weights) | [Systran/faster-whisper-small.en](https://huggingface.co/Systran/faster-whisper-small.en) | MIT |
| **Piper** `en_US-amy-medium` (default TTS) | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) | Per voice card (typically CC BY 4.0) |

See `packaging/VOICE_LICENSE_REVIEW.md` for maintainer voice classifications.

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

1. Attach **this file** to every model/voice GitHub Release (`MODEL_LICENSES.md`).
2. Do not upload `--include-runtime` or `--include-venv` private data.
3. Do not auto-restore voices in `EXCLUDED_VOICE_BASENAMES` (ryan, lessac).
4. Default TTS remains `en_US-amy-medium`.

Questions: **jaybridgeman0095@gmail.com**
