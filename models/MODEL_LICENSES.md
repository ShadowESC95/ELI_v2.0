# Model & Voice License Manifest — ELI v2.0

ELI distributes **third-party** GGUF, embedding, vision, and Piper voice files
separately from source (GitHub Release assets — tag `local-assets-v2.1`)
because they exceed git size limits. ELI's own code is Apache-2.0 from v2.5.36;
that licence does not extend to these files. Each keeps its upstream licence,
some of them non-commercial, and **you are responsible for complying with each
upstream license** when you download, use or pass on these files.

This manifest covers the installer catalog (`eli/core/model_download.py`),
the **`local-assets-v2.1` GitHub Release pack**, what the release builds bundle,
default voice assets, and restore exclusions enforced by
`scripts/asset_release_policy.py`. Upstream licences were read from each
model's Hugging Face card or voice `MODEL_CARD` on 2026-11-20; read the upstream
terms yourself before relying on them.

---

## GitHub Release pack (`local-assets-v2.1`)

Files at the release root (flat layout). Restore via:

`./RUN_ELI.sh --with-github-assets` (portable package) or `scripts/restore_github_asset_files.py`

### Required auxiliary

| File | Upstream | License |
|---|---|---|
| `nomic-embed-text-v1.5.Q4_K_M.gguf` | [nomic-ai/nomic-embed-text-v1.5-GGUF](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF) | Apache-2.0 |

**Required for memory / RAG / research vector search.** Also auto-fetched by `install.sh`
from Hugging Face when network is allowed, and bundled in every release build.

### Starter chat GGUF (pick one or more)

