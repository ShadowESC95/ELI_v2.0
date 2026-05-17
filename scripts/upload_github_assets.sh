#!/usr/bin/env bash
# Upload large local asset archive chunks to a GitHub Release.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_MKXI_v2.0_PRO}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.0}"
TITLE="${ELI_ASSET_RELEASE_TITLE:-ELI MKXI v2.0 PRO local assets}"
ASSET_DIR="$ROOT/dist/github_assets/upload"

usage() {
  cat <<EOF
Usage: scripts/upload_github_assets.sh [options]

Options:
  --repo OWNER/REPO      Default: $REPO
  --tag TAG             Default: $TAG
  --asset-dir PATH      Default: $ASSET_DIR
  -h, --help            Show help.

Requires:
  gh auth login
  archives built by scripts/create_github_asset_archives.sh
EOF
}

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
    --asset-dir)
      shift
      ASSET_DIR="$(cd "$1" && pwd)"
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

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required. Install from https://cli.github.com/ and run gh auth login." >&2
  exit 1
fi

if [ ! -d "$ASSET_DIR" ]; then
  echo "Asset directory not found: $ASSET_DIR" >&2
  echo "Run scripts/create_github_asset_archives.sh first." >&2
  exit 1
fi

mapfile -t ASSETS < <(find "$ASSET_DIR" -maxdepth 1 -type f | sort)
if [ "${#ASSETS[@]}" -eq 0 ]; then
  echo "No assets found in $ASSET_DIR" >&2
  exit 1
fi

if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$TAG" --repo "$REPO" --title "$TITLE" --notes \
"Large local ELI assets split into GitHub release files.

Restore with:
  scripts/restore_github_assets.sh --repo $REPO --tag $TAG

These assets are intentionally not committed into Git because GitHub normal Git rejects files over 100 MB."
fi

echo "[asset] Uploading ${#ASSETS[@]} assets to $REPO release $TAG"
gh release upload "$TAG" "${ASSETS[@]}" --repo "$REPO" --clobber
echo "[asset] Upload complete"
