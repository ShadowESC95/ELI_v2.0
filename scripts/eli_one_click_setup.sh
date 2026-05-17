#!/usr/bin/env bash
# One-command ELI setup from a source checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CPU_ONLY=0
SKIP_TORCH=0
WITH_GITHUB_ASSETS=0
INSTALL_DESKTOP=1
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_MKXI_v2.0_PRO}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.0}"

usage() {
  cat <<EOF
Usage: scripts/eli_one_click_setup.sh [options]

Options:
  --cpu-only              Install CPU Torch/llama paths.
  --skip-torch            Do not install Torch.
  --with-github-assets    Restore model/voice release assets after install.
  --repo OWNER/REPO       Asset repo. Default: $REPO
  --tag TAG               Asset release tag. Default: $TAG
  --no-desktop            Do not install user desktop launcher.
  -h, --help              Show help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --cpu-only) CPU_ONLY=1 ;;
    --skip-torch) SKIP_TORCH=1 ;;
    --with-github-assets) WITH_GITHUB_ASSETS=1 ;;
    --repo)
      shift
      REPO="${1:?--repo requires OWNER/REPO}"
      ;;
    --tag)
      shift
      TAG="${1:?--tag requires a value}"
      ;;
    --no-desktop) INSTALL_DESKTOP=0 ;;
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

INSTALL_ARGS=()
[ "$CPU_ONLY" -eq 1 ] && INSTALL_ARGS+=(--cpu-only)
[ "$SKIP_TORCH" -eq 1 ] && INSTALL_ARGS+=(--skip-torch)

echo "[setup] Installing ELI MKXI v2.0 PRO"
bash "$ROOT/install.sh" "${INSTALL_ARGS[@]}"

if [ "$WITH_GITHUB_ASSETS" -eq 1 ]; then
  echo "[setup] Restoring GitHub release assets"
  bash "$ROOT/scripts/restore_github_assets.sh" --repo "$REPO" --tag "$TAG"
fi

if [ "$INSTALL_DESKTOP" -eq 1 ] && [ "$(uname -s)" = "Linux" ]; then
  DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$DESKTOP_DIR"
  cat > "$DESKTOP_DIR/eli-mkxi-v2-pro.desktop" <<EOF
[Desktop Entry]
Name=ELI MKXI v2.0 PRO
Comment=Local AI cognitive runtime and assistant
Exec=$ROOT/scripts/eli_one_click_run.sh
Icon=$ROOT/blueprints/eli_logo2.png
Type=Application
Categories=Utility;Science;ArtificialIntelligence;
StartupNotify=true
Terminal=false
EOF
  chmod +x "$DESKTOP_DIR/eli-mkxi-v2-pro.desktop"
  echo "[setup] Desktop launcher installed: $DESKTOP_DIR/eli-mkxi-v2-pro.desktop"
fi

echo ""
echo "[setup] Complete. Run:"
echo "  scripts/eli_one_click_run.sh"
