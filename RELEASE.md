# ELI v2.0 — cutting a download-and-run release

> Maintainer walkthrough: **`blueprints/v2_release.pdf`** (local markdown also under `blueprints/`)

## 1. Build packages

**Grandma-friendly (Linux AppImage + portable):**

```bash
bash scripts/build_grandma_release.sh
# Output:
#   dist/app_packages/ELI_v2-<ver>-x86_64.AppImage      ← double-click Linux
#   dist/app_packages/ELI_v2-<ver>-linux-portable.tar.gz
```

**Portable only:**

```bash
bash scripts/build_v2_release.sh
# Output: dist/app_packages/ELI_v2-2.0.10-linux-portable.tar.gz
```

**Windows Setup.exe** (run on a Windows PC with [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
bash build_packages.sh windows-lean
powershell -ExecutionPolicy Bypass -File packaging/windows/build-windows.ps1 -Version 2.0.10
# Output: dist/ELI_v2-2.0.10-Setup.exe
```

Optional full bundle (local models — very large):

```bash
bash scripts/build_v2_release.sh --with-assets
```

Other platforms (maintainer hosts):

```bash
bash build_packages.sh wheel windows macos appimage
```

## 2. Upload model / voice pack (separate)

Large assets exceed GitHub's 100 MB file limit for git blobs:

```bash
bash scripts/create_github_asset_archives.sh
# Attach models/MODEL_LICENSES.md to the release notes or asset bundle
python3 scripts/upload_github_asset_files.py --repo ShadowESC95/ELI_v2.0 --tag local-assets-v2.1
```

## 3. Publish GitHub Release

1. [New release](https://github.com/ShadowESC95/ELI_v2.0/releases/new)
2. Tag: `v2.0.10` (semver matches `pyproject.toml`)
3. Attach:
   - `ELI_v2-2.0.10-linux-portable.tar.gz`
   - `ELI_v2-2.0.10-x86_64.AppImage` (grandma-friendly)
   - `ELI_v2-2.0.10-Setup.exe` (Windows, if built)
   - `.sha256` sidecars
   - Model pack assets (optional separate tag)

## 4. What users do

**Easiest Linux:** download `ELI_v2-*-x86_64.AppImage`, then:

```bash
chmod +x ELI_v2-*-x86_64.AppImage
./ELI_v2-*-x86_64.AppImage
```

First launch installs to `~/.local/share/ELI_v2` and opens the setup wizard.

**Easiest Windows:** download `ELI_v2-*-Setup.exe`, run it, click through the installer.
Or extract the zip and double-click `ELI_Setup.bat`.

**Classic portable:**

```bash
tar -xzf ELI_v2-2.0.10-linux-portable.tar.gz
cd ELI_v2-2.0.10-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh    # guided (recommended)
# or: ./INSTALL_ELI.sh && ./RUN_ELI.sh
```

**Tested path:** Linux x86_64 + NVIDIA. Other OS builds are best-effort until reported.
