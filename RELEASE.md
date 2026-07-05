# ELI v2.0 — cutting a download-and-run release

> Full walkthrough: **[blueprints/v2_release.md](blueprints/v2_release.md)**

## 1. Build portable Linux package

```bash
bash scripts/build_v2_release.sh
# Output: dist/app_packages/ELI_v2.0-2.0.1-linux-portable.tar.gz
```

Optional full bundle (local models — very large):

```bash
bash scripts/build_v2_release.sh --with-assets
```

Other platforms (maintainer hosts):

```bash
bash build_packages.sh wheel windows macos
```

## 2. Upload model / voice pack (separate)

Large assets exceed GitHub's 100 MB file limit for git blobs:

```bash
bash scripts/create_github_asset_archives.sh   # if present
# Attach models/MODEL_LICENSES.md to the release notes or asset bundle
python3 scripts/upload_github_asset_files.py --repo ShadowESC95/ELI_v2.0 --tag v2.0.0-assets
```

## 3. Publish GitHub Release

1. [New release](https://github.com/ShadowESC95/ELI_v2.0/releases/new)
2. Tag: `v2.0.1` (or `v2.0.1-portable`)
3. Attach:
   - `ELI_v2.0-2.0.1-linux-portable.tar.gz`
   - `.sha256` sidecar
   - Model pack assets (optional separate tag)

## 4. What users do

```bash
tar -xzf ELI_v2.0-2.0.0-linux-portable.tar.gz
cd ELI_v2.0-2.0.0-linux-portable
./INSTALL_ELI.sh
./RUN_ELI.sh --with-github-assets
./RUN_ELI.sh
```

**Tested path:** Linux x86_64 + NVIDIA. Other OS builds are best-effort until reported.
