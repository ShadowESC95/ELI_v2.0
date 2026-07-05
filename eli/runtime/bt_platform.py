"""Cross-platform Bluetooth radio detection, recovery, and classic discovery.

Every machine differs (built-in radio, USB dongle, multiple hci*, BlueZ vs WinRT).
This module auto-discovers adapters on Linux, macOS, and Windows, picks a working
controller, and returns actionable recovery hints — never hard-codes hci0/hci1.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

_ZERO_MAC = "00:00:00:00:00:00"
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def platform_kind() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def _valid_mac(addr: str) -> bool:
    a = (addr or "").strip().upper()
    return bool(a and a != _ZERO_MAC and _MAC_RE.match(a))


def _sh(args: List[str], timeout: float = 25.0) -> Tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "tool-not-found"
    except Exception as e:
        return 1, str(e)


def powershell(script: str, timeout: float = 30.0) -> Tuple[int, str]:
    """Run a PowerShell snippet (Windows)."""
    return _powershell(script, timeout=timeout)


def _powershell(script: str, timeout: float = 30.0) -> Tuple[int, str]:
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        return 127, "powershell not found"
    return _sh([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


@dataclass
class BtAdapter:
    """One Bluetooth radio — kernel hci*, BlueZ controller, or OS radio."""
    id: str
    name: str = ""
    address: str = ""
    powered: bool = False
    state: str = "unknown"       # up, down, unknown
    bus: str = "unknown"         # usb, builtin, pci, unknown
    bluez: bool = False          # registered with BlueZ bluetoothctl
    source: str = ""             # kernel, bluez, os


def _linux_hci_bus(hci_path: str) -> str:
    try:
        real = os.path.realpath(os.path.join(hci_path, "device"))
        if "/usb" in real.lower():
            return "usb"
        if "/pci" in real.lower():
            return "pci"
    except Exception:
        pass
    return "unknown"


def _linux_kernel_adapters() -> List[BtAdapter]:
    adapters: List[BtAdapter] = []
    for path in sorted(glob.glob("/sys/class/bluetooth/hci*")):
        name = os.path.basename(path)
        addr = ""
        try:
            with open(os.path.join(path, "address"), encoding="utf-8") as f:
                addr = f.read().strip().upper()
        except Exception:
            pass
        state = "unknown"
        if shutil.which("hciconfig"):
            _, out = _sh(["hciconfig", name], timeout=4)
            state = "up" if re.search(r"\bUP\b", out or "") else "down"
            if not addr:
                m = re.search(r"BD Address:\s*([0-9A-Fa-f:]{17})", out or "")
                if m:
                    addr = m.group(1).upper()
        adapters.append(BtAdapter(
            id=name,
            address=addr,
            state=state,
            bus=_linux_hci_bus(path),
            powered=state == "up" and _valid_mac(addr),
            source="kernel",
        ))
    return adapters


def _linux_bluez_controllers() -> List[BtAdapter]:
    if not shutil.which("bluetoothctl"):
        return []
    _, out = _sh(["bluetoothctl", "list"], timeout=8)
    adapters: List[BtAdapter] = []
    for addr in re.findall(r"Controller\s+([0-9A-Fa-f:]{17})", out or ""):
        adapters.append(BtAdapter(
            id=addr.upper(),
            address=addr.upper(),
            bluez=True,
            powered=_valid_mac(addr),
            state="up" if _valid_mac(addr) else "down",
            source="bluez",
        ))
    return adapters


def list_adapters() -> List[BtAdapter]:
    """Auto-discover every Bluetooth radio the OS exposes."""
    kind = platform_kind()
    if kind == "linux":
        by_id: Dict[str, BtAdapter] = {}
        for a in _linux_kernel_adapters():
            by_id[a.id] = a
        for b in _linux_bluez_controllers():
            key = b.address or b.id
            if key in by_id:
                existing = by_id[key]
                existing.bluez = True
                existing.powered = b.powered or existing.powered
                if b.address:
                    existing.address = b.address
            else:
                # Match kernel hci by MAC when BlueZ knows the address
                matched = False
                for k, existing in by_id.items():
                    if existing.address and existing.address == b.address:
                        existing.bluez = True
                        existing.powered = b.powered or existing.powered
                        matched = True
                        break
                if not matched:
                    by_id[b.id] = b
        return list(by_id.values())

    if kind == "darwin":
        adapters: List[BtAdapter] = []
        powered = False
        if shutil.which("blueutil"):
            _, out = _sh(["blueutil", "-p"], timeout=5)
            powered = out.strip() == "1"
        name = "Bluetooth"
        _, sp = _sh(["system_profiler", "SPBluetoothDataType"], timeout=15)
        for line in (sp or "").splitlines():
            low = line.strip().lower()
            if low.startswith("chipset:") or low.startswith("product id:"):
                name = line.split(":", 1)[-1].strip() or name
                break
        adapters.append(BtAdapter(
            id="default",
            name=name,
            powered=powered,
            state="up" if powered else "down",
            bus="builtin",
            source="os",
        ))
        return adapters

    # Windows — WinRT Bluetooth radio via PowerShell
    rc, out = _powershell(
        "try {"
        "  $r = [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]"
        "    ::GetRadiosAsync().GetAwaiter().GetResult() |"
        "    Where-Object { $_.Kind -eq 'Bluetooth' };"
        "  foreach ($x in $r) { Write-Output ($x.Name + '|' + $x.State) }"
        "} catch { Write-Output ('ERROR|' + $_.Exception.Message) }",
        timeout=20,
    )
    adapters: List[BtAdapter] = []
    if rc == 0:
        for line in (out or "").splitlines():
            if "|" not in line:
                continue
            nm, st = line.split("|", 1)
            nm, st = nm.strip(), st.strip()
            if nm.upper().startswith("ERROR"):
                break
            adapters.append(BtAdapter(
                id=nm or "bluetooth",
                name=nm or "Bluetooth",
                powered=st.lower() == "on",
                state="up" if st.lower() == "on" else "down",
                bus="builtin",
                source="os",
            ))
    if not adapters:
        # Fallback: PnP Bluetooth radio devices
        rc2, pnp = _powershell(
            "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |"
            " Where-Object { $_.FriendlyName -match 'Radio|Adapter' } |"
            " ForEach-Object { $_.FriendlyName + '|' + $_.Status }",
            timeout=15,
        )
        if rc2 == 0:
            for line in (pnp or "").splitlines():
                if "|" not in line:
                    continue
                nm, st = line.split("|", 1)
                adapters.append(BtAdapter(
                    id=nm.strip(),
                    name=nm.strip(),
                    powered=st.strip().lower() == "ok",
                    state="up" if st.strip().lower() == "ok" else "down",
                    bus="unknown",
                    source="pnp",
                ))
    return adapters


def recovery_hint(adapters: Optional[List[BtAdapter]] = None) -> str:
    """Platform-specific, hardware-agnostic recovery guidance."""
    adapters = adapters if adapters is not None else list_adapters()
    kind = platform_kind()

    if kind == "linux":
        down = _linux_hci_down()
        if down:
            names = " ".join(down)
            return (f"Bluetooth adapter is down ({names}) — run: "
                    f"sudo bash scripts/eli_bt_reset.sh  (or: sudo hciconfig {names} up)")
        down_legacy = [a.id for a in adapters if a.state == "down" and a.source == "kernel"]
        if down_legacy:
            names = " ".join(down_legacy)
            return (f"replug your USB Bluetooth adapter, then run: "
                    f"sudo hciconfig {names} up && sudo systemctl restart bluetooth")
        if adapters and not any(a.bluez for a in adapters):
            return ("Bluetooth hardware detected but BlueZ has no controller — "
                    "replug the adapter or run: sudo systemctl restart bluetooth")
        if adapters and not any(a.powered or a.bluez for a in adapters):
            return "enable Bluetooth in system settings or replug your USB adapter"
        if not shutil.which("bluetoothctl"):
            return "install BlueZ (bluetoothctl package) and enable Bluetooth"
        return "enable Bluetooth in system settings or replug your USB adapter"

    if kind == "darwin":
        if not shutil.which("blueutil"):
            return ("enable Bluetooth in System Settings, or install blueutil "
                    "(brew install blueutil) for ELI control")
        return "turn on Bluetooth in System Settings → Control Centre (or run: blueutil -p 1)"

    if not shutil.which("powershell") and not shutil.which("pwsh"):
        return "turn on Bluetooth in Settings → Bluetooth & devices"
    return "turn on Bluetooth in Settings → Bluetooth & devices"


def _linux_hci_down() -> List[str]:
    """Kernel hci* interfaces that are DOWN (BlueZ cannot power on until these are up)."""
    down = []
    for a in _linux_kernel_adapters():
        if a.state != "down":
            continue
        if _valid_mac(a.address) or a.id == "hci0":
            down.append(a.id)
    return down


def _linux_try_recover() -> None:
    if shutil.which("rfkill"):
        _sh(["rfkill", "unblock", "bluetooth"], timeout=5)
    if shutil.which("hciconfig"):
        for adapter in _linux_kernel_adapters():
            if adapter.state != "up":
                _sh(["hciconfig", adapter.id, "up"], timeout=5)


def try_recover_radio() -> None:
    """Best-effort radio recovery without admin (Linux rfkill/hciconfig; OS-specific elsewhere)."""
    kind = platform_kind()
    if kind == "linux":
        _linux_try_recover()
    elif kind == "darwin" and shutil.which("blueutil"):
        _sh(["blueutil", "-p", "1"], timeout=5)
    elif kind == "windows":
        _windows_ensure_radio()


def _linux_pick_controller(addrs: List[str], adapters: List[BtAdapter]) -> str:
    """Prefer a BlueZ controller with a real MAC; fall back to any listed."""
    valid = [a for a in addrs if _valid_mac(a)]
    if valid:
        usb_addrs = {a.address for a in adapters if a.bus == "usb" and a.bluez}
        for addr in valid:
            if addr.upper() in usb_addrs or addr in valid[:1]:
                return addr
        return valid[0]
    return addrs[0] if addrs else ""


def _linux_ensure_radio() -> Tuple[bool, str]:
    if not shutil.which("bluetoothctl"):
        return False, recovery_hint()

    def _controllers() -> List[str]:
        _, listing = _sh(["bluetoothctl", "list"], timeout=8)
        return re.findall(r"Controller\s+([0-9A-Fa-f:]{17})", listing or "")

    adapters = list_adapters()
    down_hci = _linux_hci_down()
    if down_hci:
        try_recover_radio()
        time.sleep(0.4)
        down_hci = _linux_hci_down()
        if down_hci:
            names = " ".join(down_hci)
            return False, (f"Bluetooth adapter is down ({names}) — run: "
                           f"sudo bash scripts/eli_bt_reset.sh")

    addrs = _controllers()
    if not addrs and adapters:
        try_recover_radio()
        time.sleep(0.6)
        addrs = _controllers()

    if not addrs:
        return False, recovery_hint(adapters)

    pick = _linux_pick_controller(addrs, adapters)
    ordered = [pick] + [a for a in addrs if a != pick]
    for addr in ordered:
        _sh(["bluetoothctl", "select", addr], timeout=6)
        _sh(["bluetoothctl", "power", "on"], timeout=10)
        _, show = _sh(["bluetoothctl", "show"], timeout=8)
        if "powered: yes" in show.lower():
            return True, addr
    return False, "Bluetooth radio off — " + recovery_hint(adapters)


def _darwin_ensure_radio() -> Tuple[bool, str]:
    if not shutil.which("blueutil"):
        adapters = list_adapters()
        if adapters and adapters[0].powered:
            return True, "default"
        return False, recovery_hint(adapters)
    _, out = _sh(["blueutil", "-p"], timeout=5)
    if out.strip() == "1":
        return True, "default"
    _sh(["blueutil", "-p", "1"], timeout=5)
    _, out2 = _sh(["blueutil", "-p"], timeout=5)
    if out2.strip() == "1":
        return True, "default"
    return False, recovery_hint()


def _windows_ensure_radio() -> Tuple[bool, str]:
    adapters = list_adapters()
    if adapters and any(a.powered for a in adapters):
        return True, adapters[0].id
    rc, out = _powershell(
        "try {"
        "  $r = [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime]"
        "    ::GetRadiosAsync().GetAwaiter().GetResult() |"
        "    Where-Object { $_.Kind -eq 'Bluetooth' };"
        "  foreach ($x in $r) {"
        "    if ($x.State -ne 'On') {"
        "      $x.SetStateAsync('On').GetAwaiter().GetResult() | Out-Null"
        "    }"
        "    Write-Output ($x.Name + '|' + $x.State)"
        "  }"
        "} catch { Write-Output ('ERROR|' + $_.Exception.Message) }",
        timeout=25,
    )
    if rc == 0:
        for line in (out or "").splitlines():
            if "|" not in line:
                continue
            nm, st = line.split("|", 1)
            if st.strip().lower() == "on":
                return True, nm.strip() or "bluetooth"
    return False, recovery_hint(adapters)


def ensure_radio() -> Tuple[bool, str]:
    """Power on and select a working adapter — any OS."""
    kind = platform_kind()
    if kind == "linux":
        return _linux_ensure_radio()
    if kind == "darwin":
        return _darwin_ensure_radio()
    return _windows_ensure_radio()


def radio_status() -> Dict[str, Any]:
    """Snapshot for UI — adapter count, powered state, recovery hint."""
    adapters = list_adapters()
    ok, msg = ensure_radio()
    kind = platform_kind()
    tool = ""
    if kind == "linux":
        tool = "bluetoothctl" if shutil.which("bluetoothctl") else ""
    elif kind == "darwin":
        tool = "blueutil" if shutil.which("blueutil") else "system_profiler"
    else:
        tool = "powershell" if (shutil.which("powershell") or shutil.which("pwsh")) else ""

    has_hardware = bool(adapters)
    radio_down = has_hardware and not ok
    if kind == "linux" and has_hardware and not any(a.bluez for a in adapters):
        radio_down = True

    return {
        "platform": kind,
        "available": bool(tool),
        "tool": tool,
        "powered": ok,
        "controller": msg if ok else "",
        "adapter_count": len(adapters),
        "adapters": [
            {"id": a.id, "name": a.name, "address": a.address,
             "powered": a.powered, "state": a.state, "bus": a.bus, "bluez": a.bluez}
            for a in adapters
        ],
        "radio_down": radio_down,
        "recovery_hint": recovery_hint(adapters) if radio_down or not ok else "",
    }


def _ingest_bt_line(line: str, found: List[dict], seen: Set[str],
                    entry_fn) -> None:
    m = re.search(
        r"(?:\[(?:NEW|CHG)\]\s+)?Device\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*(.*)",
        line.strip(),
    )
    if m:
        addr, rest = m.group(1).upper(), m.group(2).strip()
        if addr in seen:
            if rest and rest != addr.replace(":", "-"):
                for row in found:
                    if row.get("host", "").upper() == addr:
                        row["name"] = rest
            return
        seen.add(addr)
        name = rest if rest and not rest.upper().startswith("RSSI") else ""
        found.append(entry_fn(addr, name))
        return
    # macOS blueutil: "address, name" or "address (name)"
    m2 = re.match(r"^([0-9a-f:]{17})\s*,?\s*(.*)$", line.strip(), re.I)
    if m2:
        addr = m2.group(1).upper()
        if addr in seen:
            return
        seen.add(addr)
        found.append(entry_fn(addr, (m2.group(2) or "").strip()))


def classic_discover(
    timeout: float,
    found: List[dict],
    seen: Set[str],
    errors: List[str],
    entry_fn,
    *,
    scan: bool = True,
) -> None:
    """OS-native BR/EDR / paired-device discovery. Set scan=False for instant cached list."""
    ok, msg = ensure_radio()
    if not ok:
        errors.append(f"Bluetooth radio unavailable — {msg}")
        # Still try to list cached/paired devices where the OS allows it.

    kind = platform_kind()
    if kind == "linux":
        _linux_classic_discover(timeout, found, seen, errors, entry_fn, ok, scan=scan)
    elif kind == "darwin":
        _darwin_classic_discover(timeout, found, seen, errors, entry_fn)
    else:
        _windows_classic_discover(timeout, found, seen, errors, entry_fn)


def _linux_classic_discover(
    timeout: float,
    found: List[dict],
    seen: Set[str],
    errors: List[str],
    entry_fn,
    radio_ok: bool,
    *,
    scan: bool = True,
) -> None:
    if not shutil.which("bluetoothctl"):
        errors.append("bluetooth: bluetoothctl not found (install bluez)")
        return

    def _ingest(text: str) -> None:
        for line in re.sub(r"\x1b\[[0-9;]*m", "", text or "").splitlines():
            _ingest_bt_line(line, found, seen, entry_fn)

    try:
        r = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True, text=True, timeout=8,
        )
        _ingest(r.stdout or "")
    except Exception as e:
        errors.append(f"bluetooth devices list: {e}")

    if radio_ok and scan:
        secs = max(4, min(int(timeout) + 2, 15))
        try:
            r = subprocess.run(
                ["bluetoothctl", "--timeout", str(secs), "scan", "on"],
                capture_output=True, text=True, timeout=secs + 8,
            )
            _ingest((r.stdout or "") + (r.stderr or ""))
        except Exception as e:
            errors.append(f"bluetooth classic scan: {e}")
        finally:
            ensure_radio()


def _darwin_classic_discover(
    timeout: float,
    found: List[dict],
    seen: Set[str],
    errors: List[str],
    entry_fn,
) -> None:
    if shutil.which("blueutil"):
        _, paired = _sh(["blueutil", "--paired"], timeout=10)
        for line in (paired or "").splitlines():
            parts = line.strip().split(",")
            if parts:
                addr = parts[0].strip().upper()
                name = parts[1].strip() if len(parts) > 1 else ""
                if _MAC_RE.match(addr) and addr not in seen:
                    seen.add(addr)
                    found.append(entry_fn(addr, name))
        secs = max(3, min(int(timeout), 12))
        _, inquiry = _sh(["blueutil", "--inquiry", str(secs)], timeout=secs + 8)
        for line in (inquiry or "").splitlines():
            _ingest_bt_line(line, found, seen, entry_fn)
    else:
        _, sp = _sh(["system_profiler", "SPBluetoothDataType"], timeout=20)
        for line in (sp or "").splitlines():
            m = re.search(r"Address:\s*([0-9A-Fa-f:]{17})", line)
            if m:
                addr = m.group(1).upper()
                if addr not in seen:
                    seen.add(addr)
                    found.append(entry_fn(addr, ""))


def _windows_classic_discover(
    timeout: float,
    found: List[dict],
    seen: Set[str],
    errors: List[str],
    entry_fn,
) -> None:
    rc, out = _powershell(
        "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |"
        " Where-Object { $_.Status -eq 'OK' -and "
        "$_.FriendlyName -notmatch 'Radio|Enumerator|Gatt|Server|Service|Protocol|Profile|LE$' } |"
        " ForEach-Object {"
        "  $id = $_.InstanceId;"
        "  $mac = '';"
        "  if ($id -match '([0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2})') {"
        "    $mac = $matches[1] -replace '_', ':'"
        "  }"
        "  Write-Output ($mac + '|' + $_.FriendlyName)"
        " }",
        timeout=max(12, min(int(timeout) + 8, 25)),
    )
    if rc != 0:
        errors.append(f"windows bluetooth scan: {(out or '')[:200]}")
        return
    for line in (out or "").splitlines():
        if "|" not in line:
            continue
        addr, name = line.split("|", 1)
        addr, name = addr.strip().upper(), name.strip()
        if not _MAC_RE.match(addr):
            continue
        if addr in seen:
            continue
        seen.add(addr)
        found.append(entry_fn(addr, name))


def device_info(addr: str) -> Dict[str, Any]:
    """Best-effort device metadata for classification."""
    addr = (addr or "").strip().upper()
    info: Dict[str, Any] = {"uuids": []}
    if not addr:
        return info

    kind = platform_kind()
    if kind == "linux" and shutil.which("bluetoothctl"):
        _, out = _sh(["bluetoothctl", "info", addr], timeout=10)
        for line in (out or "").splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip().lower().replace(" ", "_")
            if key == "uuid":
                info["uuids"].append(v.strip())
            else:
                info[key] = v.strip()
        return info

    if kind == "darwin" and shutil.which("blueutil"):
        _, out = _sh(["blueutil", "--info", addr], timeout=10)
        if out.strip():
            info["name"] = out.strip().splitlines()[0][:80]
        return info

    if kind == "windows":
        rc, out = _powershell(
            f"$d = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |"
            f" Where-Object {{ $_.InstanceId -match '{addr.replace(':', '_')}' }} |"
            f" Select-Object -First 1 -ExpandProperty FriendlyName;"
            f"if ($d) {{ Write-Output $d }}",
            timeout=12,
        )
        if rc == 0 and out.strip():
            info["name"] = out.strip()
        return info

    return info


def set_adapter_alias(name: str) -> Dict[str, Any]:
    """Set hub friendly name on pairing screens — OS-specific."""
    name = (name or "").strip()
    kind = platform_kind()
    if kind == "darwin":
        return {"ok": False, "alias": name,
                "note": "macOS uses System Settings → General → Sharing → Computer Name"}
    if kind == "windows":
        return {"ok": False, "alias": name,
                "note": "Windows uses Settings → Bluetooth & devices → Rename this PC"}
    if not shutil.which("bluetoothctl"):
        return {"ok": False, "alias": name, "error": "bluetoothctl not found"}
    ensure_radio()
    _, show = _sh(["bluetoothctl", "show"], timeout=8)
    for line in show.splitlines():
        if line.strip().lower().startswith("alias:"):
            if line.split(":", 1)[1].strip() == name:
                return {"ok": True, "alias": name, "already_set": True}
            break
    try:
        r = subprocess.run(
            ["bluetoothctl"],
            input=f"power on\nsystem-alias {name}\nquit\n",
            capture_output=True, text=True, timeout=12,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return {"ok": True, "alias": name, "output": out.strip()[:200]}
    except Exception as e:
        return {"ok": False, "alias": name, "error": str(e)}


def list_known_devices() -> List[Dict[str, Any]]:
    """Instant device list from the OS cache (no scan) — paired, connected, and known."""
    rows: List[Dict[str, Any]] = []
    kind = platform_kind()

    def _row(addr: str, name: str = "") -> Dict[str, Any]:
        return {
            "host": addr.upper(),
            "port": None,
            "name": (name or "").strip() or f"Bluetooth device ({addr})",
            "kind": "bluetooth",
            "label": "Bluetooth device",
            "control": "bluetooth",
            "driver": "bluetooth",
            "transport": "bluetooth",
            "source": "known",
        }

    if kind == "linux" and shutil.which("bluetoothctl"):
        _, listing = _sh(["bluetoothctl", "devices"], timeout=8)
        for line in re.sub(r"\x1b\[[0-9;]*m", "", listing or "").splitlines():
            m = re.search(r"Device\s+([0-9A-Fa-f:]{17})\s*(.*)", line.strip())
            if not m:
                continue
            addr, name = m.group(1).upper(), m.group(2).strip()
            info = device_info(addr)
            row = _row(addr, name or info.get("name") or info.get("alias") or "")
            row["paired"] = str(info.get("paired", "")).lower() == "yes"
            row["connected"] = str(info.get("connected", "")).lower() == "yes"
            rows.append(row)
        return rows

    if kind == "darwin" and shutil.which("blueutil"):
        _, paired = _sh(["blueutil", "--paired"], timeout=8)
        for line in (paired or "").splitlines():
            parts = line.strip().split(",")
            if parts and _MAC_RE.match(parts[0].strip()):
                rows.append(_row(parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""))
        return rows

    if kind == "windows":
        seen: Set[str] = set()
        rc, out = _powershell(
            "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |"
            " Where-Object { $_.Status -eq 'OK' -and "
            "$_.FriendlyName -notmatch 'Radio|Enumerator|Gatt|Server|Service|Protocol|Profile|LE$' } |"
            " ForEach-Object {"
            "  $id = $_.InstanceId;"
            "  $mac = '';"
            "  if ($id -match '([0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2}_[0-9A-Fa-f]{2})') {"
            "    $mac = $matches[1] -replace '_', ':'"
            "  }"
            "  if ($mac) { Write-Output ($mac + '|' + $_.FriendlyName) }"
            " }",
            timeout=12,
        )
        if rc == 0:
            for line in (out or "").splitlines():
                if "|" not in line:
                    continue
                addr, name = line.split("|", 1)
                addr = addr.strip().upper()
                if _MAC_RE.match(addr) and addr not in seen:
                    seen.add(addr)
                    rows.append(_row(addr, name.strip()))
        return rows

    return rows


def connected_devices() -> List[Dict[str, Any]]:
    """Devices the OS reports as connected right now."""
    return [d for d in list_known_devices() if d.get("connected")]


def device_known(addr: str) -> bool:
    """Whether the OS already lists this device (paired / cached)."""
    addr = (addr or "").strip().upper()
    if not addr:
        return False
    kind = platform_kind()
    if kind == "linux" and shutil.which("bluetoothctl"):
        _, listing = _sh(["bluetoothctl", "devices"], timeout=8)
        return addr in (listing or "").upper()
    if kind == "darwin" and shutil.which("blueutil"):
        _, paired = _sh(["blueutil", "--paired"], timeout=8)
        return addr in (paired or "").upper()
    if kind == "windows":
        rc, out = _powershell(
            f"Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |"
            f" Where-Object {{ $_.InstanceId -match '{addr.replace(':', '_')}' }} |"
            f" Measure-Object | Select-Object -ExpandProperty Count",
            timeout=10,
        )
        return rc == 0 and out.strip() not in ("", "0")
    return False


def _norm_bt_name(name: str) -> str:
    n = (name or "").strip().lower()
    if not n or n.startswith("bluetooth device ("):
        return ""
    return n


def _linux_list_devices() -> List[Dict[str, str]]:
    """Return [{address, name}] from bluetoothctl's device cache."""
    rows: List[Dict[str, str]] = []
    if not shutil.which("bluetoothctl"):
        return rows
    _, listing = _sh(["bluetoothctl", "devices"], timeout=8)
    for line in re.sub(r"\x1b\[[0-9;]*m", "", listing or "").splitlines():
        m = re.search(r"Device\s+([0-9A-Fa-f:]{17})\s*(.*)", line.strip())
        if not m:
            continue
        rows.append({"address": m.group(1).upper(), "name": (m.group(2) or "").strip()})
    return rows


