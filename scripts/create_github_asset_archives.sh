#!/usr/bin/env bash
# Build GitHub Release asset archives for large local payloads.
#
# This does not push anything. It creates split tar.gz chunks under
# dist/github_assets/upload/. Each chunk is kept below the GitHub release
# per-asset practical limit so `gh release upload` can send them safely.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/dist/github_assets/upload"
CHUNK_SIZE="${ELI_ASSET_CHUNK_SIZE:-1900m}"
INCLUDE_RUNTIME=0
INCLUDE_VENV=0

usage() {
  cat <<'EOF'
Usage: scripts/create_github_asset_archives.sh [options]

Options:
  --include-runtime   Include artifacts/ runtime state. Private/local data risk.
  --include-venv      Include .venv/. Machine-specific and not recommended.
  --chunk-size SIZE   split size, default 1900m.
  -h, --help          Show help.

Default archive set:
  models/
  tts_piper/
  dist/github_assets/asset_manifest.json
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --include-runtime) INCLUDE_RUNTIME=1 ;;
    --include-venv) INCLUDE_VENV=1 ;;
    --chunk-size)
      shift
      CHUNK_SIZE="${1:?--chunk-size requires a value}"
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

mkdir -p "$OUT_DIR"

echo "[asset] Writing ignored-file manifest"
python3 "$ROOT/scripts/github_asset_manifest.py" --output "$ROOT/dist/github_assets/asset_manifest.json"

make_split_tar() {
  local name="$1"
  shift
  local paths=("$@")
  local prefix="$OUT_DIR/${name}.tar.gz.part-"

  local existing=0
  for p in "${paths[@]}"; do
    if [ -e "$ROOT/$p" ]; then
      existing=1
    fi
  done
  if [ "$existing" -eq 0 ]; then
    echo "[asset] Skip $name: none of ${paths[*]} exists"
    return 0
  fi

  echo "[asset] Creating split archive: $name"
  rm -f "$prefix"*
  (
    cd "$ROOT"
    tar -czf - "${paths[@]}" 2>/tmp/eli_asset_tar_${name}.log | split -b "$CHUNK_SIZE" - "$prefix"
  )
  ls -lh "$prefix"*
}

make_split_tar "eli-model-assets" "models"
make_split_tar "eli-voice-assets" "tts_piper"

if [ "$INCLUDE_RUNTIME" -eq 1 ]; then
  make_split_tar "eli-runtime-private-state" "artifacts"
fi

if [ "$INCLUDE_VENV" -eq 1 ]; then
  make_split_tar "eli-local-venv-linux" ".venv"
fi

cp "$ROOT/dist/github_assets/asset_manifest.json" "$OUT_DIR/asset_manifest.json"
echo "[asset] Archive directory: $OUT_DIR"
