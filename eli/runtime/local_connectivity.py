"""Local-only WiFi and audio routing — sovereign stack, no cloud.

Uses OS tools only: nmcli/netsh on WiFi, pactl/wpctl for audio sinks.
Every branch degrades to a clear message; nothing here phones home.
"""
from __future__ import annotations

import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple


def _sh(args: List[str], timeout: float = 25.0) -> Tuple[int, str]:
    import subprocess

    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "tool-not-found"
    except Exception as e:
        return 1, str(e)


def connectivity_status() -> Dict[str, Any]:
    """Snapshot for the Home dashboard — WiFi, default audio sink, Bluetooth stack."""
    return {
        "ok": True,
        "local_only": True,
        "wifi": wifi_status(),
        "audio": audio_status(),
        "bluetooth": bluetooth_status(),
    }


def bluetooth_status() -> Dict[str, Any]:
    if sys.platform == "darwin":
        tool = "blueutil" if shutil.which("blueutil") else None
    elif sys.platform.startswith("win"):
        tool = None  # roadmap
    else:
        tool = "bluetoothctl" if shutil.which("bluetoothctl") else None
    powered = False
    adapter_name = ""
    if tool == "bluetoothctl":
        _, out = _sh(["bluetoothctl", "show"], timeout=8)
        powered = "powered: yes" in out.lower()
        for line in out.splitlines():
            low = line.strip().lower()
            if low.startswith("alias:"):
                adapter_name = line.split(":", 1)[1].strip()
                break
        try:
            from eli.runtime.device_drivers import BluetoothDriver
            BluetoothDriver.ensure_adapter_alias()
            adapter_name = BluetoothDriver.ADAPTER_ALIAS
        except Exception:
            adapter_name = adapter_name or "Eli"
    return {
        "available": bool(tool),
        "tool": tool or "",
        "powered": powered,
        "adapter_name": adapter_name or "Eli",
    }


def wifi_status() -> Dict[str, Any]:
    if sys.platform == "darwin":
        return _wifi_status_mac()
    if sys.platform.startswith("win"):
        return _wifi_status_win()
    return _wifi_status_linux()


def _wifi_status_linux() -> Dict[str, Any]:
    if not shutil.which("nmcli"):
        return {
            "available": False,
            "connected": False,
            "ssid": "",
            "signal": 0,
            "error": "WiFi control needs NetworkManager (nmcli). Use your system settings, or install network-manager.",
        }
    _, radio = _sh(["nmcli", "-t", "-f", "WIFI", "radio"], timeout=8)
    wifi_on = "enabled" in radio.lower() or ":yes" in radio.lower()
    rc, out = _sh(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"], timeout=12)
    ssid, signal, connected = "", 0, False
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0].strip().lower() in ("yes", "1"):
            ssid = parts[1].strip()
            try:
                signal = int(parts[2].strip() or 0)
            except ValueError:
                signal = 0
            connected = bool(ssid)
            break
    return {
        "available": True,
        "wifi_on": wifi_on,
        "connected": connected,
        "ssid": ssid,
        "signal": signal,
        "platform": "linux",
    }


def _wifi_status_win() -> Dict[str, Any]:
    if not shutil.which("netsh"):
        return {"available": False, "connected": False, "ssid": "", "error": "netsh unavailable"}
    _, out = _sh(["netsh", "wlan", "show", "interfaces"], timeout=12)
    ssid_m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M | re.I)
    state_m = re.search(r"^\s*State\s*:\s*(.+)$", out, re.M | re.I)
    ssid = (ssid_m.group(1).strip() if ssid_m else "")
    state = (state_m.group(1).strip().lower() if state_m else "")
    connected = "connected" in state
    sig_m = re.search(r"^\s*Signal\s*:\s*(\d+)", out, re.M | re.I)
    signal = int(sig_m.group(1)) if sig_m else 0
    return {
        "available": True,
        "connected": connected,
        "ssid": ssid if connected else "",
        "signal": signal,
        "platform": "windows",
    }


