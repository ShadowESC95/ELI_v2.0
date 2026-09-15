#!/usr/bin/env bash
# Fix stale ELI desktop / menu icons that still point at a deleted portable folder
# (e.g. …/ELI_v2-2.4.29-linux-portable). GNOME fails on Path= BEFORE Exec runs,
# so clicking those icons never reaches the 2.4.34+ eli-run refresh.
#
# Usage (from any ELI extract / checkout):
#   bash scripts/fix_eli_desktop_icons.sh
#   bash scripts/fix_eli_desktop_icons.sh --install   # also rewrite launchers for THIS tree
#
# Safe: only touches eli*.desktop / ELI*.desktop under applications + Desktop.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DO_INSTALL=0
for a in "$@"; do
  case "$a" in
    --install|-i) DO_INSTALL=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
  esac
done

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESK="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
if [ -f "$HOME/.config/user-dirs.dirs" ]; then
  # shellcheck disable=SC1090
  . "$HOME/.config/user-dirs.dirs" 2>/dev/null || true
  DESK="${XDG_DESKTOP_DIR:-$DESK}"
  DESK="${DESK/#\$HOME/$HOME}"
fi

_removed=0
_scrub_dir() {
  local d="$1"
  [ -d "$d" ] || return 0
  local f text path_line path_val
  shopt -s nullglob
  for f in "$d"/eli*.desktop "$d"/ELI*.desktop; do
    [ -f "$f" ] || continue
    text="$(cat "$f" 2>/dev/null || true)"
    path_line="$(printf '%s\n' "$text" | grep -E '^Path=' | head -1 || true)"
    kill=0
    if [ -n "$path_line" ]; then
      path_val="${path_line#Path=}"
      path_val="${path_val%\"}"
      path_val="${path_val#\"}"
      path_val="${path_val%\'}"
      path_val="${path_val#\'}"
      if [ -n "$path_val" ] && [ ! -d "$path_val" ]; then
        kill=1
      fi
      case "$path_val" in
        *linux-portable*|*ELI_v2-*|*ELI_v3-*) kill=1 ;;
      esac
    fi
    case "$text" in
      *linux-portable*|*ELI_v2-*linux*|*ELI_v3-*linux*) kill=1 ;;
    esac
    if [ "$kill" = 1 ]; then
      echo "[fix] removing stale launcher: $f"
      rm -f "$f"
      _removed=$((_removed + 1))
    fi
  done
  shopt -u nullglob
}

echo "[fix] scrubbing ELI launchers under:"
echo "       $APPS"
echo "       $DESK"
_scrub_dir "$APPS"
_scrub_dir "$DESK"

if [ "$DO_INSTALL" = 1 ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
  else
    PY="$(command -v python3 || echo python3)"
  fi
  export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
  export ELI_PROJECT_ROOT="$ROOT"
  echo "[fix] rewriting launchers for: $ROOT"
  if "$PY" -m eli.runtime.desktop_launchers install --root "$ROOT"; then
    echo "[fix] install_desktop_launchers OK"
  else
    echo "[fix] Python installer failed — stale Path= stubs were still removed ($_removed)." >&2
    echo "       Re-run: bash \"$ROOT/scripts/install_desktop_apps.sh\"" >&2
  fi
else
  echo "[fix] removed $_removed stale launcher(s)."
  echo "       Next: from your CURRENT ELI folder run:"
  echo "         bash scripts/fix_eli_desktop_icons.sh --install"
  echo "       or: bash scripts/install_desktop_apps.sh"
  echo "       Then use the new Desktop / app-menu icons (not the old 2.4.29 stub)."
fi
