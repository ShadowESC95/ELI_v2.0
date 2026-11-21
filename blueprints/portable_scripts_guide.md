# Which script do I run? — ELI v2.0 portable

> **Updated for v2.5.36 (November 2026).** The primary way to install ELI is now the
> **prebuilt installers on GitHub Releases** — `ELI-Setup-<v>.exe` (Windows),
> the `.dmg` (macOS, Apple Silicon), the `.AppImage` (Linux). All three are built in CI and
> started there before a release goes out (the Windows installer is run first); the macOS
> app is only ad-hoc signed, so macOS asks once before opening it. First launch offers GPU
> acceleration (NVIDIA CUDA / AMD or Intel Vulkan; Apple Metal is built in) and a starter
> model sized to your hardware. Data lives in a per-user `ELI_v2` folder and survives upgrades;
> `--fresh-start` resets it. Everything below remains valid for
> **source installs** (clone + `install.sh`) and the classic portable tarball. In a clone the
> portable launchers are `scripts/eli_setup.sh` (for `ELI_Setup.sh` / `INSTALL_ELI.sh`) and
> `scripts/eli_startup.sh` (for `RUN_ELI.sh`).


You have just extracted **`ELI_v2-<version>-linux-portable`** and you are looking at a
folder full of scripts. This guide explains **every launcher in plain language**: what
it is, when to use it, the exact command to type, and what it actually does under the
hood. No prior knowledge assumed.

---

## The short answer

> **After a fresh extract, open a terminal in this folder and run:**
>
> ```bash
> chmod +x ELI_Setup.sh
> ./ELI_Setup.sh
> ```
>
> That one command installs everything and sets ELI up; press **Launch** at the end (or run
> `./RUN_ELI.sh`) to start it. If you only ever read one line of this document, that is the line.

`chmod +x` means "mark this file as runnable" — you only need it once. The `./` in front
means "run the script that is right here in this folder."

Everything else in this folder is either **(a)** something `ELI_Setup.sh` calls for you,
**(b)** an alternative for people who want more control, or **(c)** a tool for developers
that you should ignore.

---

## Pick your path (decision table)

| Your situation | Run this |
|---|---|
| "Just make it work." | `./ELI_Setup.sh` |
| `ELI_Setup.sh` says **PySide6 is not installed** | `bash install.sh --yes --auto-model` then `./RUN_ELI.sh` |
| I want to install now and launch later, separately | `./INSTALL_ELI.sh` then `./RUN_ELI.sh` |
| My computer has **no NVIDIA graphics card** | `./ELI_Setup.sh` — the hardware check picks the CPU build by itself; to force it: `ELI_INSTALL_CPU_ONLY=1 ./ELI_Setup.sh` |
| I want ELI's starter models + voices too (big download) | `./RUN_ELI.sh --with-github-assets` (sets ELI up first if it is not yet) |
| I want to use ELI from my **phone or tablet** | `./scripts/eli_serve.sh --lan --https` |
| I'm on **Windows** | `install.bat` (or the `Setup.exe` from GitHub Releases) |
| I'm a developer building release packages | `build_packages.sh` — *not for normal use* |

---

## Important: ELI needs an AI model

A fresh portable ships **without** the large AI model file (to keep the download small).
The release download already carries the memory embedder (`models/embeddings/`) and the
Piper voices (`tts_piper/piper/`); a chat model is the one thing missing, and ELI will not
think until one is present. Two ways to get one:

- **Bundled convenience pack** (small starter models + voices), pulled from the project's
  GitHub Release once ELI is set up:
  ```bash
  gh auth login                       # one-time: log in to GitHub
  ./RUN_ELI.sh --with-github-assets   # downloads the model/voice pack, then launches
  ```
  (On a run that first has to install ELI, the download follows the install.)
- **Automatic model download** (guided), if you prefer just the model:
  ```bash
  .venv/bin/python -m eli.core.model_download --auto
  ```

`ELI_Setup.sh` downloads a chat model sized to your hardware for you, so most people never
type these by hand.

---

## Every file, explained

