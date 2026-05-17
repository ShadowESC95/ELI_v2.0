# ELI Environment and Launch Contract

This document defines the maintained source-checkout environment for ELI.

## GUI binding policy

ELI's maintained desktop GUI path is **PySide6**.  
Do not treat PyQt5 or PyQt6 as required project dependencies unless a separate experimental branch explicitly needs them.

## Standard source-checkout install

From the ELI project root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-full.txt
python -m pip install -e .[full]
```

## Maintained launch path

Use the project runner:

```bash
./scripts/run_eli_repo_venv.sh
```

The runner:
- resolves the project root;
- activates `<ELI_PROJECT_ROOT>/.venv`;
- exports `ELI_PROJECT_ROOT`;
- exports the repository root through `PYTHONPATH`;
- launches the maintained setup entry point:

```bash
python3 -m eli.gui.app --setup
```

Avoid launching deeply nested GUI files directly except for targeted developer diagnostics. Direct file execution can bypass package-relative import assumptions and create misleading `No module named eli...` failures.

## Dependency surfaces

The canonical top-level install surfaces are:
- `requirements.txt` — Linux x86_64 baseline profile
- `requirements-full.txt` — broad source-checkout profile
- `requirements-windows.txt` — Windows profile
- `requirements-macos.txt` — macOS profile
- `requirements-android.txt` — Android / Termux headless profile

Generated or audit-derived requirement inventories may exist under `requirements/generated/`, but they are not the first-class onboarding contract unless explicitly promoted into the maintained setup flow.

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
python3 -m pip check
python3 -m py_compile   eli/gui/app.py   eli/gui/labs_tab.py   eli/runtime/generated_script_guard.py
```

For normal execution:

```bash
./scripts/run_eli_repo_venv.sh
```
