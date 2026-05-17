#!/usr/bin/env bash
# Build a portable desktop application package for ELI MKXI v2.0 PRO.
# Default package excludes heavyweight model/voice assets; restore them from GitHub release after install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cd "$ROOT" && python3 - <<'PY'
import tomllib
with open('pyproject.toml','rb') as f:
    print(tomllib.load(f)['project']['version'])
PY
)"
APP_NAME="ELI_MKXI_v2.0_PRO"
OUT_DIR="$ROOT/dist/app_packages"
WORK_DIR="$ROOT/build/app-package"
WITH_ASSETS=0
SKIP_WHEEL=0
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_MKXI_v2.0_PRO}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.0}"

usage() {
  cat <<EOF_USAGE
Usage: scripts/package_desktop_app.sh [options]

Options:
  --with-assets           Include local models/ and tts_piper/ in the tarball. Huge; off by default.
  --skip-wheel            Do not rebuild the Python wheel before packaging.
  --out-dir PATH          Output directory. Default: $OUT_DIR
  --repo OWNER/REPO       GitHub asset repo recorded in install notes. Default: $REPO
  --tag TAG               GitHub asset release tag recorded in install notes. Default: $TAG
  -h, --help              Show help.

Output:
  dist/app_packages/ELI_MKXI_v2.0_PRO-${VERSION}-linux-portable.tar.gz
EOF_USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-assets) WITH_ASSETS=1 ;;
    --skip-wheel) SKIP_WHEEL=1 ;;
    --out-dir)
      shift
      OUT_DIR="$(mkdir -p "$1" && cd "$1" && pwd)"
      ;;
    --repo)
      shift
      REPO="${1:?--repo requires OWNER/REPO}"
      ;;
    --tag)
      shift
      TAG="${1:?--tag requires a value}"
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

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "tar is required" >&2; exit 1; }

mkdir -p "$OUT_DIR" "$WORK_DIR"
STAGING="$WORK_DIR/${APP_NAME}-${VERSION}-linux-portable"
rm -rf "$STAGING"
mkdir -p "$STAGING"

if [ "$SKIP_WHEEL" -eq 0 ]; then
  echo "[package] building wheel"
  (cd "$ROOT" && python3 -m build --wheel --no-isolation)
fi

echo "[package] exporting tracked source"
(
  cd "$ROOT"
  if [ "$WITH_ASSETS" -eq 1 ]; then
    git ls-files -z
  else
    git ls-files -z -- ':!:models/**' ':!:tts_piper/**'
  fi | tar --null -T - -cf -
) | tar -xf - -C "$STAGING"

mkdir -p "$STAGING/dist" "$STAGING/packaging/desktop" "$STAGING/models" "$STAGING/tts_piper"
if ls "$ROOT"/dist/eli_mkxi-*.whl >/dev/null 2>&1; then
  cp "$ROOT"/dist/eli_mkxi-*.whl "$STAGING/dist/"
fi

if [ "$WITH_ASSETS" -eq 1 ]; then
  echo "[package] including local model/voice assets; this can be very large"
  [ -d "$ROOT/models" ] && cp -a "$ROOT/models/." "$STAGING/models/"
  [ -d "$ROOT/tts_piper" ] && cp -a "$ROOT/tts_piper/." "$STAGING/tts_piper/"
fi

cat > "$STAGING/RUN_ELI.sh" <<'RUN_EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$APP_ROOT/scripts/eli_startup.sh" "$@"
RUN_EOF
chmod +x "$STAGING/RUN_ELI.sh"

cat > "$STAGING/INSTALL_ELI.sh" <<INSTALL_EOF
#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
bash "\$APP_ROOT/scripts/eli_one_click_setup.sh" "\$@"
INSTALL_EOF
chmod +x "$STAGING/INSTALL_ELI.sh"

cat > "$STAGING/packaging/desktop/ELI_MKXI_v2_PRO.desktop.template" <<'DESKTOP_EOF'
[Desktop Entry]
Name=ELI MKXI v2.0 PRO
Comment=Local AI cognitive runtime and assistant
Exec=__APP_ROOT__/RUN_ELI.sh
Icon=__APP_ROOT__/blueprints/eli_logo2.png
Type=Application
Categories=Utility;Science;ArtificialIntelligence;
StartupNotify=true
Terminal=false
DESKTOP_EOF

cat > "$STAGING/packaging/desktop/install_desktop_launcher.sh" <<'DESKTOP_INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESKTOP_DIR"
sed "s#__APP_ROOT__#$APP_ROOT#g" \
  "$APP_ROOT/packaging/desktop/ELI_MKXI_v2_PRO.desktop.template" \
  > "$DESKTOP_DIR/eli-mkxi-v2-pro.desktop"
chmod +x "$DESKTOP_DIR/eli-mkxi-v2-pro.desktop"
echo "$DESKTOP_DIR/eli-mkxi-v2-pro.desktop"
DESKTOP_INSTALL_EOF
chmod +x "$STAGING/packaging/desktop/install_desktop_launcher.sh"

cat > "$STAGING/README_INSTALL.txt" <<README_EOF
ELI MKXI v2.0 PRO portable desktop package

Run:
  ./INSTALL_ELI.sh
  eli
  ./RUN_ELI.sh

Restore model/voice assets from GitHub release:
  gh auth login
  ./RUN_ELI.sh --with-github-assets

Manual restore:
  .venv/bin/python scripts/restore_github_asset_files.py --repo $REPO --tag $TAG

Desktop launcher:
  ./packaging/desktop/install_desktop_launcher.sh

Terminal command:
  ./INSTALL_ELI.sh installs ~/.local/bin/eli by default.
  If your shell has cached an older eli command, run: hash -r

This package intentionally excludes .venv, runtime/private artifacts, caches, and heavy model/voice assets unless built with --with-assets.
README_EOF

PACKAGE="$OUT_DIR/${APP_NAME}-${VERSION}-linux-portable.tar.gz"
rm -f "$PACKAGE" "$PACKAGE.sha256"
echo "[package] creating $PACKAGE"
(
  cd "$WORK_DIR"
  tar -czf "$PACKAGE" "$(basename "$STAGING")"
)
(cd "$OUT_DIR" && sha256sum "$(basename "$PACKAGE")" > "$(basename "$PACKAGE").sha256")

echo "[package] complete"
echo "  $PACKAGE"
echo "  $PACKAGE.sha256"
