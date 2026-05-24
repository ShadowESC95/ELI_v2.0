#!/usr/bin/env bash
# sync_build.sh — sync source eli/ into the portable build package.
# Run after committing changes to keep the packaged binary current.
#
# Usage: bash scripts/sync_build.sh [--dry-run]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_TARGET="$PROJECT_ROOT/build/app-package/ELI_MKXI_v2.0_PRO-2.0.0-linux-portable"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

if [[ ! -d "$BUILD_TARGET/eli" ]]; then
    echo "[sync_build] Build target not found: $BUILD_TARGET/eli"
    exit 1
fi

SYNC_DIRS=(
    "eli"
    "api"
    "config"
)

for d in "${SYNC_DIRS[@]}"; do
    SRC="$PROJECT_ROOT/$d"
    DST="$BUILD_TARGET/$d"
    if [[ ! -d "$SRC" ]]; then continue; fi

    RSYNC_ARGS=(
        -av --delete
        --exclude="__pycache__"
        --exclude="*.pyc"
        --exclude="*.pyo"
        --exclude=".mypy_cache"
        --exclude="*.egg-info"
    )

    if [[ $DRY_RUN -eq 1 ]]; then
        RSYNC_ARGS+=(--dry-run)
        echo "[sync_build][dry-run] $SRC → $DST"
    else
        echo "[sync_build] $SRC → $DST"
    fi

    rsync "${RSYNC_ARGS[@]}" "$SRC/" "$DST/"
done

# Sync top-level project files
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