### `ELI_Setup.sh` — the recommended one-click
**What it is:** the friendly "grandparent setup." A double-click-friendly name that hands
off to `scripts/eli_setup.sh`.
**When to use:** first time, and whenever you want the easy path.
**Command:** `./ELI_Setup.sh`
**What it does:** checks your hardware (GPU or CPU build), makes a small private Python
environment (`.venv`) with the window toolkit, and opens the graphical installer. That runs
`install.sh` once — all dependencies, the inference engine for your hardware, the databases,
the `eli-v2` terminal command and the app-menu icons — then fetches the memory embedder, the
voices and a chat model sized to your hardware. Its **Launch** button starts ELI. With no
display it does the same in the terminal. It takes no options. **To you:** the "do
everything for me" button.

### `INSTALL_ELI.sh` — same as ELI_Setup.sh (legacy name)
**What it is:** a thin wrapper around `scripts/eli_setup.sh` (identical to `ELI_Setup.sh`).
**When to use:** same as `ELI_Setup.sh`; name kept for older docs.
**Command:** `./INSTALL_ELI.sh`
**What it does:** opens the unified GUI installer when possible; otherwise runs `install.sh --yes --auto-model`. It does
**not** open ELI — that's what `RUN_ELI.sh` is for.
**Options:** none — it passes nothing on. Force the CPU build with
`ELI_INSTALL_CPU_ONLY=1 ./INSTALL_ELI.sh`; for `--skip-torch` and the other installer flags run
`bash install.sh` directly, and fetch the model/voice pack with `./RUN_ELI.sh --with-github-assets`.
**To you:** "get it ready, but don't open it yet."

### `RUN_ELI.sh` — launch ELI (your daily button)
**What it is:** a wrapper around `scripts/eli_startup.sh`.
**When to use:** every day, to start ELI. Safe to run even if you haven't installed yet —
it will install first if needed.
**Command:** `./RUN_ELI.sh`
**What it does:** checks that ELI is installed (installs if not), checks that the inference
engine starts on this CPU (reinstalling a CPU build if it does not), optionally restores the
model/voice assets, then launches the app and keeps a log of the start under
`artifacts/startup/logs/`.
**Useful options:** `--with-github-assets` (fetch the model/voice pack before launching, after
the setup a fresh extract gets first), `--trace` (turns on the pipeline trace: each request's route
and stages are logged at debug level),
`--no-setup` (skip the install check), `--no-log` (no log file).
**To you:** the "open ELI" button.

### `install.sh` — the full Linux/macOS installer (advanced)
**What it is:** the low-level installer that the one-click scripts wrap. This is the
real engine that builds the environment.
**When to use:** you want direct control over the installation, or you're comfortable in
a terminal.
**Command:** `bash install.sh`
**What it does:** creates the `.venv`, installs the **exact, frozen** set of tested
dependencies (reproducible), verifies GPU offload works, initialises data folders and
databases, fetches the embedder and voices, offers a model and the `eli-v2` terminal command,
and adds the app-menu icons. It does **not** run the graphical wizard or launch ELI — the
one-click scripts add those niceties on top.
**Useful options:** `--yes` (no questions; also downloads a model sized to your GPU),
`--cpu-only` (no GPU), `--skip-torch` (skip PyTorch), `--latest` (newest dependency versions
instead of the frozen lock), `--install-cuda` (best-effort install of the NVIDIA CUDA toolkit),
`--model=KEY` / `--no-model` (a specific model / no model and no embedder).
**To you:** "the manual installer" — most people should use `ELI_Setup.sh` instead.

### `install.bat` and `install.ps1` — Windows installers
**What they are:** the Windows equivalent of `install.sh`. `install.bat` is the
double-click file; it simply launches the more capable `install.ps1` (PowerShell).
**When to use:** you're on Windows.
**Command (in the folder):** `install.bat`  — or `install.bat /cpu` for no GPU.
**What they do:** same idea as `install.sh` — build the environment, verify the GPU,
initialise databases.
**Useful options:** `/cpu` (CPU-only), `/cuda` (also install the CUDA toolkit via winget),
`/latest` (newest versions instead of the frozen lock).
**To you:** "the Windows installer." Non-technical Windows users may prefer the
`Setup.exe` from the GitHub Releases page instead.

### `eli.sh` — the bare launcher (low-level)
**What it is:** the minimal launcher. It points the environment variables at this folder
and runs `python -m eli` inside the `.venv`.
**When to use:** rarely — only if you've already installed and want the most direct start.
**Command:** `./eli.sh`
**What it does:** exactly one thing — starts ELI from the already-built `.venv`. If the
environment isn't there yet, it tells you to run the installer first. `RUN_ELI.sh` is the
friendlier version of this.
**To you:** the "engine start" with none of the conveniences.

