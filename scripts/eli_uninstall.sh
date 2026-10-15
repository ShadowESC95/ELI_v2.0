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

# Stop any ELI instance running FROM THIS install first — otherwise its background daemon
# (server / proactive / autonomy) keeps recreating artifacts/ and the folder "won't delete".
# Scoped to this ROOT so other ELI installs are untouched.
_stop_running() {
  local pids
  pids="$(pgrep -f "$ROOT/.venv/bin/python" 2>/dev/null; pgrep -f "$ROOT/scripts/eli_" 2>/dev/null)"
  pids="$(printf '%s\n' $pids | sort -un)"
  [ -n "$pids" ] || { echo "  ${GRN}OK${R}  No running ELI instance from this install."; return; }
  echo "  Stopping running ELI processes from this install: $(echo $pids | tr '\n' ' ')"
  kill $pids 2>/dev/null || true; sleep 2
  for p in $pids; do kill -9 "$p" 2>/dev/null || true; done
  echo "  ${GRN}OK${R}  Stopped."
}
echo
echo "Checking for a running ELI (server/desktop) from this install…"
_stop_running

echo
echo "This removes ELI v2's app-menu icons, its launcher script and its theme icon (never another ELI version's)."
if ask "Remove ELI's system integration now?"; then
  rm -f "$APPS"/eli-v2*.desktop "$BIN/eli-v2-run" 2>/dev/null || true
  # Older v2 entries and scripts had generic names other ELI versions also use: remove one only
  # when it is v2's (it names v2 or a v2 version).
  for f in "$APPS"/eli-setup.desktop "$APPS"/eli-server.desktop "$APPS"/eli-uninstall.desktop \
           "$APPS"/eli-pro.desktop "$BIN/eli" "$BIN/eli-run"; do
    if [ -f "$f" ] && grep -q -E 'ELI_v2|ELI v2|X-ELI-Version=2\.' "$f"; then rm -f "$f"; fi
  done
  # Only remove the theme icon v2 installed (never another version's).
  find "$ICONS" -type f -name 'eli-v2.*' -delete 2>/dev/null || true
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICONS" 2>/dev/null || true
  echo "  ${GRN}OK${R}  Removed ELI v2's launchers, launcher script and theme icon."
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
