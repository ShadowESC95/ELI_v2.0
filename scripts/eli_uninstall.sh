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
ROOT_REAL="$(cd "$ROOT" && pwd -P)"
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
# What scripts/install_eli_command.sh (through fix_eli_shell_env.sh), fix_eli_shell_env.sh and
# eli.runtime.desktop_launchers write, by the same names they use.
RC_BEGIN="# >>> ELI v2 launcher (managed by scripts/fix_eli_shell_env.sh) >>>"
RC_END="# <<< ELI v2 launcher <<<"
if [ "$(uname -s)" = "Darwin" ]; then SHARE="$HOME/Library/Application Support/ELI_v2"
else SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/ELI_v2"; fi
POINTER="$SHARE/runtime/install_root"

# A terminal command install_eli_command.sh wrote, in any of its versions, for this install: one that
# starts a script in this folder (exec "<folder>/eli.sh", or the older APP_ROOT="<folder>").
_launcher_of_this_install() {
  grep -q "terminal launcher" "$1" 2>/dev/null || return 1
  local r
  for r in "$ROOT" "$ROOT_REAL"; do
    grep -qF "\"$r/" "$1" 2>/dev/null && return 0
    grep -qxF "APP_ROOT=\"$r\"" "$1" 2>/dev/null && return 0
  done
  return 1
}

# This script and the processes that started it (the terminal it runs in) match the patterns below
# as well; stopping them ended the uninstall before it removed anything.
_own_pids() {
  local p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    echo "$p"
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ' || true)"
  done
}

# Stop any ELI instance running FROM THIS install first — otherwise its background daemon
# (server / proactive / autonomy) keeps recreating artifacts/ and the folder "won't delete".
# Scoped to this ROOT so other ELI installs are untouched.
_stop_running() {
  local found own p pids=""
  found="$(pgrep -f "$ROOT/.venv/bin/python" 2>/dev/null; pgrep -f "$ROOT/scripts/eli_" 2>/dev/null)" || true
  own=" $(_own_pids | tr '\n' ' ') "
  for p in $(printf '%s\n' $found | sort -un); do
    case "$own" in *" $p "*) continue ;; esac
    kill -0 "$p" 2>/dev/null && pids="$pids $p"      # still running (the searches' own shells are gone)
  done
  pids="${pids# }"
  [ -n "$pids" ] || { echo "  ${GRN}OK${R}  No running ELI instance from this install."; return 0; }
  echo "  Stopping running ELI processes from this install: $pids"
  kill $pids 2>/dev/null || true; sleep 2
  for p in $pids; do kill -9 "$p" 2>/dev/null || true; done
  echo "  ${GRN}OK${R}  Stopped."
}

# The managed block fix_eli_shell_env.sh wrote into a shell start-up file, and the blank line it put
# before it, when the block points at this install. Written back in place (the file keeps its mode,
# and a link to a dotfiles folder stays a link).
_unpatch_rc() {
  local rc="$1" tmp
  [ -f "$rc" ] && grep -qxF "$RC_BEGIN" "$rc" 2>/dev/null || return 0
  tmp="$(mktemp)"
  awk -v b="$RC_BEGIN" -v e="$RC_END" -v r1="$ROOT/eli.sh" -v r2="$ROOT_REAL/eli.sh" '
    function flush() { if (held) { print ""; held = 0 } }
    inblock {
      block = block $0 "\n"
      if (index($0, r1) || index($0, r2)) ours = 1
      if ($0 == e) { inblock = 0; if (!ours) { if (blank) print ""; printf "%s", block } }
      next
    }
    $0 == b { inblock = 1; block = $0 "\n"; ours = 0; blank = held; held = 0; next }
    { flush() }
    $0 == "" { held = 1; next }
    { print }
    END { if (inblock) { if (blank) print ""; printf "%s", block }; flush() }
  ' "$rc" > "$tmp" && cat "$tmp" > "$rc"
  rm -f "$tmp"
  grep -qxF "$RC_BEGIN" "$rc" 2>/dev/null || echo "  ${GRN}OK${R}  Removed the eli-v2 / eli2 aliases from $rc"
}

echo
echo "Checking for a running ELI (server/desktop) from this install…"
_stop_running

echo
echo "This removes ELI v2's app-menu icons, its launcher scripts and theme icon, and the eli-v2 / eli2"
echo "commands, shell aliases and install pointer when they belong to this install (never another ELI's)."
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
  # The terminal commands install_eli_command.sh wrote for this install (another install's stay).
  for d in "$BIN" ${ELI_BIN_DIR:+"$ELI_BIN_DIR"}; do
    for n in eli-v2 eli2 ${ELI_COMMAND_NAME:+"$ELI_COMMAND_NAME"}; do
      if [ -f "$d/$n" ] && _launcher_of_this_install "$d/$n"; then
        rm -f "$d/$n" && echo "  ${GRN}OK${R}  Removed the command $d/$n"
      fi
    done
  done
  for rc in "$HOME/.bashrc" "$HOME/.bash_aliases" "$HOME/.profile"; do
    _unpatch_rc "$rc"
  done
  # The pointer the menu launchers follow, when it points here; its folder only when that leaves it empty.
  if [ -f "$POINTER" ]; then
    _pointed="$(tr -d '\r\n' < "$POINTER" 2>/dev/null || true)"
    if [ "$_pointed" = "$ROOT" ] || [ "$_pointed" = "$ROOT_REAL" ]; then
      rm -f "$POINTER" && echo "  ${GRN}OK${R}  Removed the install pointer $POINTER"
      rmdir "$SHARE/runtime" "$SHARE" 2>/dev/null || true
    fi
  fi
  echo "  ${GRN}OK${R}  Removed ELI v2's launchers, launcher script and theme icon."
else
  echo "  ${YEL}skipped${R}  system integration left in place."
fi

echo
echo "Your data (chats, memory, models) lives under: $ROOT/artifacts and $ROOT/models"
# --yes answers the integration question only: the folder (all data and models) goes with --purge,
# or with a yes typed here.
if [ "$PURGE" -eq 1 ] || { [ "$ASSUME_YES" -eq 0 ] && ask "Delete this ENTIRE install folder (all data + models)?"; }; then
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