### `eli-v2` — the terminal command (created during setup)
**What it is:** a shortcut installed into `~/.local/bin/eli-v2` (and `~/.local/bin/eli2`) by
the setup, which also adds matching aliases to `~/.bashrc`. Other ELI versions keep their own
command names, so they never take each other's.
**When to use:** after installing, from **any** folder.
**Command:** `eli-v2`
**What it does:** runs this folder's `eli.sh`, so it launches ELI without needing to be inside
this folder.
**Tip:** if typing `eli-v2` runs an old version, open a new terminal or run `hash -r`; if it
still points at an old folder, run `bash scripts/fix_eli_shell_env.sh --yes` from this one.

### `eli-v2.0.desktop` — an old menu-entry template
**What it is:** a Linux application-menu entry left from earlier versions. Nothing installs it
any more.
**What sets up the menu instead:** `scripts/install_desktop_apps.sh`, which the installer runs
on Linux (`./packaging/desktop/install_desktop_launcher.sh` calls it too). It adds **ELI v2.0**,
**ELI Server**, **ELI Setup** and **Uninstall** entries that start `~/.local/bin/eli-v2-run`,
which finds this folder through a small pointer file — no folder path is written into the
entries themselves.
**To you:** the "ELI icon" in your menu once setup has run.

### `build_packages.sh` — developer tool (not for end users)
**What it is:** the script that **builds** the distributable packages (Python wheel, Debian
package, Linux AppImage, Windows portable zips, etc.).
**When to use:** only if you are packaging ELI for release.
**What it does:** assembles installable artifacts under `dist/`. It does **not** run or
install ELI for use.
**To you:** ignore this one — it's for whoever ships ELI, not for using it.

### `scripts/eli_serve.sh` — use ELI from your phone / tablet
**What it is:** starts ELI's built-in web server so a browser on another device can reach it.
**Command:** `./scripts/eli_serve.sh --lan --https`
**What it does:** binds to your local network (`--lan`) with an access token, and enables
HTTPS (`--https`, on port 8443) which browsers require before they'll allow the
**microphone**. It prints a URL to open on the phone; the QR code to scan is on the served
page's **Connect** tab and in the desktop app under Settings → Web Server.
Everything still runs on **this** machine — nothing goes to any cloud.
**To you:** the "talk to ELI from my couch on my phone" button.

### `README_INSTALL.txt`
**What it is:** the short plain-text quick-start that ships in the folder. This PDF is the
expanded, friendly version of it.

---

## After it's running — everyday use

- **Start ELI:** `./RUN_ELI.sh`  (or just type `eli-v2`, or click the menu icon)
- **Phone access:** `./scripts/eli_serve.sh --lan --https`
- **Your data lives here** (created automatically on first run):
  `artifacts/db/` (memories & conversations), `artifacts/notes/` (the notes ELI writes for
  you), `artifacts/runtime/`, and `config/`.
  Because this is a *portable* copy, everything stays inside this folder — you can move or
  back up the whole `ELI_v2-<version>-linux-portable` folder and nothing is lost. After a
  move, run `./scripts/install_desktop_apps.sh` and `bash scripts/fix_eli_shell_env.sh --yes`
  from the new place so the menu icons and the `eli-v2` command follow it.

## If something goes wrong

- **"Virtual environment not found":** you launched before installing — run `./ELI_Setup.sh`
  (or `./INSTALL_ELI.sh`) first.
- **No NVIDIA GPU / install fails on GPU bits:** reinstall the CPU build with
  `ELI_INSTALL_CPU_ONLY=1 ./ELI_Setup.sh` (or `bash install.sh --cpu-only`).
- **ELI has no model / won't answer:** fetch one with `./RUN_ELI.sh --with-github-assets`
  (after `gh auth login`) or `.venv/bin/python -m eli.core.model_download --auto`.
- **Odd behaviour at startup:** every start through `./RUN_ELI.sh` is logged under
  `artifacts/startup/logs/`; `./RUN_ELI.sh --trace` also turns on the pipeline trace.

---

*ELI runs entirely on your own hardware. It is offline by default — turn on the **Net**
toggle in the app only when you want it to reach the internet.*