def _name_matches(want: str, candidate: str) -> bool:
    """Loose name match — handles BLE vs classic MAC showing the same product name."""
    want = _norm_bt_name(want)
    cand = _norm_bt_name(candidate)
    if not want or not cand:
        return False
    if want == cand:
        return True
    if want in cand or cand in want:
        return True
    # Strip common suffixes/prefixes from scan noise
    for strip in ("-bt", " bt", " series", " headphones", " headset"):
        if want.replace(strip, "") == cand.replace(strip, ""):
            return True
    return False


def _linux_active_scan(secs: int) -> None:
    """Run a classic BR/EDR scan so pairing-mode devices enter the BlueZ cache."""
    secs = max(6, min(int(secs), 25))
    if not shutil.which("bluetoothctl"):
        return
    try:
        subprocess.run(
            ["bluetoothctl", "--timeout", str(secs), "scan", "on"],
            capture_output=True, text=True, timeout=secs + 10,
        )
    except Exception as e:
        log.debug("bluetooth scan: %s", e)
    finally:
        _sh(["bluetoothctl", "scan", "off"], timeout=6)
        ensure_radio()


def _address_quality_score(addr: str) -> int:
    """Rank MACs when one product name maps to both BLE ads and classic BR/EDR."""
    info = device_info(addr)
    score = 0
    icon = (info.get("icon") or "").lower()
    if any(x in icon for x in ("headset", "headphones", "audio")):
        score += 120
    uuids = [u.lower() for u in info.get("uuids") or []]
    if any("110b" in u or "110a" in u or "audio sink" in u or "audio source" in u for u in uuids):
        score += 80
    if info.get("class"):
        score += 40
    if str(info.get("paired", "")).lower() == "yes":
        score += 50
    if str(info.get("connected", "")).lower() == "yes":
        score += 40
    mfg = info.get("manufacturerdata.key") or info.get("manufacturerdata_key")
    if mfg and not icon and not info.get("class"):
        score -= 50
    if not icon and not info.get("class") and len(uuids) <= 2:
        score -= 20
    return score


