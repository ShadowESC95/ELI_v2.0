# Installation — one-click setup (2026-06-07)

`install.sh` is the single entry point for a non-technical user. One command sets up
everything except the (deliberate, guided) model download.

## What `bash install.sh` does
1. Detects Python (3.10+) and OS; creates `.venv`; upgrades pip/setuptools/wheel.
2. Installs **PyTorch** (CUDA 12.1 / CPU / macOS-MPS per flags/OS).
3. Installs **llama-cpp-python** with GPU acceleration (CUDA wheel index / Metal /
   CPU) — then **verifies `llama_supports_gpu_offload()`** and, if it landed CPU-only,
   prints the exact CUDA-rebuild command (closes the silent-CPU-wheel trap).
4. Installs the ELI package (`[full]`) + all remaining dependencies from the
   **frozen `requirements.lock.txt`** (exact known-good versions; reproducible).
5. Seeds `config/settings.json` from the template (offline-by-default, wizard on) —
   never overwrites an existing config.
6. Creates `models/` and **initialises the data dirs + SQLite databases** (idempotent)
   so first launch is instant and the install is verifiably complete.
7. Verifies `import eli`, the GUI entry, and the `eli` console script.
8. Prints how to launch + how to download a model.

## Flags
- `--cpu-only` — no CUDA (CPU torch + CPU llama-cpp).
- `--latest` — use `requirements.txt` version ranges instead of the frozen lock.
- `--skip-torch` — leave an existing torch in place.

## Files
- `install.sh` (Linux/macOS), `install.bat` / `install.ps1` (Windows).
- `requirements.lock.txt` — frozen exact versions (excludes torch/llama-cpp, which
  install via their CUDA indices). Regenerate after dependency changes:
  `.venv/bin/pip freeze | grep -vE '^-e |file://|^(torch|torchvision|torchaudio|llama[-_]cpp[-_]python|triton|nvidia-)' > requirements.lock.txt`
- `requirements*.txt` — per-platform ranges. `pyproject.toml` — package metadata +
  `[project.scripts]` (`eli` → `eli.gui.app:main`).

## Launch
`./eli.sh` or `source .venv/bin/activate && eli`. First run shows the setup wizard.
Model: `python -m eli.core.model_download --auto` (or `--list`, or a named model).
ELI stays offline by default; the model download is a deliberate one-time action.
