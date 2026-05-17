# ELI MKXI v2.0 PRO

ELI MKXI is a local-first AI assistant package with a PySide6 GUI, GGUF
inference support, persistent SQLite memory, local tools, speech/audio paths,
image/report tooling, and OS integration helpers.

## One-Click Setup

Fresh Linux/source checkout:

```bash
git clone https://github.com/ShadowESC95/ELI_MKXI_v2.0_PRO.git
cd ELI_MKXI_v2.0_PRO
bash scripts/eli_one_click_setup.sh
bash scripts/eli_one_click_run.sh
```

If the large local model/voice release assets have been uploaded to the private
GitHub release, restore them during setup:

```bash
gh auth login
bash scripts/eli_one_click_setup.sh --with-github-assets
```

CPU-only setup:

```bash
bash scripts/eli_one_click_setup.sh --cpu-only
```

Build an installable wheel/sdist:

```bash
bash scripts/package_eli_release.sh
python -m pip install "dist/eli_mkxi-*.whl[full]"
```

## GitHub Large Assets

The code repository intentionally excludes machine-specific runtime state,
virtual environments, and large model/voice binaries from normal Git because
GitHub rejects normal Git blobs over 100 MB and those files can be tens of GB.

Create a complete local ignored-asset manifest:

```bash
python scripts/github_asset_manifest.py --output dist/github_assets/asset_manifest.json
```

Create split GitHub Release upload archives for local model and voice payloads:

```bash
bash scripts/create_github_asset_archives.sh
```

Upload those split archives to the private GitHub release:

```bash
bash scripts/upload_github_assets.sh
```

Restore release assets after cloning:

```bash
bash scripts/restore_github_assets.sh
```

If the machine does not have enough free disk to create one archive set, use the
direct/chunked uploader. It stages one file at a time and is better for this
checkout's 70 GB+ model directory:

```bash
python scripts/upload_github_asset_files.py
python scripts/restore_github_asset_files.py
```

The repository is designed to be movable. Do not commit user-specific absolute
paths such as `/home/name/...`, `C:\Users\name\...`, or `/Users/name/...`.
Use project-relative paths, `ELI_PROJECT_ROOT`, or the path helpers in
`eli.core.paths` and `eli.core.portable_paths`.

## Project Layout

- `eli/core`: paths, settings, contracts, hardware profile
- `eli/kernel`: control loop, engine, state models
- `eli/cognition`: reasoning, grounding, synthesis
- `eli/memory`: episodic, semantic, knowledge graph, working memory
- `eli/planning`: goals, jobs, autonomy, scheduling
- `eli/execution`: router, executor, tool authority
- `eli/perception`: audio, screenshots, OS controller, TTS/STT
- `eli/runtime`: arbitration, verification, security policy
- `eli/integrations`: Ollama, GGUF, media backends, adapters
- `eli/plugins`: tool plugins
- `eli/gui`: GUI launcher and client code
- `config`: portable default settings
- `models`: optional local model payloads
- `packaging`: Windows, macOS, Linux packaging scripts
- `dist`: generated release artifacts
- `outputs`: generated instruction/export files

## Supported OS Names And Aliases

Runtime OS checks go through `eli.utils.platform_compat`.

- Windows: `windows`, `win`, `win32`, `win64`, `nt`, `cygwin`, `msys`, `mingw`
- macOS: `macos`, `mac`, `darwin`, `osx`, `mac os`, `mac os x`
- Linux: `linux`, `linux2`, `gnu/linux`, `ubuntu`, `debian`, `fedora`, `arch`
- Android/Termux: `android`, `termux`, `bionic`
- BSD: `bsd`, `freebsd`, `openbsd`, `netbsd`
- Generic Unix: `unix`, `posix`

Android support means Termux/headless integration. It does not mean full desktop
GUI, global desktop control, CUDA, PyAudio, or AppImage support on Android.

## Dynamic Path Rules

Use these APIs instead of hard-coded machine paths:

```python
from eli.core.paths import (
    project_root, data_dir, config_dir, cache_dir, models_dir,
    db_dir, user_db_path, agent_db_path, memory_db_path,
)

from eli.core.portable_paths import resolve_path_value, make_portable_path_value
```

Settings may store:

- `models/gguf/base/model.gguf`
- `${ELI_PROJECT_ROOT}/models/gguf/base/model.gguf`
- `%ELI_PROJECT_ROOT%\models\gguf\base\model.gguf`

At runtime those resolve to the current machine. When a path is inside the
project tree, settings storage converts it back to a project-relative path.

## Environment Files

- `.env.example`: minimal common overrides
- `.env.full.example`: full environment reference
- `.env.mkxi`: Bash helper for Linux/macOS source checkouts

Most users should leave `ELI_PROJECT_ROOT` unset. The app auto-detects its
project root from the installed package or source tree.

## Requirements

- `requirements.txt`: Linux x86_64 profile
- `requirements-windows.txt`: Windows profile
- `requirements-macos.txt`: macOS profile
- `requirements-android.txt`: Android/Termux headless profile
- `requirements-full.txt`: broad source-checkout profile

Recommended setup from a source checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-full.txt
python -m pip install -e .[full]
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-windows.txt
python -m pip install -e .[full]
```

macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-macos.txt
python -m pip install -e .[full]
```

Android/Termux:

```bash
pkg update
pkg install python termux-api
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-android.txt
python -m pip install -e .
```

## Running

Source checkout:

```bash
python -m eli
```

Linux installed package:

```bash
eli-mkxi
```

Windows portable ZIP:

1. Extract the ZIP.
2. Run `install.bat` or `install.ps1`.
3. Launch with `eli.bat` or the installed shortcut if present.

macOS tarball:

1. Extract `ELI_MKXI-<version>-macos-app.tar.gz`.
2. Open `ELI MKXI.app`.
3. Approve Gatekeeper/accessibility permissions if macOS asks.

## Packaging

Full release build from Linux:

```bash
bash build_packages.sh wheel wheelhouse deb appimage macos windows
```

Notes:

- The Linux AppImage target falls back to a portable tarball when
  `appimagetool` is not installed.
- A real Windows `.exe` or `.msi` must be built on Windows with
  `packaging/windows/build-windows.ps1`.
- A signed/notarized macOS `.dmg` must be built on macOS.

## Cross-Platform Limits

The code now has guards and aliases for Windows, macOS, Linux, BSD, and
Android/Termux, but no package can make every OS permission and native backend
instant:

- Windows may require SmartScreen approval, Visual C++ runtime, and audio/COM
  packages for endpoint volume control.
- macOS requires Screen Recording and Accessibility permissions for automation,
  and signing/notarization for a polished installer.
- Linux desktop control depends on the current desktop, Wayland/X11 tools,
  PulseAudio/PipeWire, and package availability.
- Android/Termux supports portable/headless operation and Termux API helpers,
  not full desktop GUI/control parity.
- GPU acceleration still depends on local drivers, CUDA/Metal/MPS support, and
  native wheels.

## Verification

Run focused checks:

```bash
python3 -m py_compile eli/utils/platform_compat.py eli/core/runtime_settings.py
pytest -q tests/test_core_paths.py tests/test_core_settings.py tests/test_integration.py
```

Run all tests:

```bash
pytest -q tests/
```