def _best_address_for_name(name: str) -> str:
    """Pick the classic/audio MAC when BlueZ lists the same name twice."""
    want = _norm_bt_name(name)
    if not want:
        return ""
    addrs = [d["address"] for d in _linux_list_devices() if _name_matches(want, d["name"])]
    if not addrs:
        return ""
    if len(addrs) == 1:
        return addrs[0]
    return max(addrs, key=_address_quality_score)


def _prefer_address(addr: str = "", name: str = "") -> str:
    """Resolve stale BLE MACs to the best BlueZ address for pairing/audio."""
    by_name = _best_address_for_name(name)
    if by_name:
        return by_name
    return (addr or "").strip().upper()


def resolve_device(addr: str = "", name: str = "", timeout: float = 20.0) -> Dict[str, Any]:
    """Active scan and resolve a device — fixes stale BLE MACs by matching friendly name."""
    start = time.time()
    addr_u = _prefer_address(addr, name)
    want_name = _norm_bt_name(name)

    # Resolve by friendly name from the OS cache first (fixes BLE vs classic MAC mismatch).
    if want_name and platform_kind() == "linux" and shutil.which("bluetoothctl"):
        best = _best_address_for_name(name)
        if best:
            return {
                "address": best,
                "found": True,
                "phase": "resolved_by_name",
                "duration_s": round(time.time() - start, 1),
            }

    ok, radio_msg = ensure_radio()
    if not ok:
        return {
            "address": addr_u,
            "found": False,
            "phase": "radio_off",
            "radio_error": radio_msg,
            "duration_s": round(time.time() - start, 1),
        }

    if addr_u and device_known(addr_u):
        info = device_info(addr_u)
        if not want_name or _name_matches(want_name, str(info.get("name") or info.get("alias") or "")):
            return {
                "address": addr_u,
                "found": True,
                "phase": "cached",
                "duration_s": round(time.time() - start, 1),
            }

    kind = platform_kind()
    secs = max(8, min(int(timeout), 25))

    if kind == "linux" and shutil.which("bluetoothctl"):
        _linux_active_scan(secs)
        devices = _linux_list_devices()
        if addr_u and any(d["address"] == addr_u for d in devices):
            return {
                "address": addr_u,
                "found": True,
                "phase": "scanned_mac",
                "duration_s": round(time.time() - start, 1),
            }
        if want_name:
            best = _best_address_for_name(name)
            if best:
                return {
                    "address": best,
                    "found": True,
                    "phase": "resolved_by_name",
                    "duration_s": round(time.time() - start, 1),
                }
        return {
            "address": addr_u,
            "found": bool(addr_u and device_known(addr_u)),
            "phase": "not_in_scan",
            "duration_s": round(time.time() - start, 1),
        }

    if kind == "darwin" and shutil.which("blueutil"):
        _sh(["blueutil", "--inquiry", str(secs)], timeout=secs + 8)
        if addr_u and device_known(addr_u):
            return {"address": addr_u, "found": True, "phase": "scanned_mac",
                    "duration_s": round(time.time() - start, 1)}
        return {"address": addr_u, "found": device_known(addr_u), "phase": "darwin_scan",
                "duration_s": round(time.time() - start, 1)}

    if kind == "windows":
        _windows_classic_discover(secs, [], set(), [], lambda a, n: {"host": a, "name": n})
        return {"address": addr_u, "found": device_known(addr_u), "phase": "windows_scan",
                "duration_s": round(time.time() - start, 1)}

    return {"address": addr_u, "found": False, "phase": "unsupported",
            "duration_s": round(time.time() - start, 1)}


