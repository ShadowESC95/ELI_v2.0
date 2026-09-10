#!/usr/bin/env bash
# Point the shell `eli` command at THIS checkout and clear stale ELI_* exports.
#
# Fixes the common failure mode: a bash alias or exported ELI_PROJECT_ROOT from
# another folder (v2 dev tree, v3 checkout, old portable path) makes ELI write
# into the wrong artifacts/ tree.
#
# Usage:  bash scripts/fix_eli_shell_env.sh [--force] [--yes]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=0
ASSUME_YES=0
MARK_BEGIN="# >>> ELI v2 launcher (managed by scripts/fix_eli_shell_env.sh) >>>"
MARK_END="# <<< ELI v2 launcher <<<"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help)
      echo "Usage: bash scripts/fix_eli_shell_env.sh [--force] [--yes]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

echo "[fix-shell] checkout: $ROOT"

bash "$ROOT/scripts/install_eli_command.sh" --force --name eli
bash "$ROOT/scripts/install_eli_command.sh" --force --name eli2

_patch_rc() {
  local rc="$1"
  [ -f "$rc" ] || return 0
  local tmp
  tmp="$(mktemp)"
  awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
    $0 == b { skip=1; next }
    $0 == e { skip=0; next }
    skip { next }
    /^[[:space:]]*alias[[:space:]]+eli=/ { next }
    /^[[:space:]]*export[[:space:]]+ELI_PROJECT_ROOT=/ { next }
    { print }
  ' "$rc" > "$tmp"
  mv "$tmp" "$rc"
  {
    echo ""
    echo "$MARK_BEGIN"
    echo "# Prefer this checkout when you type: eli"
    echo "unalias eli 2>/dev/null || true"
    echo "alias eli='$ROOT/eli.sh'"
    echo "alias eli2='$ROOT/eli.sh'"
    echo "# Do not export ELI_PROJECT_ROOT globally — each launcher sets it."
    echo "$MARK_END"
  } >> "$rc"
  echo "[fix-shell] updated: $rc"
}

for rc in "$HOME/.bashrc" "$HOME/.bash_aliases" "$HOME/.profile"; do
  _patch_rc "$rc"
done

echo "[fix-shell] done."
echo "[fix-shell] Open a new terminal, then:  type eli"
echo "[fix-shell] Expected: alias eli='$ROOT/eli.sh'  OR  $HOME/.local/bin/eli"
