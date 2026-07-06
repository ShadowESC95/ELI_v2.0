#!/usr/bin/env bash
# Build a portable desktop application package for ELI Pro.
# Default package excludes heavyweight model/voice assets; restore them from GitHub release after install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$ROOT/.venv/bin/python3" ]; then
  PYTHON="${PYTHON:-$ROOT/.venv/bin/python3}"
else
  PYTHON="${PYTHON:-python3}"
fi
VERSION="$(cd "$ROOT" && "$PYTHON" - <<'PY'
import sys
sys.path.insert(0, ".")
from eli.core.toml_util import load_toml
print(load_toml("pyproject.toml")["project"]["version"])
PY
)"
APP_NAME="ELI_v2"
OUT_DIR="$ROOT/dist/app_packages"
WORK_DIR="$ROOT/build/app-package"
WITH_ASSETS=0
SKIP_WHEEL=0
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_v2.0}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.1}"

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
  dist/app_packages/ELI_v2-${VERSION}-linux-portable.tar.gz
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
  echo "[package] building wheel ($PYTHON)"
  (cd "$ROOT" && "$PYTHON" -m build --wheel --no-isolation)
fi

echo "[package] exporting committed source from HEAD"
if [ "$WITH_ASSETS" -eq 1 ]; then
  (cd "$ROOT" && git archive --format=tar HEAD) | tar -xf - -C "$STAGING"
else
  (cd "$ROOT" && git archive --format=tar HEAD -- ':!:models/**' ':!:tts_piper/**') | tar -xf - -C "$STAGING"
fi

mkdir -p "$STAGING/dist" "$STAGING/packaging/desktop" "$STAGING/models" "$STAGING/tts_piper" "$STAGING/blueprints"
# License docs live under models/ but models/** is excluded from the lean archive — copy explicitly
for _lic in MODEL_LICENSES.md README.txt; do
  [ -f "$ROOT/models/$_lic" ] && cp "$ROOT/models/$_lic" "$STAGING/models/"
done
if [ -f "$ROOT/packaging/desktop/Eli_Icon.png" ]; then
  if [ -x "$ROOT/.venv/bin/python" ] 2>/dev/null || [ -x "$PYTHON" ]; then
    _GEN_PY="${PYTHON:-python3}"
    [ -x "$ROOT/.venv/bin/python" ] && _GEN_PY="$ROOT/.venv/bin/python"
    "$_GEN_PY" "$ROOT/scripts/generate_branding_icons.py" 2>/dev/null || true
  fi
  cp "$ROOT/packaging/desktop/Eli_Icon.png" "$STAGING/packaging/desktop/"
  cp "$ROOT/packaging/desktop/Eli_Icon.png" "$STAGING/blueprints/"
  for _ic in Eli_Icon.ico eli-48.png eli-128.png eli-256.png; do
    [ -f "$ROOT/packaging/desktop/$_ic" ] && cp "$ROOT/packaging/desktop/$_ic" "$STAGING/packaging/desktop/"
  done
fi
if ls "$ROOT"/dist/eli_v2_0-*.whl >/dev/null 2>&1; then
  cp "$ROOT"/dist/eli_v2_0-*.whl "$STAGING/dist/"
fi

# Offline wheelhouse — set ELI_FULL_WHEELHOUSE=1 to bundle EVERY pinned wheel so the app
# installs with ZERO network (install.sh points pip at this dir). Default: just the CPU
# torch fallback wheel (keeps the download small). Best-effort: whatever pip can't fetch
# a wheel for (source-only or CUDA llama-cpp) simply falls back to the normal install path.
echo "[package] bundling wheelhouse (ELI_FULL_WHEELHOUSE=${ELI_FULL_WHEELHOUSE:-0})"
mkdir -p "$STAGING/wheelhouse"
"$PYTHON" -m pip download torch -d "$STAGING/wheelhouse" \
    --platform manylinux2014_x86_64 --python-version 312 --implementation cp \
    --abi cp312 --only-binary=:all: --no-deps -q 2>/dev/null || true
if [ "${ELI_FULL_WHEELHOUSE:-0}" = "1" ] && [ -f "$ROOT/requirements.lock.txt" ]; then
  echo "[package]   downloading full pinned wheel set (this is large, needs network)…"
  "$PYTHON" -m pip download -r "$ROOT/requirements.lock.txt" -d "$STAGING/wheelhouse" \
      --prefer-binary -q 2>/dev/null || echo "[package]   (some wheels unavailable — install will fetch those)"
fi
if [ -n "$(ls -A "$STAGING/wheelhouse" 2>/dev/null)" ]; then
  echo "[package] wheelhouse: $(ls -1 "$STAGING/wheelhouse"/*.whl 2>/dev/null | wc -l) wheel(s)"
else
  rmdir "$STAGING/wheelhouse" 2>/dev/null || true
fi

