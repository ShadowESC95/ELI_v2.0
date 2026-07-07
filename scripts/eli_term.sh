#!/usr/bin/env bash
# Run a command inside a terminal window, portably.
#
# Modern GNOME/Wayland silently ignores `Terminal=true` in .desktop launchers, so ELI's
# Setup/Server icons appeared to "do nothing". This helper is launched with Terminal=false
# and finds a real terminal emulator itself (GNOME, KDE, XFCE, wlroots, …).
#
# IMPORTANT: gnome-terminal routes through a login-time daemon that does NOT inherit
# exported shell functions, so we build ONE self-contained command STRING (every arg
# safely quoted) and hold the window open at the end — no exported functions.
#
#   eli_term.sh /path/to/script.sh [args…]
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: eli_term.sh <command> [args…]" >&2; exit 2; }

# Immediate feedback in case the terminal takes a moment to appear.
command -v notify-send >/dev/null 2>&1 && notify-send "ELI" "Starting…" 2>/dev/null || true

# One inline command: run the (quoted) target, then keep the window open so the user can
# read the output / URL + token. $? and $_rc are escaped so they evaluate in the terminal.
CMD="$(printf '%q ' "$@"); _rc=\$?; echo; echo \"[ELI] finished (exit \$_rc). Press Enter to close.\"; read -r _ || true"

for term in gnome-terminal tilix mate-terminal xfce4-terminal konsole kgx \
            kitty alacritty foot wezterm x-terminal-emulator xterm; do
  command -v "$term" >/dev/null 2>&1 || continue
  case "$term" in
    gnome-terminal|tilix|mate-terminal|xfce4-terminal)
      exec "$term" -- bash -c "$CMD" ;;
    *)
      exec "$term" -e bash -c "$CMD" ;;
  esac
done

# No terminal emulator found — run headless so the action still happens.
echo "[ELI] no terminal emulator found; running without a window…" >&2
exec "$@"