def _linux_device_dbus_path(addr: str) -> str:
    """Standard BlueZ D-Bus path for a device on the default controller."""
    addr_u = (addr or "").strip().upper().replace(":", "_")
    _, listing = _sh(["bluetoothctl", "list"], timeout=6)
    hci = "hci0"
    for line in (listing or "").splitlines():
        if line.strip().lower().startswith("controller"):
            # Controller AA:BB:CC:DD:EE:FF hostname [default]
            break
    return f"/org/bluez/{hci}/dev_{addr_u}"


def _linux_dbus_call(path: str, interface: str, method: str,
                      extra: Optional[List[str]] = None,
                      timeout: float = 45.0) -> Tuple[bool, str]:
    """Invoke a BlueZ D-Bus method (no bluetoothctl agent required)."""
    args = ["dbus-send", "--system", "--dest=org.bluez", "--print-reply",
            path, f"{interface}.{method}"]
    if extra:
        args.extend(extra)
    rc, out = _sh(args, timeout=timeout)
    low = (out or "").lower()
    ok = rc == 0 and "error" not in low.split("method return")[0]
    return ok, out


def _linux_dbus_set_trusted(path: str) -> Tuple[bool, str]:
    return _linux_dbus_call(
        path, "org.freedesktop.DBus.Properties", "Set",
        extra=["string:org.bluez.Device1", "string:Trusted", "variant:boolean:true"],
        timeout=20.0,
    )