# Starter model — bundle ONE small GGUF so a fresh install answers immediately with no
# model download. Set ELI_STARTER_MODEL to a filename in models/ (default: tinyllama).
STARTER_MODEL="${ELI_STARTER_MODEL:-tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf}"
if [ -f "$ROOT/models/$STARTER_MODEL" ]; then
  echo "[package] bundling starter model: $STARTER_MODEL ($(du -h "$ROOT/models/$STARTER_MODEL" | cut -f1))"
  mkdir -p "$STAGING/models"; cp "$ROOT/models/$STARTER_MODEL" "$STAGING/models/"
else
  echo "[package] starter model $STARTER_MODEL not found in models/ — skipping (installer will download one)"
fi

if [ "$WITH_ASSETS" -eq 1 ]; then
  echo "[package] including ALL local model/voice assets; this can be very large"
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

cat > "$STAGING/INSTALL_ELI.sh" <<'INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$APP_ROOT/scripts/eli_setup.sh" "$@"
INSTALL_EOF
chmod +x "$STAGING/INSTALL_ELI.sh"

cat > "$STAGING/ELI_Setup.sh" <<'SETUP_EOF'
#!/usr/bin/env bash
# Double-click friendly name — same as scripts/eli_setup.sh (grandparent setup).
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$APP_ROOT/scripts/eli_setup.sh" "$@"
SETUP_EOF
chmod +x "$STAGING/ELI_Setup.sh"

cat > "$STAGING/packaging/desktop/ELI_v2.desktop.template" <<'DESKTOP_EOF'
[Desktop Entry]
Name=ELI v2.0
GenericName=Local AI Assistant
Comment=Local AI cognitive runtime and assistant
Exec=__APP_ROOT__/RUN_ELI.sh
Icon=eli
Type=Application
Categories=Utility;
Keywords=ai;assistant;llm;local;eli;eli_v2_0;
StartupNotify=true
Terminal=false
StartupWMClass=ELI
DESKTOP_EOF

cat > "$STAGING/packaging/desktop/install_desktop_launcher.sh" <<'DESKTOP_INSTALL_EOF'
#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESKTOP_DIR"
sed "s#__APP_ROOT__#$APP_ROOT#g" \
  "$APP_ROOT/packaging/desktop/ELI_v2.desktop.template" \
  > "$DESKTOP_DIR/eli-v2.desktop"
rm -f "$DESKTOP_DIR/eli.desktop" "$DESKTOP_DIR/eli-pro.desktop" "$DESKTOP_DIR/eli-v2-0.desktop"
chmod +x "$DESKTOP_DIR/eli-v2.desktop"
echo "$DESKTOP_DIR/eli-v2.desktop"
DESKTOP_INSTALL_EOF
chmod +x "$STAGING/packaging/desktop/install_desktop_launcher.sh"

cat > "$STAGING/README_INSTALL.txt" <<README_EOF
ELI v2.0 — portable download-and-run package

Hardware (honest):
  Best tested: Linux x86_64 + NVIDIA GPU.
  Windows/macOS/AMD builds exist; expect rough edges — feedback welcome.

Quick start (easiest):
  chmod +x ELI_Setup.sh && ./ELI_Setup.sh          # guided one-click setup (recommended)
  # picks chat models from full catalog + installs voice/embedder

Chat models (7 in catalog):
  qwen2.5-3b, qwen2.5-7b, qwen3-8b, falcon3-10b, phi-4, qwen3.6-35b-a3b, falcon-h1-34b
  Always installed: nomic embedder (~85 MB) + voice (whisper + piper)
  Re-pick later: .venv/bin/python -m eli.core.model_download --choose

Full new-user guide (all OS, every command):
  blueprints/new_user_install_guide.pdf

Phone / tablet (LAN + microphone):
  ./scripts/eli_serve.sh --lan --https

Linux AppImage (double-click after chmod +x):
  See GitHub Releases — ELI_v2-*-x86_64.AppImage

Windows Setup.exe:
  See GitHub Releases — ELI_v2-*-Setup.exe (or ELI_Setup.bat inside the zip)

Classic portable:
  1. ./INSTALL_ELI.sh
  2. ./RUN_ELI.sh --with-github-assets    # optional model/voice pack
  3. ./RUN_ELI.sh                         # launch ELI

Daily use:
  ./RUN_ELI.sh
  eli    (after INSTALL_ELI.sh installs ~/.local/bin/eli)

Model/voice pack (separate download — tag: local-assets-v2.1):
  gh auth login
  ./RUN_ELI.sh --with-github-assets
  # or: .venv/bin/python scripts/restore_github_asset_files.py --repo $REPO --tag $TAG
  # Ryan (NC-SA) and Lessac (uncleared) voices are skipped — see models/MODEL_LICENSES.md

Desktop launcher:
  ./packaging/desktop/install_desktop_launcher.sh

Data folders (auto-created on first run):
  artifacts/db/  artifacts/runtime/  config/

Terminal command:
  INSTALL_ELI.sh installs ~/.local/bin/eli by default.
  If your shell cached an older eli: hash -r

ELI v3 is in private development (not linked from this package).
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
