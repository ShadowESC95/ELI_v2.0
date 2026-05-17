#!/usr/bin/env bash
# Install a user-level `eli` command that launches this checkout through its venv.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${ELI_BIN_DIR:-$HOME/.local/bin}"
NAME="${ELI_COMMAND_NAME:-eli}"
FORCE=0

usage() {
  cat <<EOF_USAGE
Usage: scripts/install_eli_command.sh [options]

Options:
  --name NAME       Command name to install. Default: $NAME
  --bin-dir PATH    Install directory. Default: $BIN_DIR
  --force           Replace an existing command at the target path.
  -h, --help        Show help.

Installs:
  $BIN_DIR/$NAME

The installed command runs:
  $ROOT/scripts/eli_startup.sh "\$@"
EOF_USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --name)
      shift
      NAME="${1:?--name requires a value}"
      ;;
    --bin-dir)
      shift
      BIN_DIR="${1:?--bin-dir requires a path}"
      ;;
    --force)
      FORCE=1
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

case "$NAME" in
  ""|*/*)
    echo "Invalid command name: $NAME" >&2
    exit 2
    ;;
esac

mkdir -p "$BIN_DIR"
TARGET="$BIN_DIR/$NAME"

if [ -e "$TARGET" ] && [ "$FORCE" -ne 1 ]; then
  echo "[install-command] target already exists: $TARGET" >&2
  echo "[install-command] rerun with --force to replace it." >&2
  exit 1
fi

cat > "$TARGET" <<EOF_LAUNCHER
#!/usr/bin/env bash
# ELI MKXI v2.0 PRO terminal launcher.
set -euo pipefail
APP_ROOT="$ROOT"
exec "\$APP_ROOT/scripts/eli_startup.sh" "\$@"
EOF_LAUNCHER
chmod +x "$TARGET"

echo "[install-command] installed: $TARGET"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo "[install-command] warning: $BIN_DIR is not currently in PATH." >&2
    echo "[install-command] add this to your shell profile:" >&2
    echo "  export PATH=\"$BIN_DIR:\$PATH\"" >&2
    ;;
esac

resolved="$(command -v "$NAME" 2>/dev/null || true)"
if [ -n "$resolved" ] && [ "$resolved" != "$TARGET" ]; then
  echo "[install-command] warning: '$NAME' currently resolves to $resolved" >&2
  echo "[install-command] open a new terminal or run 'hash -r'; if it still resolves elsewhere, move $BIN_DIR earlier in PATH." >&2
fi
