# ELI v2.0 — cutting a download-and-run release

> Maintainer walkthrough: **`blueprints/v2_release.pdf`**  
> **New users:** **`first time Installation/INSTALLATION_GUIDE.md`**

Current semver: **`pyproject.toml`** → **2.4.25** (tag **`v2.4.25`**).

## 1. Build packages

**CI / tag push (recommended):** push tag `v2.4.25` — workflow builds AppImage, portable, Windows, macOS.

**Local Linux AppImage + portable:**

```bash
SKIP_TESTS=1 bash scripts/build_grandma_release.sh
```

## 2. What each asset is for

| Asset | Use |
|---|---|
| `ELI-Setup-<v>.exe` | Windows one-click (frozen). Desktop = ELI only; GUI singleton. |
| `ELI_v2-<v>-windows-x64.zip` | Unzip → `ELI\ELI.exe` |
| `ELI_v2-<v>-x86_64.AppImage` | Linux double-click (frozen) |
| `ELI_v2-<v>-linux-portable.tar.gz` | `./ELI_Setup.sh` → hardware-aware wizard |
| `ELI_v2-<v>-macos-arm64.dmg` | macOS Apple Silicon |

**One installer:** `./ELI_Setup.sh` / `ELI_Setup.bat` / `ELI-Setup-*.exe` → GUI wizard → `eli.setup.hardware_policy` → one `install.sh`/`install.ps1`. Core stages (env, DB, nomic, voice, chat GGUF) hard-fail until present. OS tools (mpv, tesseract, …) best-effort.

## 3. Tag and publish

```bash
git tag v2.4.25 && git push origin v2.4.25
```