def _wifi_status_mac() -> Dict[str, Any]:
    # Best-effort without extra brew tools — scan still works via networksetup elsewhere.
    tool = "networksetup" if shutil.which("networksetup") else None
    ssid = ""
    if tool:
        _, out = _sh(["networksetup", "-getairportnetwork", "en0"], timeout=8)
        if "not associated" not in out.lower() and "you are not" not in out.lower():
            m = re.search(r":\s*(.+)$", out.strip())
            if m:
                ssid = m.group(1).strip()
    return {
        "available": bool(tool),
        "connected": bool(ssid),
        "ssid": ssid,
        "signal": 0,
        "platform": "darwin",
        "note": "Full WiFi join on macOS may need System Settings — ELI can still route audio and LAN devices.",
    }


def wifi_scan() -> Dict[str, Any]:
    if sys.platform == "darwin":
        return _wifi_scan_mac()
    if sys.platform.startswith("win"):
        return _wifi_scan_win()
    return _wifi_scan_linux()


def _wifi_scan_linux() -> Dict[str, Any]:
    if not shutil.which("nmcli"):
        return {"ok": False, "error": "nmcli not found — install NetworkManager", "networks": []}
    _sh(["nmcli", "dev", "wifi", "rescan"], timeout=10)
    rc, out = _sh(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "dev", "wifi", "list"], timeout=20)
    if rc != 0 and "tool-not-found" in out:
        return {"ok": False, "error": "nmcli not found", "networks": []}
    seen: Dict[str, Dict[str, Any]] = {}
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        ssid = parts[0].strip()
        if not ssid:
            continue
        try:
            signal = int(parts[1].strip() or 0)
        except ValueError:
            signal = 0
        sec = parts[2].strip()
        in_use = parts[3].strip().lower() in ("yes", "1", "*")
        prev = seen.get(ssid)
        if not prev or signal > prev.get("signal", 0):
            seen[ssid] = {"ssid": ssid, "signal": signal, "security": sec, "in_use": in_use}
    nets = sorted(seen.values(), key=lambda x: (-x.get("signal", 0), x.get("ssid", "")))
    return {"ok": True, "networks": nets, "platform": "linux"}


def _wifi_scan_win() -> Dict[str, Any]:
    if not shutil.which("netsh"):
        return {"ok": False, "error": "netsh unavailable", "networks": []}
    rc, out = _sh(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=20)
    if rc != 0:
        return {"ok": False, "error": out.strip()[:200] or "wlan scan failed", "networks": []}
    nets: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {}
    for line in out.splitlines():
        m = re.match(r"^\s*SSID\s+\d+\s*:\s*(.+)$", line)
        if m:
            if cur.get("ssid"):
                nets.append(cur)
            cur = {"ssid": m.group(1).strip(), "signal": 0, "security": "", "in_use": False}
            continue
        sm = re.match(r"^\s*Signal\s*:\s*(\d+)%", line)
        if sm and cur:
            cur["signal"] = int(sm.group(1))
        am = re.match(r"^\s*Authentication\s*:\s*(.+)$", line)
        if am and cur:
            cur["security"] = am.group(1).strip()
    if cur.get("ssid"):
        nets.append(cur)
    st = wifi_status()
    if st.get("ssid"):
        for n in nets:
            if n["ssid"] == st["ssid"]:
                n["in_use"] = True
    nets.sort(key=lambda x: (-x.get("signal", 0), x.get("ssid", "")))
    return {"ok": True, "networks": nets, "platform": "windows"}


def _wifi_scan_mac() -> Dict[str, Any]:
    # airport is deprecated; return guidance rather than failing silently.
    airport = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    if not shutil.which(airport) and not Path_exists(airport):
        return {
            "ok": False,
            "error": "WiFi scan on macOS needs System Settings or airport CLI — ELI stays local; use the menu bar to join.",
            "networks": [],
            "platform": "darwin",
        }
    rc, out = _sh([airport, "-s"], timeout=20)
    if rc != 0:
        return {"ok": False, "error": out.strip()[:200] or "scan failed", "networks": []}
    nets: List[Dict[str, Any]] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        ssid = parts[0]
        try:
            signal = int(parts[1].replace("%", ""))
        except ValueError:
            signal = 0
        nets.append({"ssid": ssid, "signal": signal, "security": "", "in_use": False})
    return {"ok": True, "networks": nets, "platform": "darwin"}


