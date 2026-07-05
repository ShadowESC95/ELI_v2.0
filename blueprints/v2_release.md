# Blueprint — ELI v2.0 download-and-run release

How to build, publish, and use the **portable Linux package** — the v2 finish line
for people who want ELI working without cloning source.

Companion: root [`RELEASE.md`](../RELEASE.md) (maintainer checklist) ·
[`README.md`](../README.md#download--run-linux-portable) (user-facing).

---

## What ships

| Artifact | Size (typical) | Contains |
|---|---|---|
| `ELI_v2-2.0.0-linux-portable.tar.gz` | ~8 MB (no models) | Source tree, wheel, `INSTALL_ELI.sh`, `RUN_ELI.sh`, install scripts |
| Model/voice pack (`local-assets-v2.1`) | ~6+ GB total | nomic embedder, starter GGUFs, cleared Piper voices |

**Not in the tarball:** `.venv`, `artifacts/`, `models/*.gguf` — created at install time.

**Auto-fetched on `INSTALL_ELI.sh` (network once):**
- Python deps into `.venv`
- Full SQLite architecture (blank slate) via `eli.core.init_data`
- `models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf` (~80 MiB)
- Piper `en_US-amy-medium` + whisper STT via `eli.runtime.voice_assets`

**From asset pack (`--with-github-assets`):** starter chat models + voices on the release tag.
Excluded from auto-restore: `en_US-ryan-*`, `en_US-lessac-*`, `en_GB-cori-high`.

**Tested path:** Linux x86_64 + NVIDIA GPU. Windows/macOS/AMD installers exist; feedback welcome.

---

## Maintainer: build (on your dev machine)

```bash
cd /path/to/ELI_v2.0
# Uses project .venv for python-build if system pip is PEP-668 locked
bash scripts/build_v2_release.sh
```

Outputs:

```
dist/app_packages/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz
dist/app_packages/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz.sha256
```

Optional monolithic build (includes local `models/` — huge):

```bash
bash scripts/build_v2_release.sh --with-assets
```

Sync source into an existing staging tree after edits:

```bash
bash scripts/sync_build.sh
```

---

## Maintainer: publish GitHub Release

**Live release:** [v2.0.0](https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.0.0)  
**Model pack:** [local-assets-v2.1](https://github.com/ShadowESC95/ELI_v2.0/releases/tag/local-assets-v2.1)

### First-time publish (new tag)

```bash
cd /path/to/ELI_v2.0
PKG=dist/app_packages/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz
SHA=dist/app_packages/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz.sha256

gh release create v2.0.0 \
  --repo ShadowESC95/ELI_v2.0 \
  --title "ELI v2.0 — Linux portable (download & run)" \
  --notes "$(cat <<'EOF'
## Download & run (Linux)

1. Download **ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz** below.
2. Verify (optional): \`sha256sum -c ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz.sha256\`
3. Extract and install:

\`\`\`bash
tar -xzf ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz
cd ELI_MKXI_v2.0_PRO-2.0.0-linux-portable
./INSTALL_ELI.sh
./RUN_ELI.sh --with-github-assets   # optional model pack (separate assets tag)
./RUN_ELI.sh
\`\`\`

**Best tested:** Linux x86_64 + NVIDIA. Rough edges elsewhere — [open an issue](https://github.com/ShadowESC95/ELI_v2.0/issues).

**v3** is in active development: https://github.com/ShadowESC95/Eli_v3
EOF
)" \
  "$PKG" "$SHA"
```

### Refresh an existing release (rebuild + replace assets)

When the tag already exists (e.g. after README/install script fixes), upload new
binaries with `--clobber` and refresh the notes:

```bash
PKG=dist/app_packages/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz
SHA=dist/app_packages/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz.sha256

gh release upload v2.0.0 --repo ShadowESC95/ELI_v2.0 --clobber "$PKG" "$SHA"
gh release edit v2.0.0 --repo ShadowESC95/ELI_v2.0 --title "..." --notes-file RELEASE_NOTES.md
```

Checksum after upload (2026-07-05 rebuild):

```
034cd6a256db4dbec7f7cacccf2da938afbb7fc8d04ce51508a54199af763d50
```

### Model / voice pack (separate tag)

Large files cannot live in git. Upload to a dedicated release tag:

```bash
export ELI_ASSET_RELEASE_TAG=v2.0.0-assets
python3 scripts/upload_github_asset_files.py --repo ShadowESC95/ELI_v2.0 --tag "$ELI_ASSET_RELEASE_TAG"
```

Users restore with:

```bash
./RUN_ELI.sh --with-github-assets --tag v2.0.0-assets
```

---

## End user: download & run

From **[GitHub Releases](https://github.com/ShadowESC95/ELI_v2.0/releases)** (not “Code → Download ZIP” — that’s source without the installer wiring).

```bash
tar -xzf ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz
cd ELI_MKXI_v2.0_PRO-2.0.0-linux-portable
./INSTALL_ELI.sh
./RUN_ELI.sh --with-github-assets   # once, if model pack published
./RUN_ELI.sh
```

Inside the tarball, `README_INSTALL.txt` repeats these steps.

**Data folders** (`artifacts/db/`, etc.) are created on first install/run — see [`artifacts/README.md`](../artifacts/README.md).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python3 -m build` fails (PEP 668) | Use project `.venv`: `.venv/bin/pip install build` then re-run `build_v2_release.sh` |
| No GGUF after install | Run `--with-github-assets` or `python -m eli.core.model_download --auto` |
| `eli` command not found | `hash -r` after `INSTALL_ELI.sh`; check `~/.local/bin` on PATH |
| GPU not used | NVIDIA driver + CUDA path; see README “Tested on & known limitations” |

---

*Last updated: 2026-07-05 — portable build verified on maintainer Linux host.*
