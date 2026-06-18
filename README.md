<div align="center">

# ELI MKXI v2.0 PRO

### Your own AI assistant — running entirely on your computer.

No cloud. No accounts. No subscription. No telemetry. Your data never leaves your machine.

![License](https://img.shields.io/badge/license-PolyForm%20Internal%20Use-blue)
![Platform](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Status](https://img.shields.io/badge/100%25-local%20%26%20private-success)
![Models](https://img.shields.io/badge/models-bring%20your%20own%20GGUF-orange)

</div>

---

ELI is a capable AI assistant that you **own and run yourself** — by typing or speaking. It talks
with you, operates your computer, reads your screen and documents, writes and fixes code, and
**learns who you are over time** — all on your own hardware. Think of a private, local alternative
to a cloud assistant: same kind of help, but it's *yours*, it works offline, and nothing is sent
to anyone.

> **New here?** Jump to [What can it do?](#-what-can-it-do) · **Want to install it?** → [Quick Start](#-quick-start) ·
> **Developer?** → [Under the hood](#-under-the-hood)

## Contents
- [What is ELI?](#-what-is-eli)
- [What can it do?](#-what-can-it-do)
- [What makes ELI different](#-what-makes-eli-different)
- [Highlights](#-highlights)
- [Quick Start](#-quick-start)
- [Choose your model](#-choose-your-model)
- [Use it from your phone](#-use-it-from-your-phone)
- [Privacy](#-privacy)
- [Documentation](#-documentation)
- [Under the hood](#-under-the-hood)
- [Security](#-security)
- [License](#-license) · [Contact](#-contact)

---

## 🤖 What is ELI?

**ELI is a private AI that lives entirely on your own computer.** It talks with you, remembers you
across months, runs your machine, sees your screen, reads your files, writes and fixes code, builds
documents from your own evidence — and, uniquely, can **improve its own code** and even **re-train
its own brain on your conversations.** Unlike Siri, Alexa, or ChatGPT, nothing you say has to leave
your house: it's **offline by default, enforced at the network socket itself**, with a switch *you*
control.

It is not a chatbot bolted onto a cloud API. It's ~140,000 lines of Python that form a complete
**cognitive runtime for one person and one machine** — a 12-stage reasoning pipeline, **14 specialist
agents** on a DAG orchestrator, layered memory (SQLite + FAISS vector search + a knowledge graph),
local voice and vision, a desktop GUI, and a phone-friendly web server. **Model-, user-, and
hardware-agnostic.**

> The honest trade: ELI gives up a few IQ points (the price of running on *your* hardware instead of
> a datacentre) in exchange for **total privacy, total ownership, genuine self-honesty, and the
> ability to grow.** That trade is the product.

- **For everyone:** open the app, type or talk — *"play some lo-fi"*, *"what's on my screen?"*,
  *"remember my dog's name is Rufus"*, *"research solar inverters overnight"*. It just works, privately.
- **For developers:** **~110 distinct capabilities** (193 routable actions), grounded/anti-confabulation
  introspection, self-patching with auto-rollback, a real LoRA fine-tuning pipeline, and a socket-level
  offline guard. Source-available — read it, run it, modify it (see [License](#-license)).

## ✨ What can it do?

Real things you can say (it understands many phrasings — these are examples):

| | |
|---|---|
| 🎵 **Music & media** | "play Juicy by Notorious B.I.G. on Spotify" · "pause" · "skip" · "what's playing?" |
| 🪟 **Run your computer** | "open firefox" · "close steam and set an alarm for 7am" · "tile windows" · "volume up" |
| 👁️ **See your screen & files** | "what's on my screen?" · "summarise report.pdf" · "describe this image" · "analyse data.csv" |
| ✍️ **Write & code** | "write a report on solar power" · "write a bash script to monitor the GPU" · "fix the bugs in foo.py" |
| 🧠 **Remember you** | "remember that my sister is Anna" · "what do you know about me?" — a private profile that updates as you talk |
| 🗓️ **Plan & automate** | "set a timer for 10 minutes" · "research the best inverters overnight" · learns your routines and offers to automate them |
| 🌐 **Look things up** | "what's the news?" · "weather in Dublin" · "search the web for X" *(the only time it goes online — and it tells you)* |
| 🎙️ **Hands-free** | wake word "computer", dictation, text-to-speech, and it learns your voice & tone |

Not sure? Just ask it **"what can you do?"** — it lists everything.

<details>
<summary><b>The full breadth — ~110 capabilities across 17 areas</b> (click to expand)</summary>

| Area | What's in it |
|---|---|
| **Conversation & persona** | chat, persona lock, explain-its-last-answer, multi-command chaining |
| **App & window control** | open/close/focus apps, tile/minimise/maximise, workspaces, smart-home |
| **Input & screen control** | volume/mute, type text, mouse move/click, key presses |
| **Gaze (webcam eye-tracking)** | enable/calibrate, click where your eyes rest |
| **Media** | play/pause/skip/shuffle on Spotify or YouTube, "what's playing?", skip ads |
| **Files & documents** | create/read/list, notes, clipboard, summarise, **convert between formats** |
| **Vision & screen** | read your screen, describe images, OCR, analyse PDFs/CSVs, ambient watching |
| **Coding & repair** | solve tasks (plan→verify→repair), fix bugs, examine a codebase, scaffold projects |
| **Generation** | grounded documents/reports from your own evidence, scripts, test data |
| **Memory & identity** | remember facts, recall, a deep sourced profile of what it knows about you |
| **Grounded introspection** | runtime/memory/cognition status reported from *real* evidence, not guessed |
| **Self-maintenance** | analyse failures, self-patch (with rollback), run tests, **LoRA fine-tune itself** |
| **Tasks, time & planning** | alarms, timers, calendar, pomodoro, overnight/scheduled background jobs |
| **Proactive & goals** | morning briefing, learned habits it offers to automate, self-generated proposals |
| **Voice** | wake word (set your own), dictation, TTS, learns your voice & tone |
| **Plugins** | install / enable / disable tools at runtime |
| **System & web** | CPU/RAM/GPU status, time/date, weather, news synthesis, web search (net-gated) |

Every action is real and traceable to code — full per-action reference with example phrases is
generated from the live capability manifest.
</details>

## 💡 What makes ELI different

Most "AI assistants" are a thin app talking to someone else's datacentre. ELI inverts every one of
those assumptions — and that inversion *is* the point:

1. **🔒 It's truly, provably yours.** 100% local. No account, subscription, telemetry, or call-home.
   "Offline" isn't marketing: a process-wide network guard **fail-closes at the socket layer** — with
   the Net switch off, outbound connections physically cannot happen. You hold the switch.

2. **🧠 It owns no brain — so it never goes obsolete.** ELI is **model-agnostic**: no model name or
   size is hardcoded on the inference path. Swap in any local GGUF model and it auto-detects how to
   drive it. As open models get smarter, ELI gets smarter *for free* — no vendor can deprecate it,
   price-hike it, or read over its shoulder.

3. **🔬 It's honest because it measures itself.** Ask most AIs "how does your memory work?" and they
   *invent* an answer. Ask ELI and it reads its **live runtime** — real database counts, the actual
   loaded model, the actual pipeline — and reports from deterministic evidence. A built-in guard also
   means it **never fakes an action**: if it says it did something, it did.

4. **🛠️ It improves itself.** ELI logs its own failures and can **write, syntax-check, apply, and
   auto-roll-back patches to its own code** — safely, in its own project. It can also **fine-tune its
   own model on your conversations** (a real LoRA/PyTorch pipeline), becoming more *you-shaped* over
   time — all on your hardware.

5. **🦾 It has a body, not just a mouth.** It doesn't only answer — it *acts*: opens apps, plays your
   music, manages windows, screenshots, reads your clipboard, understands images and your live screen,
   and can even **click where your eyes are looking** via webcam gaze tracking.

6. **🫂 It actually knows you.** A continuous, semantic user model is read every turn and feeds the
   persona, proactivity, reflection, and memory — so you never repeat yourself, and it adapts to your
   tone and routines.

## 🚀 Highlights

<table>
<tr>
<td valign="top" width="50%">

**Intelligence**
- 12-stage cognition pipeline + **14-agent** DAG orchestrator (parallel, retries, fallback, cache)
- Persistent memory: **SQLite + FAISS vector index + knowledge graph**
- Continuous **User Model** wired into cognition/persona/proactive/reflection
- Code examiner & self-repair (syntax → lint → LLM logic review)
- Proactive daemon (goals, habits, insights) + self-improvement

</td>
<td valign="top" width="50%">

**Runtime & platform**
- **GGUF inference** auto-tuned at boot (CPU & GPU; ctx sized to each model's real `n_ctx_train`)
- **Multi-GPU** (VRAM summed; optional `tensor_split`)
- **Local voice** — faster-whisper STT, wake-word, TTS
- **Self-hosted web app** — reach ELI from your phone over LAN
- One-click installers for **Linux · macOS · Windows**; headless/CLI mode

</td>
</tr>
</table>

## 📦 Quick Start

**Linux / macOS** — `install.sh` gives you a system report → a plan → installs the right CPU/GPU
build → offers to download a model sized to your hardware:

```bash
git clone https://github.com/ShadowESC95/ELI_MKXI_v2.0_PRO.git
cd ELI_MKXI_v2.0_PRO
bash install.sh                 # interactive: report → plan → install → pick model(s)
./scripts/eli_launch.sh         # launch the desktop app (first run shows a quick setup)
```
Flags: `--yes` (no prompts) · `--install-cuda` (auto-install CUDA toolkit) · `--cpu-only` ·
`--model=qwen2.5-7b` / `--no-model`.

**Windows** (double-click `install.bat`, or PowerShell):
```powershell
.\install.bat            # CUDA + frozen lock + GPU verify
.\eli.bat                # launch
```

That's it — the first run is a **blank slate** (no preloaded data) with a 10-second, skippable
"what should I call you?" intro.

## 🧠 Choose your model

ELI needs one local **model** (the brain). The installer offers to fetch one sized to your
hardware, or pick your own — you can grab several and switch anytime:

```bash
python -m eli.core.model_download --choose   # multi-select menu — pick ANY number
python -m eli.core.model_download --auto      # one best-fit for your VRAM
```

| key | model | size | needs |
|---|---|---|---|
| `qwen2.5-3b` | Qwen2.5-3B-Instruct | ~1.8 GB | 4 GB GPU / CPU |
| `qwen2.5-7b` | Qwen2.5-7B-Instruct *(default)* | ~4.4 GB | 8 GB GPU |
| `qwen3-8b` | Qwen3-8B (40K ctx, reasoning; LoRA base) | ~4.7 GB | 8 GB GPU |
| `falcon3-10b` | Falcon3-10B-Instruct | ~5.9 GB | 12 GB GPU |
| `phi-4` | Phi-4 (14B dense, MIT) | ~8.4 GB | 12 GB GPU |
| `qwen3.6-35b-a3b` | Qwen3.6-35B-A3B (MoE, Apache-2.0) | ~20.6 GB | 24 GB GPU / CPU |
| `falcon-h1-34b` | Falcon-H1-34B-Instruct | ~18.9 GB | 24 GB GPU / CPU |

You can also drop **any `.gguf`** into `models/`, or point ELI at your own catalog
(`ELI_MODEL_CATALOG`). The tiny **embedder** (memory/RAG) installs automatically; vision is an
optional extra. Want ELI to *speak in its own voice* out of the box? Fine-tune your own model —
see **[`docs/TRAINING_YOUR_OWN_MODEL.md`](docs/TRAINING_YOUR_OWN_MODEL.md)**.

## 📱 Use it from your phone

ELI includes a built-in web app. Run the server on a machine that can do the thinking (your
desktop), then chat from your phone's browser over your home Wi-Fi — inference stays on the host,
nothing reaches the cloud. **Safe by default** (loopback-only) until you explicitly expose it:

```bash
./scripts/eli_serve.sh             # local only  → http://127.0.0.1:8081/
./scripts/eli_serve.sh --lan       # phone access → prints a token-protected URL
```
Works on Android, iOS, and desktop with zero native build. Details:
**[`docs/SERVER_AND_WEB_APP.md`](docs/SERVER_AND_WEB_APP.md)**.

## 🔒 Privacy

Nothing leaves your computer unless you ask for something online (news, search, downloading a
model) — and ELI tells you when it does. No accounts, no telemetry, no subscription. A fresh
install knows **nothing** about you until you talk to it, and you can delete your data anytime.

## 📚 Documentation

- **[Server & Web App](docs/SERVER_AND_WEB_APP.md)** — self-hosted FastAPI server + phone/web UI
- **[Train your own model](docs/TRAINING_YOUR_OWN_MODEL.md)** — A-to-Z LoRA/QLoRA into an ELI GGUF
- **[Cross-platform coverage](docs/CROSS_PLATFORM.md)** — capability × platform matrix
- **[Model runtime policy](docs/model_runtime_policy.md)** — how ctx/layers/batch are sized

## 🛠 Under the hood

<details>
<summary><b>Architecture / project layout</b></summary>

- `eli/core` — paths, settings, contracts, hardware profile
- `eli/kernel` — control loop, cognitive engine, state models
- `eli/cognition` — reasoning, grounding, agent bus, working memory
- `eli/memory` — episodic, semantic, FAISS vector index, knowledge graph
- `eli/planning` — goals, jobs, autonomy, proactive daemon, scheduling
- `eli/execution` — router, executor, tool authority, shell security gate
- `eli/perception` — audio, screenshots, OS controller, TTS/STT
- `eli/runtime` — arbitration, verification, security policy
- `eli/plugins` — tool plugins (install/enable/disable at runtime)
- `eli/gui` — PySide6 GUI launcher and `EliMainWindow`
- `eli/cli` — headless REPL (`eli --headless`)
- `config` — portable default settings · `models` — local GGUF payloads (gitignored)
- `tests` — pytest suite (6,800+ tests across 160+ files)

**Scaling:** the loader reads each model's real `n_ctx_train` from GGUF metadata and fits
layers/batch/ctx to the hardware present; VRAM is summed across all GPUs. One path runs a 3B on a
laptop and a 35B on a workstation. Multi-GPU: enable a profile in `config/gpu_profiles.json` or set
`tensor_split`. Always local, never cloud, at every size.
</details>

<details>
<summary><b>Developer setup (from a source checkout)</b></summary>

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-full.txt
python -m pip install -e .[full]
python -m eli            # GUI   ·   python -m eli --headless   # terminal REPL
```
Per-platform requirement profiles: `requirements.lock.txt` (frozen, reproducible),
`requirements-windows.txt`, `requirements-macos.txt`, `requirements-android.txt`,
`requirements-full.txt`. Headless slash commands: `/status`, `/mode`, `/reset`, `/help`, `/quit`.

Use the path helpers in `eli.core.paths` (`project_root`, `data_dir`, `models_dir`,
`user_db_path`, …) instead of hard-coded machine paths — the repo is designed to be movable.
Most users leave `ELI_PROJECT_ROOT` unset (auto-detected). Env reference: `.env.example`,
`.env.full.example`.
</details>

<details>
<summary><b>Packaging & releases</b></summary>

```bash
bash scripts/package_eli_release.sh                 # wheel/sdist
bash scripts/package_desktop_app.sh                 # portable Linux desktop package
bash build_packages.sh wheel deb appimage macos windows
```
A real Windows `.exe`/`.msi` must be built on Windows; a signed/notarized macOS `.dmg` on macOS.
Large model/voice binaries are distributed separately (GitHub Release assets) via
`scripts/upload_github_asset_files.py` / `restore_github_asset_files.py` — they exceed Git's
100 MB blob limit.
</details>

<details>
<summary><b>Cross-platform limits</b></summary>

Guards + aliases cover Windows, macOS, Linux, BSD, and Android/Termux, but no package makes every
OS permission instant: Windows may need SmartScreen approval + audio/COM packages; macOS needs
Screen-Recording/Accessibility permissions; Linux desktop control depends on Wayland/X11 +
PulseAudio/PipeWire; Android/Termux is headless-only; GPU acceleration depends on local
drivers/CUDA/Metal. Full matrix: **[`docs/CROSS_PLATFORM.md`](docs/CROSS_PLATFORM.md)**.
</details>

## 🛡 Security

Defence-in-depth, all local:

| Layer | Protects against |
|---|---|
| Prompt-injection guard | Strips `[INST]`, `<\|im_start\|>system`, jailbreak phrases before the model sees input |
| SQL identifier validation | Allowlist regex on every f-string SQL identifier — no injection via table/column names |
| Shell security gate | `RUN_CMD` is **fail-closed**: blocked unless allowlisted; destructive patterns (`rm -rf /`, `mkfs`, fork bombs) denied even then |
| Custom-agent trust | SHA-256 registry — unregistered/tampered agent files are skipped at load |
| Offline-by-default | A process-wide network guard fails closed unless a task is explicitly authorised online |

## 📄 License

ELI MKXI is **source-available, not open-source**, under the
**[PolyForm Internal Use License 1.0.0](LICENSE)** — © 2026 Jason Fitzgibbon Bridgeman.

| You **may** | You **may not** |
|---|---|
| Download, read, run, and **modify** the source | **Redistribute**, share, publish, or sublicense it |
| Use it for your own internal / personal purposes | **Host it as a service** for others |
| Keep your own private modifications | **Sell** it or any modified version |

All commercial and distribution rights are reserved by the copyright holder. For anything beyond
that — redistribution, hosting, or a commercial license — please get in touch. Provided "as is",
without warranty.

> **Why source-available?** To put a genuinely capable, fully-local AI assistant in people's hands
> to *use and learn from* — while keeping the right to steward the project rather than have it
> taken closed and resold.

## 📬 Contact

Questions, feedback, or interested in a license/services beyond the terms above?

- 📧 **Email:** [jaybridgeman0095@gmail.com](mailto:jaybridgeman0095@gmail.com)
- 🐙 **GitHub:** [@ShadowESC95](https://github.com/ShadowESC95) ·
  [open an issue](https://github.com/ShadowESC95/ELI_MKXI_v2.0_PRO/issues)

For commercial licensing, redistribution rights, or hosting beyond the
[license](LICENSE), please reach out by email.
