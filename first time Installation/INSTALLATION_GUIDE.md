# ELI v2 — Installation Guide (every OS / machine / user)

**Version:** 2.4.25 · **Updated:** 2026-09-12  
**Release:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.25

This guide answers: **which download, which first click, and what the wizard actually installs.**

ELI is **local-first**. Inference stays on your machine. Offline-by-default after setup; model / voice / embedder downloads are deliberate one-time steps.

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

Legacy names (`INSTALL_ELI.sh`, `install_eli.sh`, `eli_one_click_setup.sh`) only **redirect** here.

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

**Hardware policy (same on every entrypoint):**

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
- Windows TTS needs a Piper **CLI** (`piper.exe`) on PATH or under `tts_piper/` in addition to voice weights (weights alone are not enough).

So: the wizard makes **chat + memory + voice + GUI** complete and hardware-aware. It does **not** magically install every optional OS package or every optional model on every board.

---

## 2. Pick your download

| You are… | Download | First action |
|----------|----------|--------------|
| Windows, simplest | `ELI-Setup-2.4.25.exe` | Run Setup |
| Windows, unzip | `ELI_v2-*-windows-x64.zip` | `ELI\ELI.exe` |
| Linux, simplest | `ELI_v2-*-x86_64.AppImage` | `chmod +x` → run |
| Linux, editable | `*-linux-portable.tar.gz` | `./ELI_Setup.sh` |
| macOS Apple Silicon | `*-macos-arm64.dmg` | Drag to Applications |
| Clone / developer | git checkout | `./scripts/eli_setup.sh` |
| Android Termux | tree / clone | `bash scripts/install_android.sh` |

---

## 3. Step-by-step

### Linux AppImage
```bash
chmod +x ELI_v2-2.4.25-x86_64.AppImage
./ELI_v2-2.4.25-x86_64.AppImage
```

### Linux portable
```bash
tar -xzf ELI_v2-2.4.25-linux-portable.tar.gz
cd ELI_v2-2.4.25-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
./RUN_ELI.sh
```

### Windows Setup
Run **`ELI-Setup-2.4.25.exe`**. Desktop shortcut is **ELI only** (Server in Start Menu). A second GUI instance is refused (singleton). Data: `%LOCALAPPDATA%\ELI_v2\`.

### macOS
Open the `.dmg`, drag to Applications, launch (Metal).

### Override CPU/GPU
```bash
ELI_INSTALL_CPU_ONLY=1 ./ELI_Setup.sh
ELI_INSTALL_CPU_ONLY=0 ./ELI_Setup.sh
# or ELI_FORCE_GPU=1
```

---

## 4. After setup

| Goal | Action |
|------|--------|
| Desktop | `./RUN_ELI.sh` / AppImage / `ELI.exe` |
| Phone on Wi‑Fi | Settings → Web Server (token URL). **Home** tab = MQTT devices, not Home Assistant |
| Missing asset | Wizard Retry, or `python -m eli.core.model_download --aux` / `python -m eli.runtime.voice_assets` |
| Status | `python -m eli.setup --status` |

---

## 5. Troubleshooting (2.4.25)

| Symptom | Fix |
|---------|-----|
| Two Windows GUIs | Use 2.4.23+ Setup; close extra; singleton blocks seconds |
| Portable dies mid-scan | Use 2.4.22+ (`_gpu_pipeline`); prefer `./ELI_Setup.sh` |
| Nomic / Piper missing | Wizard hard-fails until fixed — Retry / Fetch |
| Iris Xe OOM on install | Wizard CPU policy, or AppImage — not interactive Vulkan `install.sh` |
| Wrong `eli` / still loads old 2.4.23 | Open a **new** terminal; `bash scripts/fix_eli_shell_env.sh --yes`; re-run `./scripts/install_desktop_apps.sh`. Do not keep two portables active in the same shell. |
| Dead `nvidia-smi` + CUDA plan | 2.4.25+ treats driver errors as no NVIDIA → CPU wheels |
| Windows Web Server / no LAN QR | 2.4.25+ uses `ELI-Server.exe` on frozen Windows, paints QRs as soon as the pair URL exists, and bundles `segno` |

Maintainer map: **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)**.
