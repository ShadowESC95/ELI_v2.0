# ELI v2 — Installation Guide (every OS / machine / user)

**Version:** 2.4.23 · **Updated:** 2026-09-12  
**Release:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.23

This guide answers one question: **which download do I pick, and what do I run first?**

ELI is **local-first**. Inference stays on your machine. Offline-by-default networking still applies after install; model / voice / embedder downloads are deliberate one-time steps.

---

## 0. One sentence (read this)

**There is one installer path.** Everything else is either a frozen app, or a thin redirect into that path.

```
GitHub Releases → pick your OS asset
        ↓
  Frozen?  → double-click (AppImage / ELI-Setup.exe / .dmg / zip→ELI.exe)
  Source?  → ./ELI_Setup.sh   (or ELI_Setup.bat / scripts/eli_setup.sh)
        ↓
  GUI wizard (eli.setup) → hardware policy → install.sh | install.ps1  (once)
        ↓
  embedder (nomic) + voice (Piper/Whisper) + chat model
        ↓
  Launch: ./RUN_ELI.sh  |  eli.bat  |  AppImage / ELI.exe
```

| Do this | Do **not** do this |
|---------|-------------------|
| `./ELI_Setup.sh` / `ELI_Setup.bat` / `ELI-Setup-*.exe` | Interactive `bash install.sh` on an 8 GB Iris Xe laptop (tries Vulkan → OOM) |
| Let the wizard finish nomic + Piper | Rely on `scripts/install_eli.sh` as a real installer (it only **redirects**) |
| AppImage on lean Linux distros | Expect portable Setup to auto-install GPU packs like the AppImage |

---

## 1. Pick your download (GitHub Releases)

| You are… | Download | First action | Builds a `.venv`? |
|----------|----------|--------------|-------------------|
| **Windows, want simplest** | `ELI-Setup-<v>.exe` | Run the Setup | No (frozen) |
| **Windows, unzip-and-run** | `ELI_v2-<v>-windows-x64.zip` | `ELI\ELI.exe` | No (frozen) |
| **Windows, source/portable zip** | windows portable / lean zip with scripts | `ELI_Setup.bat` | Yes |
| **Linux, want simplest** | `ELI_v2-<v>-x86_64.AppImage` | `chmod +x` → run | No (frozen) |
| **Linux, editable / laptop CPU** | `ELI_v2-<v>-linux-portable.tar.gz` | `./ELI_Setup.sh` | Yes |
| **macOS Apple Silicon** | `ELI_v2-<v>-macos-arm64.dmg` | Drag to Applications | No (frozen) |
| **Developer / clone** | `git clone …/ELI_v2.0` | `./scripts/eli_setup.sh` | Yes |
| **Android Termux** | clone or portable tree | `bash scripts/install_android.sh` | Yes (CPU headless) |

**No release includes a chat model.** The wizard downloads one sized to your hardware. Frozen builds usually ship **nomic** + **Piper weights**; Windows TTS still needs a Piper **CLI** (`piper.exe`) on PATH or under `tts_piper/`.

---

## 2. How machines differ (hardware policy)

The wizard and `eli.setup.hardware_policy` choose **CPU-only vs GPU** the same way on every entrypoint:

| Hardware | Install path | Notes |
|----------|--------------|-------|
| **NVIDIA** (desktop / laptop) | GPU (CUDA) | Best case for speed |
| **AMD** discrete | GPU (ROCm → Vulkan → CPU) | Needs toolkit / Mesa |
| **Intel Arc** | GPU (Vulkan) | Discrete — **not** forced CPU |
| **Apple Silicon** | Metal | macOS `.dmg` / `install.sh` |
| **Intel Iris Xe / UHD** (integrated) | **CPU-only** | Portable Vulkan source builds often OOM on ≤8 GB |
| **≤ 8 GB RAM**, no NVIDIA/AMD/Arc | **CPU-only** | Reliable wheels |
| **Qualcomm Adreno** | Vulkan optional | Keep batch ≤ 32 |
| **No GPU** | CPU-only | Slow but works |

