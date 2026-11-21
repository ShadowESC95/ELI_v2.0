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
bash install.sh --yes --no-model    # venv + deps + DB schema; no chat model or embedder (voice weights are still fetched)
./scripts/eli_launch.sh
```

Flags: `--cpu-only` · `--install-cuda` · `--model=qwen2.5-7b` · `--no-model` (no chat model or embedder either; the voice weights are still fetched). Without `--no-model`, `--yes` also downloads a chat model sized to your VRAM.

A clone has no `ELI_Setup.sh` or `RUN_ELI.sh` (those are written into the portable package): `./scripts/eli_setup.sh` and `./scripts/eli_startup.sh` are the same scripts.

## Portable (no build)

Download **ELI v2.0 — Linux portable** from [GitHub Releases](https://github.com/ShadowESC95/ELI_v2.0/releases), then:

```bash
tar -xzf ELI_v2-*-linux-portable.tar.gz && cd ELI_v2-*-linux-portable
chmod +x ELI_Setup.sh install.sh && ./ELI_Setup.sh   # guided (recommended)
# If PySide6 error: bash install.sh --yes --auto-model && ./RUN_ELI.sh
```

**Full beginner guide:** [`first time Installation/INSTALLATION_GUIDE.md`](../first%20time%20Installation/INSTALLATION_GUIDE.md)

**AppImage (easier on Linux with glibc 2.39 or newer):** no `.venv` build — the GPU pack is offered on first launch; see Releases → `ELI_v2-*-x86_64.AppImage`.

## Regenerate capability docs (maintainers)

After changing executor actions or plugins:

```bash
.venv/bin/python -m eli.tools.registry.capability_updater
```

This refreshes `capability_manifest.json` and `blueprints/capabilities_and_actions.md`.

## Environment

`.env.example` (and `.env.full.example`, which lists every variable) shows the environment
variables ELI reads. Nothing loads a `.env` file by itself: export the ones you want in the
shell or launcher that starts ELI. Most installs set none.
