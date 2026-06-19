<div align="center">

# ELI MKXI v2.0 PRO

**A strictly local, private AI assistant and cognitive runtime.**

Everything runs on your own machine — the model, your data, and all processing. Nothing is ever
sent to a server. No cloud, no accounts, no telemetry. Offline by default, enforced at the network socket.

![License](https://img.shields.io/badge/license-PolyForm%20Internal%20Use-blue)
![Platform](https://img.shields.io/badge/platform-Linux%20·%20macOS%20·%20Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Offline](https://img.shields.io/badge/network-offline%20by%20default-informational)
![Models](https://img.shields.io/badge/models-local%20GGUF-orange)
[![Support on Ko-fi](https://img.shields.io/badge/support-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/shadowesc95)

</div>

---

ELI is an AI assistant you run **entirely on your own machine**. It holds a conversation, operates
your computer, reads your screen and documents, writes and repairs code, and builds a private model
of who you are over time — by typing or speaking. The model and every byte of your data live and
stay on your hardware; there is no cloud component and no account. It is offline by default and
enforces that at the network socket, and it loads a local model of your choosing, auto-tuned to your
hardware from a laptop to a multi-GPU workstation.

## Contents
- [What is ELI?](#what-is-eli)
- [What it does](#what-it-does)
- [Design principles](#design-principles)
- [Features](#features)
- [Quick Start](#quick-start)
- [Choose your model](#choose-your-model)
- [Optional: a remote view over your own network](#optional-a-remote-view-over-your-own-network)
- [Privacy](#privacy)
- [Documentation](#documentation)
- [Under the hood](#under-the-hood)
- [Security](#security)
- [Project status & contributing](#project-status--contributing)
- [License](#license) · [Contact](#contact)

---

## What is ELI?

ELI is not a chatbot wrapped around a cloud API. It is a complete, self-contained local cognitive
runtime — ~140,000 lines of Python implementing a 12-stage reasoning pipeline, 14 specialist agents
on a DAG orchestrator, layered memory (SQLite + a FAISS vector index + a knowledge graph), local
voice and vision, and a desktop GUI. It is model-, user-, and hardware-agnostic, and it runs with no
external service of any kind.

Beyond answering questions, it acts on your machine, remembers you across sessions, reports its own
state from real runtime evidence rather than guessing, and can modify its own source code and
fine-tune its model on your conversation history. **208 capabilities** sit behind a single typed or
spoken interface.

The trade-off is deliberate and stated plainly: a model running on local hardware is less capable
than a large cloud model, in exchange for privacy, ownership, offline operation, and the freedom to
swap in better open models as they appear.

## Why ELI exists

ELI is built on one conviction: **your AI should belong to you — the person using it — not the
company serving it.** That isn't a slogan; it's the constraint every architectural decision answers
to.

- **Everything is local. Nothing phones home.** Offline isn't a setting you toggle —
  `eli/core/netguard` enforces it at the socket layer, so the default is silence on the wire.
- **Your model of *you* stays on your machine.** ELI learns your patterns and preferences and writes
  them to your disk, never a data centre.
- **It improves for you, not for a vendor.** Self-training means ELI gets better at serving *you* —
  not at serving someone's next corporate model update.
- **Privacy isn't a feature checkbox. It's the founding constraint of the whole design.**

There's an underdog logic to it, too. The people who most need a capable assistant — those who can't
justify a monthly subscription, who live with bad or no internet, who simply don't want their
conversations sitting on a stranger's server — are exactly the people cloud AI underserves. A
capable, free, offline, self-improving assistant that runs on hardware you already own is
**genuinely democratising**, in a way most "AI for everyone" copy only pretends to be.

## What it does

You interact by typing or speaking; it understands many phrasings. Representative commands:

| Area | Examples |
|---|---|
| Computer control | open / close / focus applications, tile windows, set volume, type text, click |
| Media | play / pause / skip on Spotify or YouTube; "what's playing?" |
| Screen & documents | "what's on my screen?"; summarise a PDF; describe an image; analyse a CSV |
| Writing & code | draft a grounded report; write a script; fix bugs in a file; examine a codebase |
| Memory | "remember that…"; "what do you know about me?" — a private profile that updates as you talk |
| Planning & automation | alarms, timers, calendar, overnight / scheduled jobs; learns routines and offers to automate them |
| Information | news synthesis, weather, web search — network-gated, and it tells you when it goes online |
| Voice | configurable wake word, dictation, text-to-speech; adapts to your voice and tone |

Asking *"what can you do?"* lists the full surface.

<details>
<summary><b>Full capability breadth — 208 capabilities across 17 areas</b></summary>

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

## Design principles

What distinguishes ELI from a typical assistant is architectural, not cosmetic. Each principle is
backed by a concrete mechanism in the codebase:

1. **Local and offline-first.** Everything runs on your hardware. A process-wide network guard
   (`eli/core/netguard`) fail-closes at the socket layer: with networking disabled, no outbound
   connection can be made, even by a component that tries. Online actions (search, news) are explicit
   and individually gated.

2. **Model-agnostic.** No model name or size is hardcoded on the inference path. ELI loads any local
   GGUF model, detects its chat template, and sizes context to the model's real `n_ctx_train`. Newer
   open models can be dropped in without code changes.

3. **Grounded introspection.** Asked about its own state, ELI reports from live runtime evidence —
   actual database row counts, the loaded model, the active pipeline — rather than generating a
   plausible answer. A no-fake-actions guard prevents it from claiming an action it did not perform.

4. **Self-maintaining.** It logs its own failures and can generate, syntax-check, apply, and
   automatically roll back patches to its own source. A LoRA/QLoRA pipeline (PyTorch/PEFT) can
   fine-tune the model on your own conversation history.

5. **Embodied.** It operates the desktop directly — applications, windows, input, screenshots,
   clipboard, image and live-screen understanding, and optional webcam gaze control — not just text.

6. **User-aware.** A continuous, semantic user model is read on every turn and feeds the persona,
   proactive, reflection, and memory subsystems, so context persists across sessions and adapts to
   how you work.

## Features

### Conversation and reasoning
Five reasoning modes — Quick, Normal, Advanced, Research, Expert — each genuinely multi-pass
(self-consistency sampling, tree-of-thoughts branches, draft → critique). The mode is auto-selected
by how deep the question is, and when the supporting evidence is weak ELI deepens on its own: it
re-gathers harder and escalates one tier to raise its confidence *before* answering. For a quick
reply it can keep working in the background and surface a better-grounded answer afterwards. A
12-stage retrieval pipeline (HyDE query expansion → vector + full-text + knowledge-graph retrieval →
re-rank → synthesis) sits underneath, run by a 14-agent dependency-DAG orchestrator with
parallelism, retries, caching, and fallback.

### Memory that persists
A four-store memory — a FAISS vector index, full-text search, a knowledge graph, and working memory —
maintains a living, versioned profile of you. It is dynamic: active projects stay current while
abandoned ones fade, so its picture of you reflects the present. It is read on every turn, so you
don't repeat yourself across sessions.

### Operates your computer
Open, close, focus, tile, minimise, or maximise applications and windows; switch workspaces; open
system / audio / power / network settings; open URLs and your IDE. Application launch is backed by a
live index of your machine's own executables — and if an app isn't installed, ELI offers to install
it for you (real `apt` / `snap` / `flatpak` on your confirmation). It also controls volume, types
text, and moves and clicks the mouse.

### Voice, hands-free
Always-listening with a wake word **you can train** — and that hears you over background music. It
ducks your media to listen, waits for an unfinished command to complete, ignores its own spoken
output, and builds a per-user voice profile. Includes dictation, audio transcription, and a Piper
text-to-speech voice that never voices garbled fragments. A separate "train my voice" session learns
your pitch, energy, and tone so its delivery adapts to how you sound.

### Vision and screen understanding
Local vision-language models describe any image or your live screen; OCR extracts text from
pictures; "find the button that says X" locates UI elements on screen; optional ambient glances keep
a rolling awareness. All local — no cloud vision APIs.

### Gaze control (webcam)
Eye-tracking via MediaPipe with calibration and smoothing — "open / click that" moves the cursor to
where you're looking and clicks it. A genuine hands-free and accessibility capability.

### Image generation
A from-scratch procedural renderer with 10+ scene types (landscape, space, city, poster, emblem,
abstract, product, …) — composition planning, palettes, atmosphere, and post-processing, no model
required. Plus optional SSD-1B diffusion with VRAM hot-swap, and matplotlib plotting from your data.

### Documents and files
Create, read, and list files and folders; summarise any file; analyse CSVs, PDFs (single or whole
folders), and images. **Convert any document** to PDF, PDF-via-LuaLaTeX, `.docx`, `.odt`, `.rtf`,
HTML, Markdown, `.tex`, EPUB, or `.txt` (pandoc + a LibreOffice fallback). Two standout tools:
- **Report Builder** — drop in your sources (PDFs, data, code, notebooks) and ELI writes a full
  document grounded in your evidence: every claim is tied to a source or marked `[source needed]` —
  no fabricated citations or numbers.
- **File Chat** — open a file or folder and have a conversation about its actual contents.

Even a quick "generate a document about X" runs a multi-stage grounded pipeline — gather evidence →
plan an outline → draft section by section against that evidence → review and revise.

### Coding agent
Describe a task and it plans it, decomposes it into a dependency graph, writes it, runs it in a
sandbox, tests it, and repairs its own bugs — remembering fixes for next time. Plus examine-and-fix
on your existing files (tiered scan → offer → verified, auto-reverting patch), project scaffolding,
diffs, and a built-in Sim-IDE.

### Scheduling and automation
Defer any command to a time — "open Spotify at 8pm", "get the news at 7am", "morning report ready
for 7:15" — to durable background workers that survive restarts ("every morning" makes it recurring).
Chain several commands in one sentence ("close Steam and set an alarm for 7am"). Alarms, timers, and
pomodoro included.

### Proactive and self-aware
A background daemon notices your patterns and *offers* (never silently) to automate routines, builds
your morning briefing, and surfaces things worth your attention through a governed, approval-gated
layer. On a 30-minute beat it runs a self-awareness tick: it watches its own code for changes,
refreshes its self-model, and advances goals into proposals for your approval — nothing destructive
runs unattended.

### Maintains and improves itself
Logs its own failures and runs a self-repair cycle (generate → verify → apply → auto-revert); runs
maintenance (update, rebuild indexes, refresh capabilities); audits its own runtime from live health
probes; detects a missing dependency and heals its environment; and can **train a LoRA adapter on
your own conversations**, locally.

### Web, news, and weather (network-gated)
With the Net switch on, ELI fetches web answers, weather, and a **synthesised news digest** — a
rolling, interest-matched read rather than raw headlines. With it off, networking is sealed at the
socket and nothing leaves your machine.

### Interfaces — desktop, terminal, and an optional local screen-share
The primary interface is a desktop GUI (Chat plus Labs, Report Builder, Coding, Tasks, and an
embodied self-model view); there's also a headless CLI. **ELI itself always runs on your computer
and only your computer** — the AI never runs on, or sends anything to, another device. Optionally,
you can open a window onto it from a phone or tablet browser **on your own home network** via a
built-in local server (loopback-only and token-gated by default). The phone is just a remote screen:
no AI runs on it, and nothing touches the internet.

### Make it yours
Swap the model (any local GGUF). Tune the mind via a dedicated Cognition settings panel that exposes
every knowledge-gathering limit and the synthesis budget. Extend it with a real plugin system
(weather, web, calendar, notes, pomodoro, and your own). Teach it routines it proposes. And control
the boundary with a single network toggle.

## Quick Start

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

## Choose your model

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

## Optional: a remote view over your own network

The desktop app is the primary interface. Optionally, you can open ELI in a phone or tablet browser
**on your own home network** as a second screen. **The AI still runs entirely on your computer** — the
phone only displays it, nothing runs on the phone, and nothing reaches the internet. Off by default
(loopback-only) until you explicitly enable local-network access:

```bash
./scripts/eli_serve.sh             # this computer only  → http://127.0.0.1:8081/
./scripts/eli_serve.sh --lan       # your local network  → prints a token-protected URL
```
Details: **[`docs/SERVER_AND_WEB_APP.md`](docs/SERVER_AND_WEB_APP.md)**.

## Privacy

Nothing leaves your computer unless you ask for something online (news, search, downloading a
model) — and ELI tells you when it does. No accounts, no telemetry, no subscription. A fresh
install knows **nothing** about you until you talk to it, and you can delete your data anytime.

## Documentation

- **[Server & Web App](docs/SERVER_AND_WEB_APP.md)** — self-hosted FastAPI server + phone/web UI
- **[Train your own model](docs/TRAINING_YOUR_OWN_MODEL.md)** — A-to-Z LoRA/QLoRA into an ELI GGUF
- **[Cross-platform coverage](docs/CROSS_PLATFORM.md)** — capability × platform matrix
- **[Model runtime policy](docs/model_runtime_policy.md)** — how ctx/layers/batch are sized

## Under the hood

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

## Security

Defence-in-depth, all local:

| Layer | Protects against |
|---|---|
| Prompt-injection guard | Strips `[INST]`, `<\|im_start\|>system`, jailbreak phrases before the model sees input |
| SQL identifier validation | Allowlist regex on every f-string SQL identifier — no injection via table/column names |
| Shell security gate | `RUN_CMD` is **fail-closed**: blocked unless allowlisted; destructive patterns (`rm -rf /`, `mkfs`, fork bombs) denied even then |
| Custom-agent trust | SHA-256 registry — unregistered/tampered agent files are skipped at load |
| Offline-by-default | A process-wide network guard fails closed unless a task is explicitly authorised online |

## Project status & contributing

ELI is **actively developed and solely maintained** by its author — a single-steward project.
Direction, releases, and what gets merged are decided by the copyright holder. It is provided
as-is with **no support guarantee**, but bug reports and ideas are genuinely welcome, and it will
keep moving as long as it stays useful.

- **Found a bug or have an idea?** [Open an issue](https://github.com/ShadowESC95/ELI_MKXI_v2.0_PRO/issues).
- **Want to contribute code?** Pull requests are welcome — please read
  **[CONTRIBUTING.md](CONTRIBUTING.md)** first. Because ELI is source-available and singly-stewarded,
  contributions include a short **inbound license grant** so the whole project stays under one
  consistent license.
- **Security issue?** See **[SECURITY.md](SECURITY.md)** — report it privately, not in a public issue.
- **Want to support development?** ELI is free to use; if it's useful to you, you can chip in at
  **[ko-fi.com/shadowesc95](https://ko-fi.com/shadowesc95)**. Entirely optional — it just helps keep
  the project moving.

Forks for **redistribution** are not permitted by the [license](LICENSE) — contribute improvements
back here instead of publishing your own copy.

## License

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

**Seeing ELI redistributed, hosted, or sold somewhere?** That is not permitted under the license.
Please report it — with a link — to [jaybridgeman0095@gmail.com](mailto:jaybridgeman0095@gmail.com);
it helps the author act on violations.

> **Why source-available?** To put a genuinely capable, fully-local AI assistant in people's hands
> to *use and learn from* — while keeping the right to steward the project rather than have it
> taken closed and resold.

## Contact

Questions, feedback, or interested in a license/services beyond the terms above?

- **Email:** [jaybridgeman0095@gmail.com](mailto:jaybridgeman0095@gmail.com)
- **GitHub:** [@ShadowESC95](https://github.com/ShadowESC95) ·
  [open an issue](https://github.com/ShadowESC95/ELI_MKXI_v2.0_PRO/issues)

For commercial licensing, redistribution rights, or hosting beyond the
[license](LICENSE), please reach out by email.
