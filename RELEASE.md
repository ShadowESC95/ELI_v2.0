# ELI v2.0 — cutting a download-and-run release

> Maintainer walkthrough: **`docs/RELEASE_PIPELINE.md`**  
> **New users:** **`first time Installation/INSTALLATION_GUIDE.md`**

Current semver: **`pyproject.toml`** → **2.5.40** (tag **`v2.5.40`**). The tag must equal
`[project].version`; the release workflow's version guard fails the run otherwise.

## 1. Build packages

**CI / tag push (recommended):** push tag `v2.5.40` — `.github/workflows/release.yml` builds the
Windows, macOS and Linux bundles and the source packages in parallel, launch-tests each frozen
bundle, runs the whole test suite on Linux against the release's own libraries, and publishes the
GitHub Release only when all of them pass. `workflow_dispatch` is a dry run: it builds the
artifacts and skips the Release.

**Local Linux portable + AppImage:**

```bash
SKIP_TESTS=1 bash scripts/build_grandma_release.sh
```

This builds the portable tarball (`scripts/build_v2_release.sh`) and an AppImage wrapped around it
(`packaging/linux/build-appimage.sh`, which installs to `~/.local/share/ELI_v2` on first run). The
AppImage CI publishes is the PyInstaller build instead (`packaging/linux/build-appimage-pyinstaller.sh`).

## 2. What each asset is for

| Asset | Use |
|---|---|
| `ELI-Setup-<v>.exe` | Windows one-click (frozen, Inno Setup). Desktop shortcut: ELI (the server stays in the Start Menu); GUI singleton. |
| `ELI_v2-<v>-windows-x64.zip` | Unzip → `ELI\ELI.exe` |
| `ELI_v2-<v>-x86_64.AppImage` | Linux double-click (frozen; needs glibc 2.39 or newer) |
| `ELI_v2-<v>-linux-portable.tar.gz` | Source + voices: `./ELI_Setup.sh` → hardware-aware wizard |
| `ELI_v2-<v>-macos-arm64.dmg` | macOS Apple Silicon (ad-hoc signed) |
| `ELI_v2-<v>-windows-arm64-portable.zip` | Windows on ARM, lean and experimental |
| wheel, sdist, `.deb`, Windows portable zips, wheelhouse | Source installs and offline installs |
| `SHA256SUMS.txt`, `RELEASE_NOTES.md` | Checksums and notes for the release |

**Source installs:** `./ELI_Setup.sh` (portable tarball) / `ELI_Setup.bat` (Windows portable zip)
→ GUI wizard → `eli.setup.hardware_policy` → one `install.sh` / `install.ps1` run. Core stages
(env, DB, nomic, voice, chat GGUF) hard-fail until present. OS tools (mpv, tesseract, …)
best-effort. The frozen builds (`.exe`, `.zip`, `.dmg`, AppImage) need none of this: they offer
the GPU pack and a model on first start.

## 3. Tag and publish

```bash
git tag v2.5.40 && git push origin v2.5.40
```
