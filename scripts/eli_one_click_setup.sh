#!/usr/bin/env bash
# One-command ELI setup from a source checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CPU_ONLY=0
SKIP_TORCH=0
WITH_GITHUB_ASSETS=0
INSTALL_DESKTOP=1
INSTALL_COMMAND=1
ASSET_MODE="direct"
REPO="${GITHUB_REPOSITORY:-ShadowESC95/ELI_MKXI_v2.0_PRO}"
TAG="${ELI_ASSET_RELEASE_TAG:-local-assets-v2.0}"
COMMAND_NAME="${ELI_COMMAND_NAME:-eli}"
BIN_DIR="${ELI_BIN_DIR:-$HOME/.local/bin}"

usage() {
  cat <<EOF
Usage: scripts/eli_one_click_setup.sh [options]

Options:
  --cpu-only              Install CPU Torch/llama paths.
  --skip-torch            Do not install Torch.
  --with-github-assets    Restore model/voice release assets after install.
  --asset-mode MODE       Asset restore mode: direct or archive. Default: $ASSET_MODE
  --repo OWNER/REPO       Asset repo. Default: $REPO
  --tag TAG               Asset release tag. Default: $TAG
  --no-desktop            Do not install user desktop launcher.
  --no-command            Do not install the terminal command.
  --command-name NAME     Terminal command name. Default: $COMMAND_NAME
  --bin-dir PATH          Terminal command install dir. Default: $BIN_DIR
  -h, --help              Show help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --cpu-only) CPU_ONLY=1 ;;
    --skip-torch) SKIP_TORCH=1 ;;
    --with-github-assets) WITH_GITHUB_ASSETS=1 ;;
    --asset-mode)
      shift
      ASSET_MODE="${1:?--asset-mode requires direct or archive}"
      ;;
    --repo)
      shift
      REPO="${1:?--repo requires OWNER/REPO}"
      ;;
    --tag)
      shift
      TAG="${1:?--tag requires a value}"
      ;;
    --no-desktop) INSTALL_DESKTOP=0 ;;
    --no-command) INSTALL_COMMAND=0 ;;
    --command-name)
      shift
      COMMAND_NAME="${1:?--command-name requires a value}"
      ;;
    --bin-dir)
      shift
      BIN_DIR="${1:?--bin-dir requires a path}"
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

INSTALL_ARGS=()
[ "$CPU_ONLY" -eq 1 ] && INSTALL_ARGS+=(--cpu-only)
[ "$SKIP_TORCH" -eq 1 ] && INSTALL_ARGS+=(--skip-torch)

case "$ASSET_MODE" in
  direct|archive) ;;
  *)
    echo "Invalid --asset-mode: $ASSET_MODE" >&2
    echo "Expected: direct or archive" >&2
    exit 2
    ;;
esac

echo "[setup] Installing ELI Pro"
bash "$ROOT/install.sh" "${INSTALL_ARGS[@]}"

if [ "$WITH_GITHUB_ASSETS" -eq 1 ]; then
  echo "[setup] Restoring GitHub release assets ($ASSET_MODE)"
  if [ "$ASSET_MODE" = "direct" ]; then
    "$ROOT/.venv/bin/python" "$ROOT/scripts/restore_github_asset_files.py" --repo "$REPO" --tag "$TAG"
  else
    bash "$ROOT/scripts/restore_github_assets.sh" --repo "$REPO" --tag "$TAG"
  fi
fi

if [ "$INSTALL_DESKTOP" -eq 1 ] && [ "$(uname -s)" = "Linux" ]; then
  DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$DESKTOP_DIR"
  write_desktop_entry() {
    local target="$1"
    local name="$2"
    cat > "$target" <<EOF
[Desktop Entry]
Name=$name
GenericName=Local AI Assistant
Comment=Local AI cognitive runtime and assistant
Exec=$ROOT/scripts/eli_one_click_run.sh
Icon=$ROOT/blueprints/eli_logo2.png
Type=Application
Categories=Utility;
Keywords=ai;assistant;llm;local;eli;mkxi;
StartupNotify=true
Terminal=false
StartupWMClass=ELI
EOF
  }
  # User-level override for the legacy system package entry at /usr/share/applications/eli.desktop.
  # This keeps old package files intact while making app menus launch this checkout.
  write_desktop_entry "$DESKTOP_DIR/eli.desktop" "ELI Pro"
  rm -f "$DESKTOP_DIR/eli-pro.desktop" "$DESKTOP_DIR/eli-mkxi-v2-pro.desktop"
  chmod +x "$DESKTOP_DIR/eli.desktop"
  echo "[setup] Desktop launcher installed: $DESKTOP_DIR/eli.desktop"
  echo "[setup] Legacy ELI app-menu override installed as ELI Pro"
fi

if [ "$INSTALL_COMMAND" -eq 1 ]; then
  bash "$ROOT/scripts/install_eli_command.sh" \
    --name "$COMMAND_NAME" \
    --bin-dir "$BIN_DIR" \
    --force
fi

if [ -d /opt/eli ] || [ -d /etc/eli ]; then
  echo "[setup] Legacy ELI package remnants detected."
  echo "[setup] Remove them with: sudo bash $ROOT/scripts/purge_legacy_eli.sh --yes"
fi

echo ""
echo "[setup] Complete. Run:"
echo "  $COMMAND_NAME"
echo "  scripts/eli_one_click_run.sh"
