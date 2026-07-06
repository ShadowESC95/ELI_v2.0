# First run after clone

Fresh checkouts ship with `capability_manifest.json`, blueprint docs, and `.env.example` in git.
You still need a model and (for full voice/memory) optional asset downloads.

## Source install (Linux / macOS)

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
bash install.sh --yes --no-model    # venv + deps + DB schema; skip large model fetch
./scripts/eli_launch.sh             # desktop GUI
```

Flags: `--cpu-only` · `--install-cuda` · `--model=qwen2.5-7b` · `--no-model` (no embedder/voice download either).

## Portable (no build)

Download **ELI v2.0 — Linux portable** from [GitHub Releases](https://github.com/ShadowESC95/ELI_v2.0/releases), then:

```bash
tar -xzf ELI_v2-*-linux-portable.tar.gz && cd ELI_v2-*-linux-portable
./INSTALL_ELI.sh
./RUN_ELI.sh --with-github-assets   # optional starter models + voices
./RUN_ELI.sh
```

## Regenerate capability docs (maintainers)

After changing executor actions or plugins:

```bash
.venv/bin/python -m eli.tools.registry.capability_updater
```

This refreshes `capability_manifest.json` and `blueprints/capabilities_and_actions.md`.

## Environment

Copy `.env.example` only if you need overrides — most installs leave it unset.
