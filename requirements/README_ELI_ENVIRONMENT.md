# ELI Environment and Launch Contract

This document defines the maintained source-checkout environment for ELI.

## GUI binding policy

ELI's maintained desktop GUI path is **PySide6**.  
Do not treat PyQt5 or PyQt6 as required project dependencies unless a separate experimental branch explicitly needs them.

## Standard source-checkout install

The maintained installer is `bash install.sh` (`install.bat` / `install.ps1` on Windows): it picks
the Python (`scripts/eli_env.py pick`), builds the inference engine for the machine's GPU, installs
from the frozen lock and checks the result. By hand, from the ELI project root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip wheel 'setuptools>=68,<82'   # the cap install.sh applies for PyTorch
python -m pip install -r requirements-full.txt
python -m pip install -e .[full]
```

That gives the CPU build of llama-cpp-python (0.3.35 or newer, compiled from PyPI's source) and
PyPI's default PyTorch; for a GPU build use `install.sh`.

## Maintained launch path

Use the project runner:

```bash
./scripts/run_eli_repo_venv.sh
```

The runner:
- resolves the project root;
- isolates the environment (`scripts/eli_isolate_env.sh`): drops inherited ELI folder variables
  (a models folder the user set, `ELI_MODELS_DIR`, is kept) and other checkouts' `.venv` from
  `PATH`, and checks the `.venv` can still run ELI;
- activates `<ELI_PROJECT_ROOT>/.venv`;
- exports `ELI_PROJECT_ROOT`;
- exports the repository root through `PYTHONPATH`;
- sources an optional `.env.eli_v2_0`, then unsets the model variables (`ELI_GGUF_MODEL_PATH`,
  `ELI_MODEL_PATH`, `ELI_MODEL`, `GGUF_MODEL_PATH`) so a model saved there — older versions of the
  legacy `bin/elix` launcher wrote it; it now saves its choice in the app's settings — cannot
  bypass the picker;
- launches the maintained setup entry point:

```bash
python3 -m eli.gui.app --setup
```

The other launchers (`./scripts/eli_launch.sh [gui|serve|both]`, `./eli.sh`, the `eli-v2`
command) start the same app the same way, without forcing the model picker.

Avoid launching deeply nested GUI files directly except for targeted developer diagnostics. Direct file execution can bypass package-relative import assumptions and create misleading `No module named eli...` failures.

## Dependency surfaces

The canonical top-level install surfaces are:
- `requirements.lock.txt` — frozen exact versions; the default for `install.sh` and `install.ps1`
- `requirements.txt` — Linux x86_64 baseline profile (`install.sh --latest`)
- `requirements-full.txt` — broad source-checkout profile (the ranges `install.sh` falls back to)
- `requirements-windows.txt` — Windows profile (`install.ps1 -Latest` and its fallback)
- `requirements-macos.txt` — macOS profile (what `install.sh` installs on macOS)
- `requirements-android.txt` — Android / Termux headless profile (`scripts/install_android.sh`)
- `requirements-portable-bootstrap.txt` — the PySide6 wheels the portable packages carry offline

`requirements-build.txt` (release tooling) and `requirements-test.txt` (test suite) are not
runtime profiles. Generated or audit-derived requirement inventories may exist under `requirements/generated/`, but they are not the first-class onboarding contract unless explicitly promoted into the maintained setup flow.

## Runtime portability contract

Maintained source should prefer:
- project-relative paths;
- `ELI_PROJECT_ROOT`;
- runtime path helper functions;
- OS-sensitive fallbacks guarded by platform checks.

Do not hard-code a developer home directory, desktop checkout path, or one-machine artifact layout into maintained source.

## Verification commands

After environment setup:

```bash
python3 scripts/eli_env.py verify .     # ELI and everything it cannot run without, asked of .venv from outside the tree
python3 -m pip check
python3 -m py_compile   eli/gui/app.py   eli/gui/labs_tab.py   eli/runtime/generated_script_guard.py
```

For normal execution:

```bash
./scripts/run_eli_repo_venv.sh
```
