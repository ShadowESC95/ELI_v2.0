#!/usr/bin/env bash
# sync_build.sh — sync source into the portable v2 package staging tree.
# Usage: bash scripts/sync_build.sh [--dry-run]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cd "$PROJECT_ROOT" && python3 - <<'PY'
import tomllib
with open("pyproject.toml", "rb") as f:
    print(tomllib.load(f)["project"]["version"])
PY
)"
APP_NAME="ELI_MKXI_v2.0_PRO"
BUILD_TARGET="$PROJECT_ROOT/build/app-package/${APP_NAME}-${VERSION}-linux-portable"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

if [[ ! -d "$BUILD_TARGET/eli" ]]; then
    echo "[sync_build] Build target not found: $BUILD_TARGET/eli"
    echo "[sync_build] Run: bash scripts/build_v2_release.sh"
    exit 1
fi

SYNC_DIRS=( "eli" "api" "config" )

for d in "${SYNC_DIRS[@]}"; do
    SRC="$PROJECT_ROOT/$d"
    DST="$BUILD_TARGET/$d"
    if [[ ! -d "$SRC" ]]; then continue; fi
    RSYNC_ARGS=( -av --delete --exclude="__pycache__" --exclude="*.pyc" --exclude="*.pyo" --exclude=".mypy_cache" --exclude="*.egg-info" )
    if [[ $DRY_RUN -eq 1 ]]; then
        RSYNC_ARGS+=(--dry-run)
        echo "[sync_build][dry-run] $SRC → $DST"
    else
        echo "[sync_build] $SRC → $DST"
    fi
    rsync "${RSYNC_ARGS[@]}" "$SRC/" "$DST/"
done

for f in pyproject.toml requirements.txt; do
    if [[ -f "$PROJECT_ROOT/$f" ]]; then
        if [[ $DRY_RUN -eq 1 ]]; then
            echo "[sync_build][dry-run] $f"
        else
            cp "$PROJECT_ROOT/$f" "$BUILD_TARGET/$f"
        fi
    fi
done

echo "[sync_build] Done."
