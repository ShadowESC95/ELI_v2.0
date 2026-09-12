# ELI v2 — First-Time Installation

**Current release: 2.4.25** — https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.25

| Document | Who it's for |
|----------|----------------|
| **[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)** | Everyone — downloads, wizard completeness, hardware matrix |
| **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)** | Maintainers — every script entry |

### Fastest paths

| You have… | Run this first |
|-----------|----------------|
| Linux, zero build | **AppImage** |
| Linux portable | **`./ELI_Setup.sh`** |
| Git clone | **`./scripts/eli_setup.sh`** |
| Windows | **`ELI-Setup-*.exe`** |
| Windows zip (frozen) | **`ELI\ELI.exe`** |
| macOS | **`.dmg`** |
| Android Termux | **`bash scripts/install_android.sh`** |

**Wizard core:** env + llama + DB + nomic + Piper/Whisper + chat GGUF (hard-fail until present). OS extras (mpv, tesseract, …) are best-effort. Windows desktop = one ELI icon; GUI singleton.
