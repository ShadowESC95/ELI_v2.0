# ELI v2.0 — The Complete Setup Guide (Plain English)

> **Updated for v2.1.51 (August 2026).** The primary way to install ELI is now the
> **prebuilt installers on GitHub Releases** — `ELI-Setup-<v>.exe` (Windows),
> the `.dmg` (macOS, Apple Silicon), the `.AppImage` (Linux). The Linux AppImage and
> Windows installer are built and launch-tested in CI; the macOS `.dmg` is built on a
> Mac and provided best-effort (not verified in CI). First launch offers GPU acceleration (NVIDIA CUDA /
> AMD Vulkan; Apple Metal is built in) and a starter model sized to your
> hardware. Data lives in a per-user `ELI_v2` folder and survives upgrades;
> `--fresh-start` resets it. Everything below remains valid for
> **source installs** (clone + `install.sh`) and the classic portable tarball.


*Everything you need to install, set up, and run ELI — written for a person, not a programmer.
If you can copy and paste, you can do this.*

---

## What you're about to install

ELI is an AI assistant that lives **entirely on your own computer**. There's no account to
create, no subscription, and nothing you say to it ever leaves your machine unless you
deliberately ask for something from the internet (like the news or a model download).

You install it once, download a "brain" (an AI model file) once, and after that it works
completely offline.

**What you need before starting:**

| Requirement | Details |
|---|---|
| A computer | Linux is the best-tested. Windows and macOS installers exist too. |
| Python 3.10 or newer | Most modern Linux systems already have it. Check with `python3 --version` |
| Disk space | ~2 GB for ELI itself, plus 2–5 GB for a model (more if you pick a big one) |
| A GPU (graphics card) | **Optional but recommended.** NVIDIA is best supported. Without one, ELI still works — just slower. |
| Internet | Only for the install itself and the one-time model download. |

---

## Part 1 — Getting ELI onto your computer

### The easy way (recommended): download a release package

1. Go to the releases page:
   **https://github.com/ShadowESC95/ELI_v2.0/releases**
2. Download the newest Linux portable file — it looks like:
   `ELI_v2-<version>-linux-portable.tar.gz`
3. Open a terminal in your Downloads folder and run:

```bash
tar -xzf ELI_v2-*-linux-portable.tar.gz
cd ELI_v2-*-linux-portable
chmod +x ELI_Setup.sh
./ELI_Setup.sh
```

`ELI_Setup.sh` is the guided, "just press Enter" path — it walks through every step below
automatically and opens the setup wizard at the end. **If you used this, you can skip
straight to Part 3.**

There's also an AppImage (`ELI_v2-*-x86_64.AppImage`) — make it executable
(`chmod +x`), double-click it, done.