def Path_exists(p: str) -> bool:
    from pathlib import Path

    return Path(p).exists()


def wifi_connect(ssid: str, password: str = "") -> Dict[str, Any]:
    ssid = (ssid or "").strip()
    if not ssid:
        return {"ok": False, "error": "SSID required"}
    if sys.platform == "darwin":
        return _wifi_connect_mac(ssid, password)
    if sys.platform.startswith("win"):
        return _wifi_connect_win(ssid, password)
    return _wifi_connect_linux(ssid, password)


def _wifi_connect_linux(ssid: str, password: str) -> Dict[str, Any]:
    if not shutil.which("nmcli"):
        return {"ok": False, "error": "nmcli not found — use your system WiFi settings"}
    args = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    rc, out = _sh(args, timeout=35)
    low = out.lower()
    ok = rc == 0 or "successfully activated" in low or "connection successfully" in low
    return {"ok": ok, "ssid": ssid, "output": out.strip()[:400], "platform": "linux"}


def _wifi_connect_win(ssid: str, password: str) -> Dict[str, Any]:
    if not shutil.which("netsh"):
        return {"ok": False, "error": "netsh unavailable"}
    # Profile may already exist from a prior join.
    if password:
        _sh(["netsh", "wlan", "add", "profile", f"name={ssid}", f"ssid={ssid}",
             "key=clear", f"keyMaterial={password}"], timeout=15)
    rc, out = _sh(["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"], timeout=25)
    ok = rc == 0 or "completed successfully" in out.lower()
    return {"ok": ok, "ssid": ssid, "output": out.strip()[:400], "platform": "windows"}


def _wifi_connect_mac(ssid: str, password: str) -> Dict[str, Any]:
    if not shutil.which("networksetup"):
        return {"ok": False, "error": "networksetup not found"}
    iface = _mac_wifi_iface()
    if not iface:
        return {"ok": False, "error": "no WiFi interface found — join via System Settings"}
    args = ["networksetup", "-setairportnetwork", iface, ssid]
    if password:
        args.append(password)
    rc, out = _sh(args, timeout=30)
    return {"ok": rc == 0, "ssid": ssid, "output": out.strip()[:400], "platform": "darwin"}


def _mac_wifi_iface() -> str:
    _, out = _sh(["networksetup", "-listallhardwareports"], timeout=10)
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if "wi-fi" in line.lower() or "airport" in line.lower():
            for j in range(i + 1, min(i + 4, len(lines))):
                m = re.match(r"^\s*Device:\s*(\S+)", lines[j])
                if m:
                    return m.group(1)
    return "en0"


def audio_status() -> Dict[str, Any]:
    sinks = list_audio_outputs()
    default = sinks.get("default") or ""
    if not default:
        for s in sinks.get("sinks") or []:
            if s.get("is_default"):
                default = s.get("id") or s.get("name") or ""
                break
    return {
        "available": sinks.get("ok", False),
        "default_sink": default,
        "sink_count": len(sinks.get("sinks") or []),
        "error": sinks.get("error"),
    }


def list_audio_outputs() -> Dict[str, Any]:
    if shutil.which("pactl"):
        return _list_sinks_pactl()
    if shutil.which("wpctl"):
        return _list_sinks_wpctl()
    if sys.platform == "darwin" and shutil.which("SwitchAudioSource"):
        return _list_sinks_mac()
    return {
        "ok": False,
        "error": "No audio router found (install PulseAudio/PipeWire pactl, or wpctl)",
        "sinks": [],
    }


