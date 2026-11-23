# ELI v2 — Installation Guide (every OS / machine / user)

**Version:** 2.5.36 · **Updated:** 2026-11-20  
**Release:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.5.40

This guide answers: **which download, which first click, and what the wizard actually installs.**

ELI is **local-first**. Inference stays on your machine. Offline-by-default after setup; model / voice / embedder downloads are deliberate one-time steps. From v2.5.36 ELI v2 is open source under the Apache License 2.0 (`LICENSE`, `NOTICE`).

---

## 0. One path

```
GitHub Releases → pick OS asset
        ↓
  Frozen?  → AppImage / ELI-Setup.exe / .dmg / zip→ELI.exe
  Source?  → ./ELI_Setup.sh  |  ELI_Setup.bat  |  ./scripts/eli_setup.sh
        ↓
  GUI wizard → hardware_policy → install.sh | install.ps1  (once)
        ↓
  databases + nomic + Piper/Whisper + chat GGUF (+ desktop icons)
        ↓
  Launch
```

Legacy names (`INSTALL_ELI.sh`, `install_eli.sh`, `eli_one_click_setup.sh`) only **redirect** here. `ELI_Setup.sh`, `INSTALL_ELI.sh` and `RUN_ELI.sh` are in the portable package; `ELI_Setup.bat` is in the Windows source zips (`ELI_v2-*-windows-portable*.zip`).

---

## 1. Does the wizard install “everything” for full functionality?

**Core product — yes (hard-fail until present):**

| Stage | What you get |
|-------|----------------|
| Core env | `.venv`, PySide6 (GUI), torch, **llama-cpp** matched to hardware, Python deps |
| Databases | Blank local SQLite stores |
| Memory | **nomic** embedder (`model_download --aux`) |
| Voice | **Piper** TTS weights + **Whisper** STT cache |
| Chat | Starter **GGUF** sized by hardware (`--auto-model`) — any compatible GGUF later |
| Shortcuts | App menu / Start Menu where the OS supports it |

**Hardware policy (the wizard and `ELI_Setup.sh`; `install.sh` run by hand detects the same GPUs and, on an Intel iGPU or a Qualcomm Adreno with more than 8 GB RAM, may try a Vulkan build first):**

| Hardware | Backend |
|----------|---------|
| NVIDIA | CUDA |
| AMD | ROCm → Vulkan → CPU |
| Intel Arc | Vulkan |
| Apple Silicon | Metal |
| Intel Iris Xe / UHD, ≤8 GB RAM, no discrete GPU | **CPU-only** |
| Headless / no GPU | CPU |

**Best-effort (not hard-fail — may need admin / package manager):**  
OS tools such as `mpv`, `ffmpeg`, `tesseract`, `yt-dlp` (pip), clipboard/screenshot helpers. Installer tries; if the OS blocks them, features that need them show the exact install command when used.

**Not claimed as “100% on every machine”:**

- A chat model larger than your RAM/VRAM will be slow or fail to load — pick a smaller GGUF.
- Optional extras (XTTS “natural” voice, large vision models, CUDA *toolkit* via `--install-cuda`) are opt-in.
- Frozen **AppImage** GPU packs are separate from portable `.venv` Vulkan builds.
- Phones/tablets are **clients** of the PC/laptop web server — not native tablet apps.
- Speech uses a Piper program when one is found and otherwise the Piper library ELI installs (`piper-tts`), so on Windows too the voice weights are all that is needed (since v2.5.30).
- A Linux source install on NVIDIA usually builds the inference engine with CUDA on the machine (the prebuilt CUDA wheels stop below the llama-cpp-python 0.3.35 it needs), which takes NVIDIA's CUDA toolkit (`nvcc`); without it the install builds a CPU engine and says so (`install.sh --install-cuda` fetches the toolkit). The frozen downloads need no toolkit: their GPU pack is prebuilt.

So: the wizard makes **chat + memory + voice + GUI** complete and hardware-aware. It does **not** magically install every optional OS package or every optional model on every board.

---

## 2. Pick your download

| You are… | Download | First action |
|----------|----------|--------------|
| Windows, simplest | `ELI-Setup-<version>.exe` | Run Setup |
| Windows, unzip | `ELI_v2-*-windows-x64.zip` | `ELI\ELI.exe` |
| Windows, from source | `ELI_v2-*-windows-portable.zip` (or `-portable-full.zip`, offline) | `ELI_Setup.bat` or `install.bat` |
| Linux, simplest (glibc 2.39 or newer) | `ELI_v2-*-x86_64.AppImage` | `chmod +x` → run |
| Linux, editable / older system | `*-linux-portable.tar.gz` | `./ELI_Setup.sh` |
| Debian / Ubuntu package | `ELI_v2-*-amd64.deb` | `eli-v2` (first start installs into `~/.local/share/ELI_v2`) |
| macOS Apple Silicon | `*-macos-arm64.dmg` | Drag to Applications |
| Clone / developer | git checkout | `./scripts/eli_setup.sh` |
| Android Termux | tree / clone | `bash scripts/install_android.sh` |

---

## 3. Step-by-step

### Linux AppImage
```bash
chmod +x ELI_v2-*-x86_64.AppImage
./ELI_v2-*-x86_64.AppImage
```