def _linux_dbus_bt_steps(addr: str, steps: List[str]) -> Tuple[bool, str, str]:
    """Pair/trust/connect via D-Bus — works when a desktop agent is already registered."""
    path = _linux_device_dbus_path(addr)
    outputs: List[str] = []
    for step in steps:
        if step == "pair":
            ok, out = _linux_dbus_call(path, "org.bluez.Device1", "Pair", timeout=60.0)
            outputs.append(out)
            if not ok and "already exists" not in out.lower():
                return False, "\n".join(outputs), "pair_failed"
        elif step == "trust":
            ok, out = _linux_dbus_set_trusted(path)
            outputs.append(out)
        elif step == "connect":
            ok, out = _linux_dbus_call(path, "org.bluez.Device1", "Connect", timeout=45.0)
            outputs.append(out)
            if not ok and "already connected" not in out.lower():
                return False, "\n".join(outputs), "connect_failed"
    combined = "\n".join(outputs)
    info = device_info(addr)
    paired = str(info.get("paired", "")).lower() == "yes"
    connected = str(info.get("connected", "")).lower() == "yes"
    if paired or connected:
        return True, combined, "paired"
    if "pair" in steps and not paired:
        return False, combined, "pair_failed"
    return True, combined, "connected"


def _device_paired(addr: str) -> bool:
    info = device_info(addr)
    return str(info.get("paired", "")).lower() == "yes"


