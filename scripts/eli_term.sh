#!/usr/bin/env bash
# Run a command inside a terminal window, portably.
#
# Modern GNOME/Wayland silently ignores `Terminal=true` in .desktop launchers
# (it no longer auto-spawns a terminal), so ELI's Setup/Server icons appeared to
# "do nothing". This helper is launched with Terminal=false and finds a real
# terminal emulator itself, so the icons work on GNOME, KDE, XFCE, wlroots, etc.
#
#   eli_term.sh /path/to/script.sh [args…]
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: eli_term.sh <command> [args…]" >&2; exit 2; }

# Keep the window open if the command exits/fails so the user can read output.
_hold() { "$@"; rc=$?; echo; echo "[ELI] finished (exit $rc). Press Enter to close."; read -r _ || true; }
export -f _hold

# Try terminals in rough order of ubiquity. Each takes a slightly different flag
# to run a command, so we special-case the exec form per emulator.
for term in gnome-terminal konsole xfce4-terminal kgx tilix mate-terminal \
            kitty alacritty foot wezterm x-terminal-emulator xterm; do
  command -v "$term" >/dev/null 2>&1 || continue
  case "$term" in
    gnome-terminal|tilix|mate-terminal|xfce4-terminal)
      exec "$term" -- bash -c '_hold "$@"' _ "$@" ;;
    konsole|kgx)
      exec "$term" -e bash -c '_hold "$@"' _ "$@" ;;
    kitty|alacritty|foot|wezterm|x-terminal-emulator|xterm)
      exec "$term" -e bash -c '_hold "$@"' _ "$@" ;;
  esac
done

# No terminal emulator found — run headless so the action still happens.
echo "[ELI] no terminal emulator found; running without a window…" >&2
exec "$@"