Override anytime:

```bash
ELI_INSTALL_CPU_ONLY=1 ./ELI_Setup.sh   # force CPU
ELI_INSTALL_CPU_ONLY=0 ./ELI_Setup.sh   # allow GPU path
# or: ELI_FORCE_GPU=1
```

**Why the AppImage worked when portable failed on the same laptop:** AppImage is a **frozen** binary (no host venv compile). Portable runs `install.sh` and builds `llama-cpp-python` for *your* machine — that is where Iris Xe / RAM / pin conflicts used to hurt. **2.4.23** routes every script into the same policy + wizard so those paths agree.

---

## 3. Step-by-step by OS

### A. Linux AppImage (recommended for most Linux users)

```bash
chmod +x ELI_v2-2.4.23-x86_64.AppImage
./ELI_v2-2.4.23-x86_64.AppImage
```

- First run may copy under `~/.local/share/ELI_v2/` and offer a GPU pack / starter model.
- Menu entries: ELI, ELI Server (phone/web), Uninstall.
- On Ubuntu 24.04 you may need `libfuse2` (`sudo apt install libfuse2t64`) for FUSE runs.

### B. Linux portable tarball (source tree + one-click wizard)

```bash
tar -xzf ELI_v2-2.4.23-linux-portable.tar.gz
cd ELI_v2-2.4.23-linux-portable   # folder name may vary slightly
chmod +x ELI_Setup.sh RUN_ELI.sh install.sh
./ELI_Setup.sh                    # ← only first-time command you need
```

What happens:

1. Detects display → opens **Unified Install Wizard**
2. Hardware policy sets CPU vs GPU
3. Wizard streams **`install.sh --yes [--cpu-only] --auto-model` once**
4. Stages: database → **nomic embedder** → **voice** → chat model → desktop icons
5. When done: `./RUN_ELI.sh`

**If the GUI never opens (SSH / no Qt):**

```bash
bash install.sh --yes --auto-model          # policy inside install.sh still protects Iris Xe / ≤8 GB under --yes
# or force:
bash install.sh --yes --cpu-only --auto-model
./RUN_ELI.sh
```

**Extract on ext4/btrfs**, not NTFS/exFAT (SQLite WAL issues on dual-boot data drives).

### C. Linux / macOS git clone

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
./scripts/eli_setup.sh
```

Same wizard as portable. Daily launch: `./scripts/eli_launch.sh` or `./eli.sh`.

### D. Windows — frozen Setup (recommended)

1. Download `ELI-Setup-2.4.23.exe`
2. Run it (per-user, no admin required)
3. Optional NVIDIA GPU pack during install
4. Start Menu: **ELI**, **ELI Server (phone and web)**, Uninstall  
   Desktop: **ELI only** (Server is *not* on the desktop — that used to open two windows)
5. Finish → one GUI. A second launch shows “ELI is already running” (singleton)

Data: `%LOCALAPPDATA%\ELI_v2\` (survives upgrades). Program: `%LOCALAPPDATA%\Programs\ELI\`.

### E. Windows — frozen zip

Unzip → run `ELI\ELI.exe`. No `Setup.bat` in the frozen zip.

### F. Windows — source / lean portable (scripts present)

```bat
ELI_Setup.bat
```

Runs `install.ps1 -Yes -AutoModel` if needed, then `python -m eli.setup --full-install`.

### G. macOS (Apple Silicon)

Open the `.dmg`, drag ELI to Applications, launch. Metal is automatic. First run offers a starter model.

### H. Android / Termux

```bash
bash scripts/install_android.sh
# or: python -m eli.setup --full-install
python -m eli.cli.headless
```

CPU-only, no desktop GUI profile.

---

## 4. Script map (what each file *really* does in 2.4.23)

### Canonical (use these)

| File | Role |
|------|------|
| **`ELI_Setup.sh` / `INSTALL_ELI.sh`** | → `scripts/eli_setup.sh` |
| **`scripts/eli_setup.sh`** | One-click: Qt bootstrap → GUI wizard → hardware policy |
| **`python -m eli.setup --full-install`** | The wizard itself |
| **`install.sh` / `install.ps1`** | Core engine (venv, torch, llama, deps) — called by the wizard |
| **`eli.setup.hardware_policy`** | Shared CPU/GPU decision for every OS |
| **`RUN_ELI.sh` / `eli_startup.sh`** | Launch after install (auto-setup only if `.venv` missing) |
| **`eli_launch.sh` / `eli.sh` / `eli.bat`** | Daily GUI |
| **`eli_serve.sh` / ELI-Server.exe`** | Phone/web server only |

