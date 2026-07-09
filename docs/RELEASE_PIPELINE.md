# ELI v2 — Release Pipeline

Tag-triggered, three-OS release automation built on PyInstaller. Pushing a
version tag builds everything in parallel on GitHub Actions and attaches the
artifacts to the GitHub Release for that tag.

```
git tag v2.1.0
git push origin v2.1.0
```

produces on the Release page:

| Asset | Contents |
|---|---|
| `ELI-Setup-<v>.exe` | Windows installer (Inno Setup, per-user, no admin) |
| `ELI_v2-<v>-windows-x64.zip` | Windows portable — unzip, run `ELI\ELI.exe` |
| `ELI_v2-<v>-macos-arm64.dmg` | macOS Apple Silicon — drag ELI.app to Applications |
| `ELI_v2-<v>-x86_64.AppImage` | Linux — `chmod +x` and run (needs libfuse2, or `--appimage-extract-and-run`) |
| `SHA256SUMS.txt` | checksums for all of the above |

## Moving parts

| File | Role |
|---|---|
| `ELI.spec` | PyInstaller spec — one-dir build, all platforms. Data files come from `git ls-files` only (personal files/models can never leak). Version read from `pyproject.toml`. |
| `packaging/pyinstaller/eli_entry.py` | Frozen entry script → `eli.gui.app:main` (with `multiprocessing.freeze_support()`). |
| `packaging/pyinstaller/rthook_eli_frozen_paths.py` | Runtime hook: pins `ELI_PROJECT_ROOT`/data/config/models dirs. Writable installs (Windows/portable) keep state beside the app; read-only installs (macOS .app, AppImage) seed `~/.local/share/ELI_v2`-style per-user roots on first run. |
| `packaging/pyinstaller/gen_version_info.py` + `packaging/windows/version.rc.in` | Generates `build/version.rc` (Windows version resource) from `pyproject.toml`. |
| `packaging/windows/installer.iss` | Inno Setup installer for the frozen bundle (the older `ELI_Setup.iss` still serves the source-portable flow). |
| `packaging/macos/build-dmg.sh` | Ad-hoc signs `dist/ELI.app`, builds the `.dmg`. |
| `packaging/linux/build-appimage-pyinstaller.sh` | Wraps `dist/ELI` into an AppImage (pinned appimagetool 13). |
| `requirements-build.txt` | Pinned build tooling (PyInstaller etc.) for reproducible builds. |
| `.github/workflows/release.yml` | The pipeline: version guard → 3 parallel builds → Release upload. |

## What is (deliberately) not bundled

* **GGUF models, embeddings, diffusion weights** — up to 100 GB; the app
  downloads what the user picks on first run.
* **Piper voices** — flagged `license_review_required` in
  `packaging/runtime_asset_manifest.json`; downloaded at runtime.
* **PyQt** — GPL; the frozen bundle is PySide6-only (excluded in `ELI.spec`).
* **Optional extras without wheels for a platform** — each `OPTIONAL_EXTRAS`
  group in `release.yml` installs independently; a group with no wheels for
  that OS is skipped with a workflow warning and ELI degrades cleanly
  (same behaviour as a source install without that extra).

## Local builds

```
python -m venv .venv-build && source .venv-build/bin/activate   # any 3.10–3.11
pip install -r requirements-build.txt
pip install ".[gui,llm,server,docs,analysis,extras]"            # + optional extras you want bundled
pyinstaller --noconfirm --clean ELI.spec

# then, per platform:
iscc packaging\windows\installer.iss /DMyAppVersion=<version>   # Windows installer
bash packaging/macos/build-dmg.sh                               # macOS dmg
bash packaging/linux/build-appimage-pyinstaller.sh              # Linux AppImage
```

## Cutting a release

1. Bump `[project].version` in `pyproject.toml` (also
   `_DEFAULT_RELEASE_TAG` in `eli/kernel/self_upgrade.py` and the pin in
   `tests/test_pyproject_packaging.py`).
2. Commit, push, tag `v<version>`, push the tag. The `guard` job fails fast
   if the tag and `pyproject.toml` disagree.
3. Watch: `gh run watch` / Actions tab. The Release is created automatically
   with generated notes + artifacts.

`workflow_dispatch` runs the same builds without publishing a Release
(artifacts land on the workflow run) — use it to dry-run pipeline changes.

## Manual steps that remain (signing)

Unsigned builds work but trip OS trust prompts:

* **Windows**: SmartScreen shows "unknown publisher". To sign: buy an
  OV/EV code-signing certificate, then `signtool sign /fd SHA256 /a
  dist\ELI\ELI.exe` before ISCC and the produced `ELI-Setup-*.exe` after
  (store the cert as a GitHub secret and add a signing step to
  `release.yml`).
* **macOS**: the .app is ad-hoc signed only; Gatekeeper requires
  right-click → Open on first launch. Proper distribution needs an Apple
  Developer ID Application certificate + `codesign --options runtime`, then
  `xcrun notarytool submit … --wait` and `xcrun stapler staple` on the dmg.
* **Linux**: no signing required; verify via `SHA256SUMS.txt`.