def _list_sinks_pactl() -> Dict[str, Any]:
    if shutil.which("pactl"):
        _, def_out = _sh(["pactl", "get-default-sink"], timeout=8)
        default = def_out.strip().splitlines()[0].strip() if def_out.strip() else ""
    else:
        default = ""
    if not default:
        _, info = _sh(["pactl", "info"], timeout=8)
        for line in info.splitlines():
            if "default sink:" in line.lower():
                default = line.split(":", 1)[-1].strip()
                break
    _, out = _sh(["pactl", "list", "short", "sinks"], timeout=10)
    sinks: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = re.split(r"\s+", line.strip(), maxsplit=2)
        if len(parts) < 2:
            continue
        sid = parts[1]
        desc = sid
        sinks.append({
            "id": sid,
            "name": desc,
            "is_default": sid == default,
            "kind": "bluetooth" if "bluez" in sid.lower() else "local",
        })
    return {"ok": True, "sinks": sinks, "default": default, "backend": "pactl"}


def _list_sinks_wpctl() -> Dict[str, Any]:
    _, out = _sh(["wpctl", "status"], timeout=10)
    sinks: List[Dict[str, Any]] = []
    default = ""
    in_sinks = False
    for line in out.splitlines():
        if "Sinks:" in line:
            in_sinks = True
            continue
        if in_sinks and re.match(r"^\s*\d+\.", line) is None and line.strip() and not line.startswith("\t"):
            if "Sources:" in line:
                break
        m = re.match(r"^\s*(\d+)\.\s+(.+?)(?:\s+\[(.+)\])?$", line)
        if m and in_sinks:
            sid = m.group(1)
            name = m.group(2).strip()
            mark = m.group(3) or ""
            is_def = "default" in mark.lower()
            if is_def:
                default = name
            sinks.append({
                "id": sid,
                "name": name,
                "is_default": is_def,
                "kind": "bluetooth" if "bluez" in name.lower() else "local",
            })
    return {"ok": bool(sinks), "sinks": sinks, "default": default, "backend": "wpctl"}


def _list_sinks_mac() -> Dict[str, Any]:
    _, out = _sh(["SwitchAudioSource", "-a", "-t", "output"], timeout=10)
    _, cur = _sh(["SwitchAudioSource", "-c", "-t", "output"], timeout=8)
    current = cur.strip()
    sinks = [{"id": n.strip(), "name": n.strip(), "is_default": n.strip() == current, "kind": "local"}
             for n in out.splitlines() if n.strip()]
    return {"ok": bool(sinks), "sinks": sinks, "default": current, "backend": "switchaudio-osx"}


def set_default_audio(sink: str) -> Dict[str, Any]:
    sink = (sink or "").strip()
    if not sink:
        return {"ok": False, "error": "sink id or name required"}
    if shutil.which("pactl"):
        rc, out = _sh(["pactl", "set-default-sink", sink], timeout=10)
        if rc == 0:
            _, inputs = _sh(["pactl", "list", "short", "sink-inputs"], timeout=8)
            for line in inputs.splitlines():
                parts = line.split()
                if parts:
                    _sh(["pactl", "move-sink-input", parts[0], sink], timeout=6)
        return {"ok": rc == 0, "sink": sink, "output": out.strip()[:200], "backend": "pactl"}
    if shutil.which("wpctl"):
        # sink may be numeric id from wpctl status
        target = sink if sink.isdigit() else None
        if not target:
            listed = _list_sinks_wpctl()
            for s in listed.get("sinks") or []:
                if s.get("id") == sink or s.get("name") == sink:
                    target = s.get("id")
                    break
        if not target:
            return {"ok": False, "error": f"sink not found: {sink}"}
        rc, out = _sh(["wpctl", "set-default", target], timeout=10)
        return {"ok": rc == 0, "sink": sink, "output": out.strip()[:200], "backend": "wpctl"}
    if sys.platform == "darwin" and shutil.which("SwitchAudioSource"):
        rc, out = _sh(["SwitchAudioSource", "-s", sink, "-t", "output"], timeout=10)
        return {"ok": rc == 0, "sink": sink, "output": out.strip()[:200], "backend": "switchaudio-osx"}
    return {"ok": False, "error": "no audio routing tool available"}
