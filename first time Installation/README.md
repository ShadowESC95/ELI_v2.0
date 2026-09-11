# ELI v2 — First-Time Installation

**Start here if you have never installed ELI before.**  
**Current release: 2.4.23** — https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.23

| Document | Who it's for |
|----------|----------------|
| **[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)** | Everyone — which download, which first click, every OS / CPU / GPU |
| **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)** | Maintainers — every script and Python entry in detail |

### Fastest paths (pick one)

| You have… | Run this first |
|-----------|----------------|
| Linux, want zero build | **AppImage** → `chmod +x` → double-click |
| Linux portable `.tar.gz` | **`./ELI_Setup.sh`** only (GUI wizard; hardware-aware) |
| Git clone | **`./scripts/eli_setup.sh`** |
| Windows, simplest | **`ELI-Setup-*.exe`** |
| Windows frozen zip | **`ELI\ELI.exe`** |
| Windows source/scripts zip | **`ELI_Setup.bat`** |
| macOS Apple Silicon | **`.dmg`** → Applications |
| Android Termux | **`bash scripts/install_android.sh`** |

### What changed in 2.4.23 (install)

- **One funnel:** `eli_one_click_setup` / `install_eli` only **redirect** to `eli_setup` → GUI wizard.
- **Hardware policy** (`eli.setup.hardware_policy`): GPU PCs get CUDA/ROCm/Arc/Metal; Iris Xe / ≤8 GB get CPU-only.
- **Wizard owns install once** (no double full `install.sh`).
- **Assets hard-fail** until nomic + Piper/Whisper succeed.
- **Windows:** one desktop ELI icon; GUI singleton stops a second window.

Do **not** run interactive `bash install.sh` on low-RAM Intel laptops unless you pass `--cpu-only` or `--yes` (auto CPU on Iris Xe / ≤8 GB).