### Compatibility aliases (safe, but not separate installers)

| File | Reality |
|------|---------|
| **`scripts/eli_one_click_setup.sh`** | Redirects to `eli_setup.sh` |
| **`scripts/install_eli.sh`** | Redirects to `eli_setup.sh` (legacy pip path **removed**) |

### Special-purpose (keep)

| File | When |
|------|------|
| **`scripts/safe_install_linux.sh`** | Wipe `.venv`, rotate secrets, hardened settings |
| **`scripts/install_android.sh`** | Termux / headless |
| **`scripts/fix_eli_shell_env.sh`** | Fix stale `eli` shell alias when v2 and v3 coexist |

---

## 5. Assets the wizard must finish

| Asset | Why | Command if missing |
|-------|-----|--------------------|
| **Chat GGUF** | Conversation | `python -m eli.core.model_download --auto` |
| **nomic embedder** | Memory / RAG | `python -m eli.core.model_download --aux` |
| **Piper + Whisper** | Voice | `python -m eli.runtime.voice_assets` |

Stages **hard-fail** in the wizard if nomic/voice are missing (exit codes are real). First-boot “Fetch embedder + voice” opens a **scoped** network window (offline-by-default stays intact for ambient traffic).

**Home tab ≠ Home Assistant.** In-app **Home** is ELI’s MQTT / device console. Phone chat uses **Settings → Web Server** or **ELI Server**.

---

## 6. After install — daily use

| Goal | Command |
|------|---------|
| Desktop GUI | `./RUN_ELI.sh` · `./scripts/eli_launch.sh` · AppImage · `ELI.exe` |
| Phone on Wi‑Fi | Settings → Web Server → phone mode, **or** Start Menu **ELI Server** |
| Re-run incomplete assets | `python -m eli.setup --run-remaining` or `./ELI_Setup.sh` again |
| Status checklist | `python -m eli.setup --status` |

---

## 7. Troubleshooting (2.4.23)

| Symptom | Fix |
|---------|-----|
| Two Windows GUIs after Setup | Upgrade to 2.4.23+; desktop is ELI-only; close the extra window |
| Portable dies at “Scanning hardware” | Fixed in 2.4.21–2.4.22 (`_gpu_pipeline`); use 2.4.23+ |
| `fsspec` / datasets conflict | Fixed pin; do not use old pip-only `install_eli` behaviour |
| Nomic / Piper “won’t download” | Use wizard Retry, or `--aux` / `voice_assets` above |
| Web URL shows `<this-computer-ip>` | Fixed LAN resolve (incl. Windows); use token URL from the GUI |
| Iris Xe OOM during install | Use AppImage, or `./ELI_Setup.sh` (CPU policy), not interactive Vulkan `install.sh` |
| Wrong `eli` command (v2 vs v3) | `bash scripts/fix_eli_shell_env.sh --yes` |

More detail: `blueprints/common_errors_and_fixes.md`, `docs/SERVER_AND_WEB_APP.md`.

---

## 8. Maintainer deep dive

Every script flag and Python module: **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)**  
Release cut notes: repo root **`RELEASE.md`**.
