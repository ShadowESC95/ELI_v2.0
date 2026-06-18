# ELI MKXI v2.0 PRO

ELI MKXI is a 100% local, privacy-first AI assistant. It runs entirely on your
own hardware — no cloud APIs, no telemetry. ~139k lines of Python across 363
modules, **208 capabilities**, and **14 specialist agents**. **Model-, user-, and
hardware-agnostic** — the same install runs a 3B model on a laptop or a large model
across multiple datacenter GPUs. Features include:

- **GGUF inference** via llama-cpp-python (CPU and GPU, auto-tuned at boot;
  model-agnostic — no hardcoded model name/size on the inference path; context
  sized to each model's real `n_ctx_train`)
- **Multi-GPU** — VRAM summed across all GPUs; optional `tensor_split` to run one
  large model across several cards (`config/gpu_profiles.json`)
- **PySide6 GUI** with dockable panels, quick-action board, and live telemetry
- **Self-hosted web app** — a built-in FastAPI server (`api/server.py`) serves a
  mobile-first chat UI; reach ELI from a phone/tablet browser over your LAN
  (loopback-safe by default, token-gated when exposed). Inference stays on the host.
- **Continuous User Model** — a living, semantic model of the user, read directly
  each turn and wired into cognition, persona, proactive, reflection, and awareness;
  seeded by a light, skippable first-run onboarding interview
- **Persistent memory** — SQLite + FAISS vector index + knowledge graph for
  semantic recall
- **Multi-agent bus** — parallel agent dispatch with confidence aggregation,
  on a DAG orchestrator (parallel/retries/fallback/cache/timeout)
- **Code examiner & self-repair** — examine/audit files for errors (tiered:
  syntax + import → static lint → LLM logic review), fix files, and drag-and-drop
  a file into the chat to act on it directly
- **Local voice** — faster-whisper STT (VRAM-aware: GPU on large cards, else CPU
  so the main model keeps the GPU), wake-word, and TTS
- **Security hardening** — prompt injection guard, SQL identifier validation,
  fail-closed shell command gate, custom agent SHA-256 trust registry, offline-by-
  default network guard
- **Headless / CLI mode** — `eli --headless` for terminal-only use
- **Proactive daemon** — background goal/habit/insight generation
- **Self-improvement** — failure analysis, learns from mistakes, capability
  manifest regeneration
- **Plugin system** — install, enable/disable, and uninstall tools at runtime
- **Interactive cross-platform install** — Linux/macOS/Windows one-click installers
  (system report → plan → model offer); app-menu / Start-Menu desktop launchers for
  both the GUI and the web server

## One-Click Setup

Fresh Linux/source checkout — `install.sh` does everything. It opens with a **system
report** (CPU/RAM/GPU/VRAM/disk), shows a **plan** and asks to proceed, picks the right
build for your hardware, installs PyTorch + a CUDA/Metal llama-cpp-python, all packages
from the **frozen lock** (reproducible), initialises the local SQLite databases,
**verifies the GPU build actually compiled in**, and offers to **download a model sized
to your VRAM**. Piped/CI installs run non-interactively (`--yes`).

**Linux / macOS:**
```bash
git clone https://github.com/ShadowESC95/ELI_MKXI_v2.0_PRO.git
cd ELI_MKXI_v2.0_PRO
bash install.sh                 # interactive: report -> plan -> install -> model
bash install.sh --yes           # non-interactive (use detected defaults)
bash install.sh --install-cuda  # ALSO auto-install the CUDA toolkit if missing
./scripts/eli_launch.sh         # launch the desktop app (first run shows the wizard)
```
Install flags: `--yes`/`-y` (no prompts), `--auto-model` / `--model=qwen2.5-7b` /
`--no-model`, `--cpu-only` / `--gpu`, `--install-cuda`, `--latest`, `--skip-torch`.

**Windows** (double-click `install.bat`, or in PowerShell):
```powershell
.\install.bat                                  # CUDA + frozen lock + GPU verify
.\install.bat /cuda                            # also auto-install CUDA toolkit (winget)
powershell -ExecutionPolicy Bypass -File install.ps1 -InstallCuda
.\eli.bat
```

**Phone / tablet (Android, iOS) — recommended: self-hosted web app.**
Don't run inference on the phone (that needs an on-device llama.cpp build). Run the server
on a machine that *can* do inference (your desktop / a home server); inference stays on the
host, nothing reaches the cloud. The server is **safe by default** — loopback-only and
tokenless — until you explicitly expose it:
```bash
# on the host (Linux/macOS/Windows), after install.sh:
./scripts/eli_serve.sh             # local-only  -> http://127.0.0.1:8081/
./scripts/eli_serve.sh --lan       # LAN access for phone/tablet (binds 0.0.0.0 + token)
```
With `--lan` it prints a token-protected URL like `http://<host-ip>:8081/?token=…` — open
that once on the phone (same WiFi) and the page remembers the token. Works on Android, iOS,
and desktop with zero native build. REST API at `/v1/chat`, docs at `/docs`.

**One launcher for everything:** `./scripts/eli_launch.sh` (desktop GUI) ·
`eli_launch.sh serve --lan` (server) · `eli_launch.sh both` (both at once).
Windows: `.\eli.bat` (GUI) · `.\scripts\eli_serve.ps1 -Lan` (server).

**Desktop apps (app-menu / Start-Menu launchers for both ELI Pro and the web server):**
`./scripts/install_desktop_apps.sh` (Linux `.desktop` / macOS `.command`) ·
`powershell -ExecutionPolicy Bypass -File scripts\install_desktop_apps.ps1` (Windows Start Menu).

All three installers are now **interactive + identical in what they install** (system report
→ plan → model offer; `--yes`/`-Yes` for non-interactive/CI) across Linux, macOS, and Windows.

**Android / Termux (experimental, expert-only)** — the Python core can run headless in
Termux, but `llama-cpp-python`, `torch`, `faiss`, and `PySide6` are excluded from
`requirements-android.txt` and must be hand-built on-device; the GUI is unavailable.
Prefer the self-hosted web app above.
```bash
bash scripts/install_android.sh
.venv/bin/python -m eli.cli.headless
```

Then download a model when prompted, or:
```bash
python -m eli.core.model_download --auto      # pick by detected VRAM
python -m eli.core.model_download qwen2.5-7b  # ~4.7 GB (recommended, 8GB+ GPU)
```

### Scaling — 3B laptop → trillion-param on 8× datacenter GPUs
ELI is **model-, user- and hardware-agnostic by design**, and the *same install* spans the
whole range — **always local, never cloud, at every scale**:
- **Loader** sizes each model from its real `n_ctx_train` (GGUF metadata) and fits it to the
  hardware actually present — VRAM is summed across **all** detected GPUs, layers/batch/ctx
  are tuned per machine. A 3B on a 4 GB laptop and a 70B+ on a multi-GPU server use one path.
- **Models** beyond the three built-in starters (1.5B / 3B / 7B): drop any `.gguf` into
  `models/`, or point ELI at a catalog of your own — `ELI_MODEL_CATALOG=/path/catalog.json`
  or `models/catalog.json` (same schema: `key`, `name`, `filename`, `url`, `size_gb`,
  `vram_gb`). That's the supported path for mid/large/huge models without code changes.
- **Big hardware** (e.g. 8× datacenter GPUs): detection reports total VRAM and `--auto`
  selects the largest model that fits. **Multi-GPU split** for a single large model is
  configured in `config/gpu_profiles.json` (enable a profile, or set `tensor_split` —
  e.g. `"0.5,0.5"` — in settings); the loader passes it to llama.cpp `tensor_split`.
  Single-GPU is the default and unchanged.
- **Ethos holds at every tier:** offline-by-default, no telemetry, emergent persona, your
  data on your hardware — whether that's a Raspberry-Pi-class box or a $250k GPU server.

**Flags (Linux `--flag` / Windows `/flag`):** `--install-cuda` / `/cuda` (auto-install
the CUDA toolkit + rebuild llama-cpp for users without it), `--cpu-only` / `/cpu`,
`--latest` / `/latest` (version ranges instead of the frozen `requirements.lock.txt`),
`--skip-torch`. **macOS uses Metal** (no CUDA). If a CPU-only llama-cpp slips in, the
installer says so and (with the CUDA flag) fixes it automatically. Legacy
`scripts/eli_one_click_setup.sh` (installs `~/.local/bin/eli`) still works.

Equivalent startup entrypoint with optional logging, trace, setup, and asset
restore flags:

```bash
bash scripts/eli_startup.sh
bash scripts/eli_startup.sh --setup --with-github-assets
bash scripts/eli_startup.sh --trace
```

`scripts/eli_one_click_setup.sh` installs `~/.local/bin/eli` by default. That
launcher runs this checkout through its `.venv`, so a normal terminal can start
ELI with:

```bash
eli
```

If your shell has cached another `eli` command, run `hash -r` or open a new
terminal.

If the large local model/voice release assets have been uploaded to the private
GitHub release, restore them during setup:

```bash
gh auth login
bash scripts/eli_one_click_setup.sh --with-github-assets
```

CPU-only setup:

```bash
bash scripts/eli_one_click_setup.sh --cpu-only
```

Build an installable wheel/sdist:

```bash
bash scripts/package_eli_release.sh
python -m pip install "dist/eli_mkxi-*.whl[full]"
```

Build a portable Linux desktop package:

```bash
bash scripts/package_desktop_app.sh
```

The package is written to `dist/app_packages/` and includes `INSTALL_ELI.sh`,
`RUN_ELI.sh`, a desktop launcher installer, and the built wheel. By default it
does not embed local GGUF/TTS assets; restore those with:

```bash
./RUN_ELI.sh --with-github-assets
```

## GitHub Large Assets

The code repository intentionally excludes machine-specific runtime state,
virtual environments, and large model/voice binaries from normal Git because
GitHub rejects normal Git blobs over 100 MB and those files can be tens of GB.

Create a complete local ignored-asset manifest:

```bash
python scripts/github_asset_manifest.py --output dist/github_assets/asset_manifest.json
```

Create split GitHub Release upload archives for local model and voice payloads:

```bash
bash scripts/create_github_asset_archives.sh
```

Upload those split archives to the private GitHub release:

```bash
bash scripts/upload_github_assets.sh
```

Restore release assets after cloning:

```bash
python scripts/restore_github_asset_files.py
```

If the machine does not have enough free disk to create one archive set, use the
direct/chunked uploader. It stages one file at a time and is better for this
checkout's 70 GB+ model directory:

```bash
python scripts/upload_github_asset_files.py
python scripts/restore_github_asset_files.py
```

`scripts/restore_github_assets.sh` is retained for legacy split-archive
releases. The current uploaded `local-assets-v2.0` release uses the direct/chunk
manifest restored by `scripts/restore_github_asset_files.py`.

The repository is designed to be movable. Do not commit user-specific absolute
paths such as `/home/name/...`, `C:\Users\name\...`, or `/Users/name/...`.
Use project-relative paths, `ELI_PROJECT_ROOT`, or the path helpers in
`eli.core.paths` and `eli.core.portable_paths`.

## Project Layout

- `eli/core` — paths, settings, contracts, hardware profile
- `eli/kernel` — control loop, cognitive engine, state models
- `eli/cognition` — reasoning, grounding, agent bus, working memory
- `eli/memory` — episodic, semantic, FAISS vector index, knowledge graph
- `eli/planning` — goals, jobs, autonomy, proactive daemon, scheduling
- `eli/execution` — router, executor, tool authority, shell security gate
- `eli/perception` — audio, screenshots, OS controller, TTS/STT
- `eli/runtime` — arbitration, verification, security policy
- `eli/integrations` — Ollama, GGUF, media backends, adapters
- `eli/plugins` — tool plugins (install/enable/disable at runtime)
- `eli/gui` — GUI launcher and `EliMainWindow`
- `eli/gui/panels` — extracted panel components (startup, settings, agents)
- `eli/cli` — headless REPL (`eli --headless`)
- `config` — portable default settings and templates
- `models` — local model payloads (gitignored, distribute separately)
- `tests` — pytest suite (6,800+ tests across 160+ files; unit, integration, and
  claim-verification)
- `packaging` — Windows, macOS, Linux packaging scripts
- `dist` — generated release artifacts

## Supported OS Names And Aliases

Runtime OS checks go through `eli.utils.platform_compat`.

- Windows: `windows`, `win`, `win32`, `win64`, `nt`, `cygwin`, `msys`, `mingw`
- macOS: `macos`, `mac`, `darwin`, `osx`, `mac os`, `mac os x`
- Linux: `linux`, `linux2`, `gnu/linux`, `ubuntu`, `debian`, `fedora`, `arch`
- Android/Termux: `android`, `termux`, `bionic`
- BSD: `bsd`, `freebsd`, `openbsd`, `netbsd`
- Generic Unix: `unix`, `posix`

Android support means Termux/headless integration. It does not mean full desktop
GUI, global desktop control, CUDA, PyAudio, or AppImage support on Android.

## Dynamic Path Rules

Use these APIs instead of hard-coded machine paths:

```python
from eli.core.paths import (
    project_root, data_dir, config_dir, cache_dir, models_dir,
    db_dir, user_db_path, agent_db_path, memory_db_path,
)

from eli.core.portable_paths import resolve_path_value, make_portable_path_value
```

Settings may store:

- `models/gguf/base/model.gguf`
- `${ELI_PROJECT_ROOT}/models/gguf/base/model.gguf`
- `%ELI_PROJECT_ROOT%\models\gguf\base\model.gguf`

At runtime those resolve to the current machine. When a path is inside the
project tree, settings storage converts it back to a project-relative path.

## Environment Files

- `.env.example`: minimal common overrides
- `.env.full.example`: full environment reference
- `.env.mkxi`: Bash helper for Linux/macOS source checkouts

Most users should leave `ELI_PROJECT_ROOT` unset. The app auto-detects its
project root from the installed package or source tree.

## Requirements

- `requirements.lock.txt`: **frozen, exact known-good versions** (used by `install.sh`
  by default for reproducible installs; excludes torch/llama-cpp, which are installed
  via their CUDA indices)
- `requirements.txt`: Linux x86_64 profile (version ranges)
- `requirements-windows.txt`: Windows profile
- `requirements-macos.txt`: macOS profile
- `requirements-android.txt`: Android/Termux headless profile
- `requirements-full.txt`: broad source-checkout profile

Recommended setup from a source checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-full.txt
python -m pip install -e .[full]
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-windows.txt
python -m pip install -e .[full]
```

macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-macos.txt
python -m pip install -e .[full]
```

Android/Termux:

```bash
pkg update
pkg install python termux-api
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-android.txt
python -m pip install -e .
```

## Running

Source checkout (GUI):

```bash
python -m eli
```

Headless / terminal REPL:

```bash
python -m eli --headless
# or short form:
python -m eli -H
```

Headless slash commands: `/status`, `/mode`, `/reset`, `/help`, `/quit`

Linux installed package:

```bash
eli-mkxi
```

Windows portable ZIP:

1. Extract the ZIP.
2. Run `install.bat` or `install.ps1`.
3. Launch with `eli.bat` or the installed shortcut if present.

macOS tarball:

1. Extract `ELI_MKXI-<version>-macos-app.tar.gz`.
2. Open `ELI MKXI.app`.
3. Approve Gatekeeper/accessibility permissions if macOS asks.

## Packaging

Full release build from Linux:

```bash
bash build_packages.sh wheel wheelhouse deb appimage macos windows
```

Notes:

- The Linux AppImage target falls back to a portable tarball when
  `appimagetool` is not installed.
- A real Windows `.exe` or `.msi` must be built on Windows with
  `packaging/windows/build-windows.ps1`.
- A signed/notarized macOS `.dmg` must be built on macOS.

## Cross-Platform Limits

The code now has guards and aliases for Windows, macOS, Linux, BSD, and
Android/Termux, but no package can make every OS permission and native backend
instant:

- Windows may require SmartScreen approval, Visual C++ runtime, and audio/COM
  packages for endpoint volume control.
- macOS requires Screen Recording and Accessibility permissions for automation,
  and signing/notarization for a polished installer.
- Linux desktop control depends on the current desktop, Wayland/X11 tools,
  PulseAudio/PipeWire, and package availability.
- Android/Termux supports portable/headless operation and Termux API helpers,
  not full desktop GUI/control parity.
- GPU acceleration still depends on local drivers, CUDA/Metal/MPS support, and
  native wheels.

Full per-capability coverage matrix (what's full vs gracefully-degraded vs desktop-only on
each OS): **[`docs/CROSS_PLATFORM.md`](docs/CROSS_PLATFORM.md)**.

## Documentation
- **[Server & Web App](docs/SERVER_AND_WEB_APP.md)** — the self-hosted FastAPI server + mobile
  web UI: reach ELI from a phone/tablet (loopback-safe, LAN + token), endpoints, setup.
- **[Train your own model](docs/TRAINING_YOUR_OWN_MODEL.md)** — A-to-Z LoRA/QLoRA fine-tuning
  into an ELI-native GGUF (persona stays dynamic; voice-only training).
- **[Cross-platform coverage](docs/CROSS_PLATFORM.md)** — capability × platform matrix.
- **[Model runtime policy](docs/model_runtime_policy.md)** — how ctx/layers/batch are sized.

## Security

ELI applies multiple layers of defence-in-depth:

| Layer | What it protects |
|-------|-----------------|
| Prompt injection guard | Strips `[INST]`, `<\|im_start\|>system`, jailbreak phrases before the LLM sees input |
| SQL identifier validation | All f-string SQL identifiers pass an allowlist regex — no injection via column/table names |
| Shell security gate | `RUN_CMD` is **fail-closed**: all shell commands are blocked unless allowlisted via `ELI_ALLOWED_CMDS` (or the Full Control toggle is on); a destructive-pattern denylist (`rm -rf /`, `mkfs`, `dd of=/dev/`, fork bombs) blocks even then |
| Custom agent trust | SHA-256 hash registry — unregistered or tampered agent files are skipped at load |
| Input length cap | Requests over `ELI_MAX_INPUT_LEN` (default 8192) are truncated |

Register a new custom agent:

```bash
python -m eli --trust-agent path/to/my_agent.py
```

Override max input length:

```bash
export ELI_MAX_INPUT_LEN=16384
```

Bypass agent trust for local development only:

```bash
export ELI_TRUST_ALL_AGENTS=1
```

## Verification

Run focused checks:

```bash
python3 -m py_compile eli/utils/platform_compat.py eli/core/runtime_settings.py
pytest -q tests/test_core_paths.py tests/test_core_settings.py tests/test_integration.py
```

Run all tests:

```bash
pytest -q tests/
```
