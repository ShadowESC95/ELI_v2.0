#!/usr/bin/env bash
# Reset a stuck CSR / USB Bluetooth dongle (hci0 ENOMEM / "No Resources").
# Run: sudo bash scripts/eli_bt_reset.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash scripts/eli_bt_reset.sh" >&2
  exit 1
fi

echo "[eli-bt] Stopping Bluetooth..."
systemctl stop bluetooth

echo "[eli-bt] Bringing hci interfaces down..."
for h in /sys/class/bluetooth/hci*; do
  [ -e "$h" ] || continue
  name="$(basename "$h")"
  hciconfig "$name" down 2>/dev/null || true
done

echo "[eli-bt] Reloading btusb driver..."
modprobe -r btusb 2>/dev/null || true
sleep 2
modprobe btusb
sleep 2

echo "[eli-bt] Starting Bluetooth..."
systemctl start bluetooth
sleep 2

CSR=""
for h in /sys/class/bluetooth/hci*; do
  [ -e "$h" ] || continue
  name="$(basename "$h")"
  addr="$(hciconfig "$name" 2>/dev/null | awk '/BD Address/{print $3}')"
  if [ "$addr" != "00:00:00:00:00:00" ] && [ -n "$addr" ]; then
    CSR="$name"
    break
  fi
done

if [ -z "$CSR" ]; then
  echo "[eli-bt] No working Bluetooth adapter found after reset." >&2
  echo "  Try: unplug the USB BT dongle (port 1-6), wait 5s, replug, run this script again." >&2
  hciconfig -a || true
  exit 1
fi

echo "[eli-bt] Bringing up $CSR..."
if ! hciconfig "$CSR" up; then
  echo "[eli-bt] hciconfig $CSR up failed — try unplugging/replugging the USB dongle." >&2
  exit 1
fi

bluetoothctl power on || true
bluetoothctl pairable on || true

echo "[eli-bt] Status:"
hciconfig "$CSR" | head -3
bluetoothctl show | grep -E 'Powered|Pairable|Alias' || true
echo "[eli-bt] Done — retry Pair in ELI."
