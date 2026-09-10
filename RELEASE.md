# ELI v2.0 — cutting a download-and-run release

> Maintainer walkthrough: **`blueprints/v2_release.pdf`** (local markdown also under `blueprints/`)  
> **New users:** **`blueprints/new_user_install_guide.pdf`** — full install commands for Linux, Windows, and macOS.

Current semver: **`pyproject.toml`** → **2.4.8** (tag **`v2.4.8`**).

## 1. Build packages

**CI / tag push (recommended):**

Push tag `v2.4.8` — `.github/workflows/release.yml` builds AppImage, portable tar, Windows zip/Setup, and uploads to GitHub Releases.

**Grandma-friendly (Linux AppImage + portable, local):**

```bash
bash scripts/build_grandma_release.sh
# Output:
#   dist/app_packages/ELI_v2-<ver>-x86_64.AppImage      ← double-click Linux
#   dist/app_packages/ELI_v2-<ver>-linux-portable.tar.gz
```

**Portable only:**

```bash
bash scripts/build_v2_release.sh
# Output: dist/app_packages/ELI_v2-2.4.8-linux-portable.tar.gz
```

**Windows Setup.exe** (run on a Windows PC with [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
bash build_packages.sh windows-lean
powershell -ExecutionPolicy Bypass -File packaging/windows/build-windows.ps1 -Version 2.4.6
# Output: dist/ELI_v2-2.4.8-Setup.exe
```

Optional full bundle (local models — very large):

```bash
bash scripts/build_v2_release.sh --with-assets
```

Other platforms (maintainer hosts):

```bash
bash build_packages.sh wheel windows macos appimage
```

**GPU pack wheels** (bundled in AppImage when size allows): built via `scripts/package_desktop_app.sh` → `packaging/pyinstaller/eli_gpu_pack.py`. If the 2 GB GitHub asset limit is exceeded, CUDA wheels may download on first launch instead.

## 2. Upload model / voice pack (separate)

Large assets exceed GitHub's 100 MB file limit for git blobs:

```bash
bash scripts/create_github_asset_archives.sh
# Attach models/MODEL_LICENSES.md to the release notes or asset bundle
python3 scripts/upload_github_asset_files.py --repo ShadowESC95/ELI_v2.0 --tag local-assets-v2.1
```

## 3. Publish GitHub Release

1. [New release](https://github.com/ShadowESC95/ELI_v2.0/releases/new) (or let CI create it on tag push)
2. Tag: `v2.4.6` (semver matches `pyproject.toml`)
3. Attach (CI produces these):
   - `ELI_v2-2.4.8-linux-portable.tar.gz`
   - `ELI_v2-2.4.8-x86_64.AppImage` (grandma-friendly)
   - `ELI-Setup-2.4.8.exe` / Windows portable zip (if built)
   - `.sha256` sidecars
   - Model pack assets (optional separate tag)

## 4. What users do

**Easiest Linux:** download `ELI_v2-*-x86_64.AppImage`, then:

```bash
chmod +x ELI_v2-*-x86_64.AppImage
./ELI_v2-*-x86_64.AppImage
```

First launch installs to `~/.local/share/ELI_v2`, auto-installs a GPU pack when hardware is detected, and opens the unified setup wizard (single dialog — no double launch).

**Easiest Windows:** download `ELI-Setup-2.4.8.exe`, run it, click through the installer.
Or extract the zip and double-click `ELI_Setup.bat`.

**Classic portable:**

```bash
tar -xzf ELI_v2-2.4.8-linux-portable.tar.gz
cd ELI_v2-2.4.8-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh    # guided (recommended)
# or: ./INSTALL_ELI.sh && ./RUN_ELI.sh
```

**Source / developer:**

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
./scripts/eli_setup.sh    # GUI-first; terminal fallback runs install.sh
```

**Tested path:** Linux x86_64 + NVIDIA. Intel iGPU / CPU-only paths validated via field tests; other OS builds are best-effort until reported.

## 5. Refresh docs after release

```bash
python3 tools/refresh_doc_metrics.py
```

Updates version strings, test counts, LOC, and capability totals across `**/*.md` and `eli/gui/panels/startup.py`.