| File | Upstream | License | Notes |
|---|---|---|---|
| `tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf` | [TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF](https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF) | Apache-2.0 | TinyLlama base |
| `SmolLM2-1.7B-Instruct-Q4_K_M.gguf` | [HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF) | Apache-2.0 | |
| `DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf` | [deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B) | MIT | Community GGUF quantisation of DeepSeek's model |
| `ministral-3b-instruct-q4_k_m.gguf` | [ministral/Ministral-3b-instruct](https://huggingface.co/ministral/Ministral-3b-instruct) | Apache-2.0 | A community model (Llama architecture), not a Mistral AI release; the file's own metadata says `apache-2.0` |
| `Palmyra-mini-Q8_0.gguf` | [Writer/palmyra-mini-GGUF](https://huggingface.co/Writer/palmyra-mini-GGUF) | Apache-2.0 | Writer |

7B+ chat models are **not** on this tag (GitHub 2 GB/file limit). Use `install.sh` or
copy your own `.gguf` into `models/`.

### Piper voices on the release (auto-restore)

All twelve are also **bundled in every release build** (Windows, macOS, AppImage) and
in the portable tarball (`packaging/ci_fetch_assets.sh` downloads every voice on the
pack). Licences are those of each voice's dataset, as its upstream `MODEL_CARD` states
them ([rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)):

| Voice | Dataset licence (upstream card) | Auto-restore |
|---|---|---|
| `en_US-amy-medium` | "See URL" (MycroftAI/mimic3-voices) | **Yes** (ELI default TTS) |
| `en_GB-alan-medium` | "See URL" (mimic3-voices `en_UK/apope_low`, whose LICENSE reads "Copyright 2022 Mycroft AI, All Rights Reserved") | Yes |
| `en_GB-northern_english_male-medium` | CC BY-SA 4.0 (OpenSLR 83) | Yes |
| `de_DE-thorsten-medium` | CC0 | Yes |
| `fr_FR-siwis-medium` | CC BY 4.0 | Yes |
| `es_ES-carlfm-x_low` | Public domain | Yes |
| `it_IT-riccardo-x_low` | "See URL" (M-AILABS speech dataset) | Yes |
| `cs_CZ-jirka-medium` | CC0 | Yes |
| `nl_NL-mls-medium` | CC BY 4.0 (OpenSLR 94) | Yes |
| `pl_PL-gosia-medium` | CC0 | Yes |
| `ru_RU-ruslan-medium` | **CC BY-NC-SA 4.0 — non-commercial** (RUSLAN corpus) | Yes |
| `zh_CN-huayan-x_low` | **Unknown** (the card states none) | Yes |

The cards above are the current upstream ones; the pack's files are the older Piper
1.0 / 0.2 builds of the same voices.

### Voices excluded from auto-restore (`--with-github-assets`)

These are **not published** in the `local-assets-v2.1` asset release at all, and ELI
**also** skips them during restore if they are ever present — `RESTRICTED_VOICE_NAMES`
in `eli/runtime/voice_assets.py` (mirrored by `scripts/asset_release_policy.py`)
excludes every quality variant of these voices by name, so the exclusion holds even
for a hand-placed file:

| Voice | Reason |
|---|---|
| `en_US-ryan-*` (`-high`, `-medium`, …) | CC BY-NC-SA 4.0 upstream — non-commercial |
| `en_US-lessac-*` | Blizzard 2013 Lessac dataset licence — not cleared for public bundle |
| `en_GB-cori-*` | LibriVox (the card says public domain) — clearance pending; use `en_US-amy-medium` out of the box |

Install cleared voices only, or fetch alternatives from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) directly.

---

## Chat GGUF models (installer catalog)

| Key | Upstream | License | Redistribution |
|---|---|---|---|
| `qwen2.5-3b` | [bartowski/Qwen2.5-3B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF) | **Qwen Research License — non-commercial** (research or evaluation only) | HF GGUF community repacks — verify model card |
| `qwen2.5-7b` | [bartowski/Qwen2.5-7B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF) | Apache-2.0 | Same |
| `qwen3-8b` | [bartowski/Qwen_Qwen3-8B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3-8B-GGUF) | Apache-2.0 | Same |
| `falcon3-10b` | [bartowski/Falcon3-10B-Instruct-GGUF](https://huggingface.co/bartowski/Falcon3-10B-Instruct-GGUF) | **TII Falcon License** — read upstream terms | Same |
| `phi-4` | [bartowski/phi-4-GGUF](https://huggingface.co/bartowski/phi-4-GGUF) | MIT (Microsoft Phi-4) | Same |
| `qwen3.6-35b-a3b` | [unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) | Apache-2.0 | Same |
| `falcon-h1-34b` | [tiiuae/Falcon-H1-34B-Instruct-GGUF](https://huggingface.co/tiiuae/Falcon-H1-34B-Instruct-GGUF) | **TII Falcon License** — read upstream model card | Verify before commercial use |

These are downloaded by the user from Hugging Face; the release builds bundle none of them. A
portable package built with `scripts/package_desktop_app.sh` bundles one as its starter only
when its licence is open (Apache-2.0 or MIT, `OPEN_LICENSES` in `eli/core/model_download.py`),
unless `ELI_STARTER_MODEL` names another.

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
| **Piper** `en_US-amy-medium` (default TTS) | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) | See the voice table above |
| **openWakeWord** models (inside the `openwakeword` package) | [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord) | Code Apache-2.0; its pre-trained models CC BY-NC-SA 4.0 per its own licence note. ELI uses only the feature-extractor models and trains its own detector head; the release builds carry those two and none of the pre-trained wake-word models. `embedding_model.onnx` is openWakeWord's re-implementation of Google's speech_embedding model, which Google publishes under Apache-2.0; openWakeWord's note does not say whether its CC BY-NC-SA terms cover that re-implementation |

See `packaging/VOICE_LICENSE_REVIEW.md` for maintainer voice classifications.

---

## Vendored tokenizer / config (in git, not weights)

| Path | License |
|---|---|
| `models/phi-3-mini-base/` | MIT — see `models/phi-3-mini-base/LICENSE` |
| `models/image/ssd-1b/` (configs and tokenizers) | Apache-2.0 (SSD-1B card) |

Weight files for Phi-3 are **not** committed; download separately under Microsoft terms.

---

## Image generation (optional)

| Model | Upstream | License |
|---|---|---|
| SSD-1B (fetched on demand) | [segmind/SSD-1B](https://huggingface.co/segmind/SSD-1B) | Apache-2.0 |

---

## Style presets vs character impersonation (public releases)

ELI ships **five built-in style presets** (`char:calm`, `char:robotic`, `char:energetic`, `char:synthetic`, `char:refined`): bundled Piper voices (`en_GB-alan-medium`, `en_GB-northern_english_male-medium`, `en_US-amy-medium`) + ffmpeg effects (`eli/perception/voice_fx.py`). We **do not** bundle neural clones or marketing labels for copyrighted characters (HAL 9000, JARVIS, Rick Sanchez, TARS, GLaDOS, etc.) in GitHub releases or installers — that would be legally unsafe and technically misleading (the old named presets used unshippable base voices and sounded identical anyway).

Users who want a specific timbre may:
- tune or add their own `char:<name>` preset in `config/voices/characters.json`, or
- use **local voice cloning** (XTTS-v2 opt-in, source installs; the XTTS-v2 weights are under the non-commercial Coqui Public Model License) from **reference audio they have rights to use**.

Persona / communication-style commands change **wording**, not the TTS timbre.

---

## Maintainer release checklist

1. Attach **this file** to every model/voice GitHub Release (`MODEL_LICENSES.md`).
2. Do not upload `--include-runtime` or `--include-venv` private data.
3. Do not auto-restore voices in `RESTRICTED_VOICE_NAMES` (ryan, lessac, cori).
4. Default TTS remains `en_US-amy-medium` (install + GitHub pack).
5. Read a voice's upstream `MODEL_CARD` before adding it to the pack: every voice on it
   reaches every user of the release builds.
