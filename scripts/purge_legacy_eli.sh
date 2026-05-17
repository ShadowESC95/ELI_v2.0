#!/usr/bin/env bash
# Remove the old system-level ELI package/remnants without touching this checkout.
set -euo pipefail

ASSUME_YES=0
DRY_RUN=0

usage() {
  cat <<'EOF_USAGE'
Usage: sudo bash scripts/purge_legacy_eli.sh [options]

Options:
  --yes      Do not prompt before removing legacy files.
  --dry-run  Show what would be removed without changing the system.
  -h, --help Show help.

This removes only the legacy system install paths:
  apt package: eli
  /opt/eli
  /etc/eli
  /usr/share/applications/eli.desktop

It does not remove the current ELI Pro checkout or ~/.local/share/applications/eli.desktop.
EOF_USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
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

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "[legacy-purge] root privileges required." >&2
  echo "[legacy-purge] run: sudo bash scripts/purge_legacy_eli.sh --yes" >&2
  exit 1
fi

echo "[legacy-purge] target package: eli"
dpkg-query -W -f='[legacy-purge] dpkg: ${db:Status-Abbrev} ${Package} ${Version}\n' eli 2>/dev/null || \
  echo "[legacy-purge] dpkg: eli package not registered"

TARGETS=(
  "/opt/eli"
  "/etc/eli"
  "/usr/share/applications/eli.desktop"
)

found=0
for target in "${TARGETS[@]}"; do
  if [ -e "$target" ] || [ -L "$target" ]; then
    found=1
    echo "[legacy-purge] found: $target"
  fi
done

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[legacy-purge] dry run complete; no changes made."
  exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  printf "Remove legacy ELI package/remnants? [yes/no]: "
  read -r answer
  case "$answer" in
    yes|YES|y|Y) ;;
    *)
      echo "[legacy-purge] aborted."
      exit 1
      ;;
  esac
fi

if dpkg-query -W -f='${db:Status-Abbrev}' eli 2>/dev/null | grep -q '^[irchpu]'; then
  apt-get purge -y eli || true
fi

for target in "${TARGETS[@]}"; do
  if [ -e "$target" ] || [ -L "$target" ]; then
    rm -rf -- "$target"
    echo "[legacy-purge] removed: $target"
  fi
done

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

if [ "$found" -eq 0 ]; then
  echo "[legacy-purge] no legacy files were present."
fi
echo "[legacy-purge] complete. ELI Pro user launcher is left untouched."
