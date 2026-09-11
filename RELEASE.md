# ELI v2.0 — cutting a download-and-run release

> Maintainer walkthrough: **`blueprints/v2_release.pdf`** (local markdown also under `blueprints/`)  
> **New users:** **`blueprints/new_user_install_guide.pdf`** — full install commands for Linux, Windows, and macOS.

Current semver: **`pyproject.toml`** → **2.4.23** (tag **`v2.4.23`**).

## 1. Build packages

**CI / tag push (recommended):**

Push tag `v2.4.23` — `.github/workflows/release.yml` builds AppImage, portable tar, Windows zip/Setup, and uploads to GitHub Releases.

**Linux AppImage + portable (local):**

```bash
bash scripts/build_grandma_release.sh
# Output:
#   dist/app_packages/ELI_v2-<ver>-x86_64.AppImage
#   dist/app_packages/ELI_v2-<ver>-linux-portable.tar.gz
```

**Portable only:**

```bash
bash scripts/build_v2_release.sh
# Output: dist/app_packages/ELI_v2-2.4.23-linux-portable.tar.gz
```

**Windows Setup.exe** (run on a Windows PC with [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
# Frozen (what GitHub Releases ship):
pyinstaller --noconfirm ELI.spec
python scripts/make_installer_license.py
iscc packaging\windows\installer.iss /DMyAppVersion=2.4.23
# Output: dist/ELI-Setup-2.4.23.exe
```

> Do **not** confuse with `packaging/windows/ELI_Setup.iss` (source-portable tree).
> Releases use **`ELI-Setup-<v>.exe`** → `%LOCALAPPDATA%\Programs\ELI`.
> The source Setup installs into `%LOCALAPPDATA%\ELI_v2` (same folder frozen uses for **data**) — mixing them corrupts installs.

## 2. What each asset is for

| Asset | Use |
|---|---|
| `ELI-Setup-<v>.exe` | Windows one-click (frozen) |
| `ELI_v2-<v>-windows-x64.zip` | Windows unzip → `ELI\ELI.exe` (no Setup.bat) |
| `ELI_v2-<v>-x86_64.AppImage` | Linux double-click (frozen) |
| `ELI_v2-<v>-linux-portable.tar.gz` | Linux source + `./ELI_Setup.sh` (**CPU-first** on Iris Xe / ≤8 GB) |
| `ELI_v2-<v>-macos-arm64.dmg` | macOS Apple Silicon |

**One installer:** `./ELI_Setup.sh` (or `INSTALL_ELI.sh`) → `scripts/eli_setup.sh` → GUI wizard → `install.sh` / `install.ps1` once, hardware-aware via `eli.setup.hardware_policy` (NVIDIA/AMD/Arc/Metal → GPU; Iris Xe / ≤8 GB → CPU). Legacy aliases `install_eli.sh` / `eli_one_click_setup.sh` only redirect there.

## 3. Tag and publish

```bash
git tag v2.4.23 && git push origin v2.4.23
```

CI publishes the GitHub Release when the workflow finishes (~45–60 min).
