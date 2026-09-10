# First run after clone

Fresh checkouts ship with `capability_manifest.json`, blueprint docs, and `.env.example` in git.
You still need a model and (for full voice/memory) optional asset downloads.

## Source install (Linux / macOS)

**Recommended (GUI-first):**

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
./scripts/eli_setup.sh              # unified wizard; terminal fallback when headless
./scripts/eli_launch.sh             # desktop GUI
```

**Developer / headless:**

```bash
bash install.sh --yes --no-model    # venv + deps + DB schema; skip large model fetch
./scripts/eli_launch.sh
```

Flags: `--cpu-only` · `--install-cuda` · `--model=qwen2.5-7b` · `--no-model` (no embedder/voice download either).

## Portable (no build)

Download **ELI v2.0 — Linux portable** from [GitHub Releases](https://github.com/ShadowESC95/ELI_v2.0/releases), then:

```bash
tar -xzf ELI_v2-*-linux-portable.tar.gz && cd ELI_v2-*-linux-portable
chmod +x ELI_Setup.sh install.sh && ./ELI_Setup.sh   # guided (recommended)
# If PySide6 error: bash install.sh --yes --auto-model && ./RUN_ELI.sh
```

**Full beginner guide:** [`first time Installation/INSTALLATION_GUIDE.md`](../first%20time%20Installation/INSTALLATION_GUIDE.md)

**AppImage (easier on Linux):** no `.venv` build — GPU pack downloads on first launch; see Releases → `ELI_v2-*-x86_64.AppImage`.

## Regenerate capability docs (maintainers)

After changing executor actions or plugins:

```bash
.venv/bin/python -m eli.tools.registry.capability_updater
```

This refreshes `capability_manifest.json` and `blueprints/capabilities_and_actions.md`.

## Environment

Copy `.env.example` only if you need overrides — most installs leave it unset.
