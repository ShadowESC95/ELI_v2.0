#!/usr/bin/env bash
# Restore large local assets from GitHub Release archive chunks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_MKXI_v2.0_PRO}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.0}"
DOWNLOAD_DIR="$ROOT/dist/github_assets/download"
KEEP_ARCHIVES=0

usage() {
  cat <<EOF
Usage: scripts/restore_github_assets.sh [options]

Options:
  --repo OWNER/REPO       Default: $REPO
  --tag TAG              Default: $TAG
  --download-dir PATH    Default: $DOWNLOAD_DIR
  --from-dir PATH        Use already downloaded archive chunks instead of gh download.
  --keep-archives        Keep downloaded archive chunks after restore.
  -h, --help             Show help.

Private repos require:
  gh auth login
EOF
}

FROM_DIR=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      shift
      REPO="${1:?--repo requires OWNER/REPO}"
      ;;
    --tag)
      shift
      TAG="${1:?--tag requires a value}"
      ;;
    --download-dir)
      shift
      DOWNLOAD_DIR="$(mkdir -p "$1" && cd "$1" && pwd)"
      ;;
    --from-dir)
      shift
      FROM_DIR="$(cd "$1" && pwd)"
      ;;
    --keep-archives)
      KEEP_ARCHIVES=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ -n "$FROM_DIR" ]; then
  DOWNLOAD_DIR="$FROM_DIR"
else
  mkdir -p "$DOWNLOAD_DIR"
  if ! command -v gh >/dev/null 2>&1; then
    echo "gh CLI is required for private GitHub release downloads." >&2
    exit 1
  fi
  echo "[asset] Downloading release assets from $REPO tag $TAG"
  gh release download "$TAG" --repo "$REPO" --dir "$DOWNLOAD_DIR" --clobber
fi

restore_prefix() {
  local name="$1"
  local first
  first="$(find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name "${name}.tar.gz.part-*" | sort | head -1 || true)"
  if [ -z "$first" ]; then
    echo "[asset] No chunks for $name"
    return 0
  fi
  echo "[asset] Restoring $name"
  find "$DOWNLOAD_DIR" -maxdepth 1 -type f -name "${name}.tar.gz.part-*" | sort | xargs cat | tar -xzf - -C "$ROOT"
}

restore_prefix "eli-model-assets"
restore_prefix "eli-voice-assets"
restore_prefix "eli-runtime-private-state"
restore_prefix "eli-local-venv-linux"

if [ "$KEEP_ARCHIVES" -eq 0 ] && [ -z "$FROM_DIR" ]; then
  echo "[asset] Keeping download directory for inspection: $DOWNLOAD_DIR"
fi

echo "[asset] Restore complete"