def _parse_bt_output(out: str) -> bool:
    low = (out or "").lower()
    if "authentication failed" in low or "org.bluez.error" in low:
        return False
    if "failed to register agent" in low or "no agent is registered" in low:
        return False
    if ("failed to pair" in low or "failed to connect" in low) and "connection successful" not in low:
        return False
    if "page timeout" in low or "connectionattemptfailed" in low:
        return False
    if "connection successful" in low or "already connected" in low:
        return True
    if "pairing successful" in low or "paired: yes" in low or "connected: yes" in low:
        return True
    return False


def _resolve_addr_after_scan(addr: str, name: str = "") -> str:
    """Pick the BlueZ classic MAC after scan — fixes stale BLE random addresses."""
    return _prefer_address(addr, name)


def linux_pair_session(
    addr: str,
    steps: List[str],
    *,
    agent: str = "NoInputNoOutput",
    alias: str = "",
    name: str = "",
    scan_secs: int = 15,
    timeout: float = 95.0,
) -> Tuple[bool, str, str]:
    """Scan, then pair/trust/connect — one session so headphones in pairing mode are found."""
    addr = (addr or "").strip().upper()
    if not addr and not (name or "").strip():
        return False, "no device address", "no_address"
    if not shutil.which("bluetoothctl"):
        return False, "bluetoothctl not found", "no_tool"

    ok, radio_msg = ensure_radio()
    if not ok:
        return False, radio_msg or "Bluetooth radio off", "radio_off"

    alias = (alias or "Eli · Home").strip() or "Eli · Home"
    scan_secs = max(6, min(int(scan_secs), 25))

    # Discover device while it is in pairing mode
    _linux_active_scan(scan_secs)
    addr = _resolve_addr_after_scan(addr, name)
    phase = "scan_done"

    # Prefer D-Bus (uses the system/desktop pairing agent — no agent registration conflict).
    dbus_ok, dbus_out, dbus_phase = _linux_dbus_bt_steps(addr, steps)
    if dbus_ok or _device_paired(addr):
        return True, dbus_out, "paired"
    if dbus_phase == "pair_failed" and "page timeout" in dbus_out.lower():
        return False, (dbus_out + "\nDevice not responding — keep headphones in pairing mode "
                       "(LED flashing) and tap Pair again"), "not_found"

    # Fallback: bluetoothctl script without agent (desktop agent handles pairing prompts).
    script = "\n".join([
        "power on",
        "pairable on",
        "discoverable off",
        f"system-alias {alias}",
        *[f"{step} {addr}" for step in steps],
        "scan off",
        "quit",
        "",
    ])
    try:
        r = subprocess.run(
            ["bluetoothctl"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        ok = _parse_bt_output(out) or _device_paired(addr)
        if ok:
            phase = "paired"
        elif "failed to pair" in out.lower():
            phase = "pair_failed"
        elif "failed to connect" in out.lower():
            phase = "connect_failed"
        else:
            phase = "pair_attempted"
        return ok, out, phase
    except subprocess.TimeoutExpired:
        return False, f"bluetoothctl timed out after {int(timeout)}s", "timeout"
    except Exception as e:
        return False, str(e), "error"


def wait_for_device(addr: str, timeout: float = 18.0, name: str = "") -> bool:
    """Scan until the device appears (headphones must be in pairing mode)."""
    res = resolve_device(addr, name, timeout=timeout)
    return bool(res.get("found"))


def windows_bt_action(addr: str, action: str) -> Tuple[bool, str]:
    """Pair / connect / disconnect via WinRT (Windows 10+)."""
    addr = (addr or "").strip().upper()
    mac_u = addr.replace(":", "")
    ps_action = {"pair": "Pair", "connect": "Connect", "disconnect": "Disconnect",
                 "trust": "Connect"}.get(action, "Connect")
    script = (
        f"$addr = [uint64]('0x{mac_u}');"
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
        "$bt = [Windows.Devices.Bluetooth.BluetoothDevice,Windows.Devices.Bluetooth,"
        "ContentType=WindowsRuntime];"
        "try {"
        f"  $dev = $bt::FromBluetoothAddressAsync($addr).GetAwaiter().GetResult();"
        "  if (-not $dev) { Write-Output 'FAIL|device not found'; exit 1 }"
        f"  if ('{ps_action}' -eq 'Pair') {{"
        "    $r = $dev.DeviceInformation.Pairing.PairAsync().GetAwaiter().GetResult();"
        "    Write-Output ($r.Status.ToString())"
        f"  }} elseif ('{ps_action}' -eq 'Disconnect') {{"
        "    $dev.ConnectionStatus; Write-Output 'Disconnected'"
        "  } else {"
        "    Write-Output ($dev.ConnectionStatus.ToString())"
        "  }"
        "} catch { Write-Output ('FAIL|' + $_.Exception.Message) }"
    )
    rc, out = _powershell(script, timeout=45)
    low = (out or "").lower()
    ok = rc == 0 and "fail" not in low and "unreachable" not in low
    return ok, out.strip()[:400]


def tools_for_platform() -> Dict[str, Any]:
    """What this OS can use — for driver_status / dashboard."""
    kind = platform_kind()
    if kind == "linux":
        return {
            "platform": kind,
            "control": bool(shutil.which("bluetoothctl")),
            "audio": bool(shutil.which("pactl") or shutil.which("wpctl")),
            "ble": True,
            "detail": "bluetoothctl + pactl/wpctl",
        }
    if kind == "darwin":
        return {
            "platform": kind,
            "control": bool(shutil.which("blueutil")),
            "audio": bool(shutil.which("SwitchAudioSource")),
            "ble": True,
            "detail": "blueutil + SwitchAudioSource (brew)",
        }
    return {
        "platform": kind,
        "control": bool(shutil.which("powershell") or shutil.which("pwsh")),
        "audio": bool(shutil.which("powershell") or shutil.which("pwsh")),
        "ble": True,
        "detail": "PowerShell + bleak",
    }
