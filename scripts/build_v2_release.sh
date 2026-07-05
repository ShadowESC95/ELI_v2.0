#!/usr/bin/env bash
# Build the v2 download-and-run Linux portable package.
# Output: dist/app_packages/ELI_MKXI_v2.0_PRO-<version>-linux-portable.tar.gz
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export SKIP_TESTS="${SKIP_TESTS:-1}"
bash "$ROOT/scripts/package_desktop_app.sh" "$@"

echo ""
echo "[release] Portable v2 package ready under dist/app_packages/"
echo "[release] Publish to: https://github.com/ShadowESC95/ELI_v2.0/releases"
echo "[release] Users: extract → ./INSTALL_ELI.sh → ./RUN_ELI.sh [--with-github-assets]"