### Linux portable
```bash
tar -xzf ELI_v2-*-linux-portable.tar.gz
cd ELI_v2-*-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
./RUN_ELI.sh
```

### Windows Setup
Run **`ELI-Setup-<version>.exe`**. Desktop shortcuts are **ELI** and **Uninstall ELI** (Server in Start Menu). A second GUI instance is refused (singleton). Data: `%LOCALAPPDATA%\ELI_v2\` (an uninstall leaves it; Setup's "Fresh install" option resets it, keeping downloaded models).

### macOS
Open the `.dmg`, drag to Applications, launch (Metal).

### Override CPU/GPU
```bash
ELI_INSTALL_CPU_ONLY=1 ./ELI_Setup.sh
ELI_INSTALL_CPU_ONLY=0 ./ELI_Setup.sh
# or ELI_FORCE_GPU=1
```
`ELI_Setup.sh` itself takes no options; these variables are how its hardware choice is overridden. `ELI_INSTALL_CPU_ONLY=0` and `ELI_FORCE_GPU=1` make the build for the GPU found even where the CPU build would be chosen (an Intel iGPU, or 8 GB of RAM or less).

---

## 4. After setup

| Goal | Action |
|------|--------|
| Desktop | `./RUN_ELI.sh` / `eli-v2` / AppImage / `ELI.exe` |
| Phone on Wi‑Fi | Settings → Web Server (token URL + QR). The served page's **Home** tab = MQTT devices, not Home Assistant |
| Missing asset | Wizard Retry, or `python -m eli.core.model_download --aux` / `python -m eli.runtime.voice_assets` |
| Status | `python -m eli.setup --status` (source / portable installs) |
| Licence | `./eli.sh --license` / `./ELI_v2-*.AppImage --license` / `ELI-Server.exe --license` |

---

## 5. Troubleshooting (fixes by version)

| Symptom | Fix |
|---------|-----|
| Two Windows GUIs | Use 2.4.23+ Setup; close extra; singleton blocks seconds |
| Portable dies mid-scan | Use 2.4.22+ (`_gpu_pipeline`); prefer `./ELI_Setup.sh` |
| Nomic / Piper missing | Wizard hard-fails until fixed — Retry / Fetch |
| Iris Xe OOM on install | Wizard CPU policy, or AppImage — not interactive Vulkan `install.sh` |
| Wrong `eli-v2` / still loads old portable | Open a **new** terminal; run AppImage `--integrate` (rewrites menu + `~/.local/bin/eli-v2`); or from the folder you want, `bash scripts/fix_eli_shell_env.sh --yes` (reinstalls `eli-v2` / `eli2`) |
| Menu / Server icon opens deleted AppImage | 2.4.37+ auto-refreshes `.desktop` on version bump; or `./ELI_v2-*-x86_64.AppImage --integrate` |
| “Yes” to install mpv does nothing / LLM talks | 2.4.37+ Phase-45 `CONFIRM_PENDING_REMEDIATION` (first yes runs apt) |
| Dead `nvidia-smi` + CUDA plan | 2.4.25+ treats driver errors as no NVIDIA → CPU wheels |
| `libcudart.so.12` / incomplete GPU pack | 2.4.27+; `./ELI_v2-*-x86_64.AppImage --remove-gpu-pack` (removes `~/.local/share/ELI_v2/runtime/gpu`) and relaunch AppImage (Iris/AMD get Vulkan; NVIDIA CUDA packs vendor cudart) |
| GPU pack: `no CUDA wheel` + offline mode | 2.4.26+ scoped NetGuard allow + CI cuda fallback |
| GPU pack verify deletes pack after finding GPU | 2.4.29+ keeps pack whenever `ggml_cuda_init` enumerated devices (even if the probe then crashes); also 2.4.27+ cudart 12.6 |
| Check-in invents old GPU layers (e.g. 26/28) / denies knowing the day | 2.4.30+ continuity guard + CURRENT TIME day rule; ask GPU_STATUS only when you want layers |
| “Explain why you used DATE…” returns only the date | 2.4.30+ meta-DATE questions stay CHAT instead of Phase-45 DATE |
| “just checking in / what have you been doing?” → version/git data dump | 2.4.37+ “checking in” is rapport, not maintenance SELF_REPORT; keeps selected reasoning mode |
| Windows Web Server / no LAN QR | 2.4.25+ uses `ELI-Server.exe` on frozen Windows, paints QRs as soon as the pair URL exists, and bundles `segno` |
| Big GGUF “loaded” then aborts on first decode (ctx/batch ≫ VRAM) | 2.4.37+ checks **ctx and batch** too, not only GPU layers; since 2.5.18 the load plan simulates the load first (llama-cpp-python 0.3.35+) and keeps the largest settings that fit every device |
| Log shows only `127.0.0.1` / phone cannot connect | Localhost mode is intentional — use **Start (phone / Wi‑Fi)** or `--lan` for QR + LAN |
| Desktop / menu icon: Failed to change to directory `…/ELI_v2-*-linux-portable` | **Do not click the old icon** (GNOME dies on `Path=` before Exec). From the **NEW** folder: `bash scripts/fix_eli_desktop_icons.sh --install`. AppImage: `./ELI_v2-*-x86_64.AppImage --integrate`. |

Maintainer map: **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)**.
