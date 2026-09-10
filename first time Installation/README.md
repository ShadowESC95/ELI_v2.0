# ELI v2 — First-Time Installation

**Start here if you have never installed ELI before.**

| Document | Who it's for |
|----------|----------------|
| **[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)** | Everyone — plain-English “dummy guide”: which file to run first, on every OS, with troubleshooting |
| **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)** | Maintainers and advanced users — every `.sh` / `.bat` / `.ps1` / Python install entry point in detail |

**Fastest paths (pick one):**

| You have… | Run this first |
|-----------|----------------|
| Linux, want zero build | Download **AppImage** from [Releases](https://github.com/ShadowESC95/ELI_v2.0/releases/latest), `chmod +x`, double-click |
| Linux portable `.tar.gz` | `./ELI_Setup.sh` — if PySide6 errors, `bash install.sh --yes --auto-model` |
| Git clone / developer | `./scripts/eli_setup.sh` or `bash install.sh` |
| Windows zip / Setup.exe | `ELI_Setup.bat` or `install.bat` |
| Android Termux | `bash scripts/install_android.sh` |

Current release: see `pyproject.toml` (tag **`v2.4.8`**+).