### The developer way: from the source code

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
bash install.sh
```

That one command does all of this for you:

1. **Looks at your computer** — CPU, RAM, disk space, and what GPU you have (NVIDIA,
   AMD, Apple, or none).
2. **Shows you a plan** — what it's going to install and why — and asks permission
   before touching anything.
3. **Creates a private workspace** (a "virtual environment" in a `.venv` folder) so it
   never interferes with the rest of your system.
4. **Installs the AI engine** built for *your* hardware — CUDA build for NVIDIA, ROCm
   for AMD, Metal for Mac, or a plain CPU build.
5. **Verifies the GPU actually works** — and warns you loudly if you ended up with the
   slow CPU version by accident.
6. **Installs the helper tools** ELI uses to control your desktop — media playback,
   screenshots, clipboard, OCR (screen reading), microphone support.
7. **Offers to download a model** sized to your graphics card.
8. **Fetches the small required extras** — the memory "embedder" (~85 MB, needed for
   ELI's long-term memory) and the voice files (speech-to-text + a speaking voice).
9. **Sets up fresh, empty databases** — ELI starts knowing nothing about you.

### Installer options (only if you want them)

You can add these to the end of `bash install.sh`:

| Flag | What it means in plain English |
|---|---|
| `--yes` | "Don't ask me questions, just use the sensible defaults." |
| `--cpu-only` | "Ignore my GPU, run on the processor." (slower, but always works) |
| `--install-cuda` | "I have an NVIDIA card but no CUDA toolkit — install that for me too." |
| `--model=qwen2.5-7b` | "Download this specific model while you're at it." |
| `--auto-model` | "Pick the best model for my hardware and download it." |
| `--no-model` | "Don't download anything big — I'll add a model myself later." |
| `--latest` | "Use the newest versions of everything instead of the tested, frozen set." |
| `--skip-torch` | "Skip PyTorch." (saves space; disables self-training features) |

**Example — completely hands-off install with an automatic model:**

```bash
bash install.sh --yes --auto-model
```

### Windows

Double-click **`install.bat`** — it launches the full PowerShell installer, which does
the same job as the Linux one (CUDA install, dependency lock, GPU verification,
database setup). Options:

```bat
install.bat            (normal — NVIDIA CUDA install)
install.bat /cpu       (no GPU / force CPU)
install.bat /cuda      (also install the CUDA toolkit if missing)
```

Then launch with **`eli.bat`**.

### macOS

Same as Linux — `bash install.sh`. It automatically uses Apple's Metal GPU acceleration.
The first time ELI takes a screenshot or moves your mouse, macOS will ask you to allow
Screen Recording and Accessibility in System Settings → Privacy — grant them and retry.

---

## Part 2 — Giving ELI a brain (the model)

ELI needs a model file (a `.gguf` file) to think with. If you didn't grab one during
install, you have three easy options:

**Option A — let ELI pick for you** (measures your graphics card, picks what fits):

```bash
.venv/bin/python -m eli.core.model_download --auto
```

**Option B — see the menu and choose yourself:**

```bash
.venv/bin/python -m eli.core.model_download --list      # see what's on offer
.venv/bin/python -m eli.core.model_download --choose    # pick any number of them
```

| Model | Size | What you need | Who it's for |
|---|---|---|---|
| Qwen2.5-3B | ~1.8 GB | 4 GB GPU or CPU | Older machines, laptops |
| Qwen2.5-7B *(default)* | ~4.4 GB | 8 GB GPU | The sweet spot for most people |
| Qwen3-8B | ~4.7 GB | 8 GB GPU | Adds deeper reasoning |
| Falcon3-10B | ~5.9 GB | 12 GB GPU | Stronger answers |
| Phi-4 (14B) | ~8.4 GB | 12 GB GPU | High quality, MIT licensed |
| Qwen3.6-35B-A3B | ~20.6 GB | 24 GB GPU / big CPU | Enthusiast tier |
| Falcon-H1-34B | ~18.9 GB | 24 GB GPU / big CPU | Enthusiast tier |

**Option C — bring your own.** Download any chat/instruct `.gguf` file from the internet
(Hugging Face is the usual place) and drop it into the `models/` folder. ELI finds it
automatically and adapts itself to fit it into whatever memory you have. It is not locked
to any brand of model.

**The starter pack:** the release page also has a tag called `local-assets-v2.1`
containing a small starter model, the memory embedder, and voice files. If you have the
GitHub `gh` tool set up, `./RUN_ELI.sh --with-github-assets` (portable package) fetches
it all in one go.

---

## Part 3 — Starting ELI

### The desktop app (the main event)

```bash
./scripts/eli_launch.sh
```

or simply:

```bash
./eli.sh
```

The **first launch shows a setup wizard**: it asks what to call you, lets you pick your
model and voice, and explains the network toggle. ELI starts as a blank slate — it knows
nothing about you until you talk to it.

After install you'll also have **"ELI v2.0" in your app menu** (the installer adds
desktop icons on Linux), so you can start it with a click like any other program.

### Talking to it

Type in the chat box, or speak — say the wake word (you can set your own; train it in
Settings) and just talk. Ask it *"what can you do?"* and it will list everything —
all 208 of its capabilities, generated from what's genuinely wired in.

### The phone / tablet view (optional)

ELI has a built-in web page you can open from any device **on your own home network**.
The AI still runs on your computer — your phone is just a window onto it.

```bash
./scripts/eli_serve.sh          # just this computer → http://127.0.0.1:8081/
./scripts/eli_serve.sh --lan    # whole home network → prints a protected link + QR code
```

With `--lan` it automatically creates an access token and prints the exact address to
type into your phone's browser. Never expose this to the open internet — it's for your
home Wi-Fi only.

You can also run both at once (server in the background, desktop app in front):

```bash
./scripts/eli_launch.sh both --lan
```

### Terminal-only mode (no windows)

```bash
.venv/bin/python -m eli --headless
```

Commands inside it: `/status`, `/mode`, `/reset`, `/help`, `/quit`.

---

## Part 4 — The commands cheat-sheet

Everything in one place. Run these from the ELI folder.

**Install & repair**

```bash
bash install.sh                      # full install (asks first)
bash install.sh --yes --auto-model   # fully automatic install + model
./scripts/eli_setup.sh               # guided 8-step first-time setup (the gentle path)
```

**Launch**

```bash
./scripts/eli_launch.sh              # desktop app
./scripts/eli_launch.sh serve --lan  # web app for phone/tablet
./scripts/eli_launch.sh both --lan   # both at once
./eli.sh                             # desktop app (shortcut)
.venv/bin/python -m eli --headless   # text-only terminal mode
```

**Models**

```bash
.venv/bin/python -m eli.core.model_download --list     # what can I download?
.venv/bin/python -m eli.core.model_download --auto     # pick one for my hardware
.venv/bin/python -m eli.core.model_download --choose   # let me pick from a menu
.venv/bin/python -m eli.core.model_download --aux      # just the memory embedder
```

**Voice files** (if they didn't download during install)

```bash
.venv/bin/python -m eli.runtime.voice_assets
```

**Health checks**

```bash
bash run_tests.sh                    # run the test suite
bash eli_diagnose.sh                 # system diagnosis report
```

---

## Part 5 — Understanding the privacy switches

These are the promises the software makes, in plain terms:

- **Offline by default.** ELI blocks its own network access at a deep level (the socket
  layer). When it's offline, its own code *cannot* dial out even if it tries. You flip
  network access on with one toggle — and ELI announces when it goes online.
- **Your data stays put.** Conversations, your profile, memories — all in local database
  files inside the ELI folder (`artifacts/`). Delete them any time; ELI simply starts
  fresh.
- **No account, no telemetry.** Nothing phones home. There's nothing to phone home *to*.
- **One honest caveat:** ELI can run commands and read files on your computer — that's
  its job as an assistant. Its safety rails are good but not a prison; treat it like a
  capable tool you're in charge of, not a sandboxed toy. The details live in
  `SECURITY.md`.

---

## Part 6 — When something goes wrong

| Symptom | The fix |
|---|---|
| "Python 3.10+ required" | Install Python from python.org (Windows) or your package manager (`sudo apt install python3`). |
| ELI is painfully slow | Your AI engine is probably running on CPU. Re-run `bash install.sh --install-cuda` (NVIDIA). The installer tells you at the end whether GPU offload is on. |
| `.venv not found — run install.sh first` | You skipped the install, or you're in the wrong folder. `cd` into the ELI folder and run `bash install.sh`. |
| No sound / voice doesn't work | Run `.venv/bin/python -m eli.runtime.voice_assets`, and make sure `ffmpeg` and `portaudio` installed (the installer prints the exact command if it couldn't do it itself). |
| First reply after launch is slow | Normal — the model loads into memory on first use. A big model can take a minute. |
| Out-of-memory / crashes mid-answer | Your model is too big for your GPU/RAM. Download a smaller one (`--auto` picks a safe size). |
| Phone can't reach the web app | Use `--lan`, make sure both devices are on the same Wi-Fi, and check your firewall allows port 8081. |
| macOS won't screenshot / move mouse | System Settings → Privacy & Security → grant Screen Recording + Accessibility, then retry. |
| Wrong model loaded | Settings tab → pick a different model, or drop a new `.gguf` into `models/`. |

Still stuck? Open an issue with what you saw:
**https://github.com/ShadowESC95/ELI_v2.0/issues** — a plain "I tried it and this
happened" is genuinely useful.

---

## Part 7 — Removing ELI

ELI never spreads itself around your system. To remove it completely:

```bash
rm -rf /path/to/ELI_v2.0        # the folder is the whole install
```

That's it — models, databases, settings, everything lives inside that one folder.
(If you added the app-menu icons, remove them with your desktop's app editor or delete
the `.desktop` files from `~/.local/share/applications/`.)

---

*ELI v2.0 — © 2026 Jason Fitzgibbon Bridgeman. Source-available under the PolyForm
Internal Use License 1.0.0 (free to use and modify on your own machine; not for
redistribution). Questions: jaybridgeman0095@gmail.com*
