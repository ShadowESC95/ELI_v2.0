#!/usr/bin/env bash
# ELI uninstaller — removes everything ELI added OUTSIDE this folder, then
# optionally deletes the folder itself. ELI is portable: all app data lives under
# this install directory, so uninstalling is mostly removing system integration.
#
#   ./scripts/eli_uninstall.sh            interactive
#   ./scripts/eli_uninstall.sh --yes      no prompts (removes integration; keeps folder)
#   ./scripts/eli_uninstall.sh --purge    also delete this whole install folder
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSUME_YES=0; PURGE=0
for a in "$@"; do
  case "$a" in
    --yes|-y) ASSUME_YES=1 ;;
    --purge)  ASSUME_YES=1; PURGE=1 ;;
  esac
done

if [ -t 1 ]; then B=$'\033[1m'; R=$'\033[0m'; GRN=$'\033[32m'; YEL=$'\033[33m'; else B=; R=; GRN=; YEL=; fi
echo "${B}ELI uninstaller${R}"
echo "  Install folder: $ROOT"

ask() { [ "$ASSUME_YES" -eq 1 ] && return 0; printf "  %s [y/N] " "$1"; read -r a || a=""; [ "$a" = y ] || [ "$a" = Y ]; }

APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
BIN="$HOME/.local/bin"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

echo
echo "This removes ELI's app-menu icons, the 'eli' command, and its theme icon."
if ask "Remove ELI's system integration now?"; then
  rm -f "$APPS"/eli-setup.desktop "$APPS"/eli-v2.desktop "$APPS"/eli-server.desktop \
        "$APPS"/eli-uninstall.desktop "$APPS"/eli-pro.desktop "$APPS"/eli-v2-0.desktop 2>/dev/null || true
  rm -f "$BIN/eli" 2>/dev/null || true
  # Only remove the eli theme icon we installed (never touch other icons).
  find "$ICONS" -type f -name 'eli.*' -delete 2>/dev/null || true
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICONS" 2>/dev/null || true
  echo "  ${GRN}OK${R}  Removed launchers, 'eli' command, and theme icon."
else
  echo "  ${YEL}skipped${R}  system integration left in place."
fi

echo
echo "Your data (chats, memory, models) lives under: $ROOT/artifacts and $ROOT/models"
if [ "$PURGE" -eq 1 ] || ask "Delete this ENTIRE install folder (all data + models)?"; then
  echo "  Deleting $ROOT …"
  # Detach from the folder before removing it.
  cd "$HOME" 2>/dev/null || cd /
  rm -rf "$ROOT"
  echo "  ${GRN}OK${R}  ELI fully removed."
else
  echo "  ${YEL}kept${R}  the install folder — delete it manually anytime: rm -rf \"$ROOT\""
fi

echo
echo "${B}Done.${R} ELI was 100% local — nothing was ever stored in the cloud to remove."
