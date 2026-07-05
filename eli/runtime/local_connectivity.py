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


_A2DP_PROFILES = ("a2dp-sink", "a2dp")


def is_handsfree_sink(sink_id: str, description: str = "") -> bool:
    """True for HSP/HFP phone-quality sinks — not what we want for music."""
    blob = f"{sink_id} {description}".lower()
    return any(k in blob for k in (
        "headset-head-unit", "headset_head_unit", "handsfree", "hands-free",
        "hsp", "hfp", ".sco", "headset_head",
    ))


def _pactl_sink_descriptions() -> Dict[str, str]:
    descriptions: Dict[str, str] = {}
    _, detail = _sh(["pactl", "list", "sinks"], timeout=12)
    cur_name = ""
    for line in detail.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            cur_name = s.split(":", 1)[-1].strip()
        elif s.startswith("Description:") and cur_name:
            descriptions[cur_name] = s.split(":", 1)[-1].strip()
    return descriptions


def activate_bt_a2dp(addr: str) -> bool:
    """Switch a BlueZ card to high-quality A2DP playback — never HSP handsfree."""
    if not shutil.which("pactl"):
        return False
    token = addr.replace(":", "_").upper()
    _, cards = _sh(["pactl", "list", "short", "cards"], timeout=10)
    for line in cards.splitlines():
        if token not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        card_id = parts[1]
        # Turn off handsfree so PipeWire/BlueZ stops routing phone-quality audio.
        _sh(["pactl", "set-card-profile", card_id, "headset-head-unit", "off"], timeout=6)
        for profile in _A2DP_PROFILES:
            rc, _ = _sh(["pactl", "set-card-profile", card_id, profile], timeout=10)
            if rc == 0:
                return True
        return False
    return False


def find_bt_a2dp_sink(addr: str, name: str = "") -> Optional[str]:
    """Pick the music-quality sink for a BT MAC, not handsfree/HSP."""
    token = addr.replace(":", "_").upper()
    nm = (name or "").strip().lower()
    descriptions = _pactl_sink_descriptions()
    a2dp: List[str] = []
    fallback: List[str] = []
    _, listing = _sh(["pactl", "list", "short", "sinks"], timeout=10)
    for line in listing.splitlines():
        if token not in line.upper() or "bluez" not in line.lower():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        sid = parts[1]
        desc = descriptions.get(sid, "")
        if is_handsfree_sink(sid, desc):
            fallback.append(sid)
        else:
            a2dp.append(sid)
    if a2dp:
        if nm:
            for sid in a2dp:
                if nm in descriptions.get(sid, "").lower():
                    return sid
        return a2dp[0]
    if nm:
        for sid in fallback:
            if nm in descriptions.get(sid, "").lower():
                return sid
    return fallback[0] if fallback else None


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
    try:
        from eli.runtime import bt_platform as bp
        from eli.runtime.device_drivers import BluetoothDriver
        rs = bp.radio_status()
        BluetoothDriver.ensure_adapter_alias()
        return {
            "available": rs.get("available", False),
            "tool": rs.get("tool", ""),
            "powered": rs.get("powered", False),
            "radio_down": rs.get("radio_down", False),
            "recovery_hint": rs.get("recovery_hint", ""),
            "adapter_count": rs.get("adapter_count", 0),
            "platform": rs.get("platform", bp.platform_kind()),
            "adapter_name": BluetoothDriver.resolve_adapter_alias(),
            "connected_devices": bp.connected_devices(),
        }
    except Exception:
        return {
            "available": False,
            "tool": "",
            "powered": False,
            "radio_down": False,
            "recovery_hint": "",
            "adapter_name": bp.adapter_display_alias(),
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


def load_audio_aliases() -> Dict[str, str]:
    """User-chosen names for outputs: {sink_id: 'Kitchen speaker'}."""
    try:
        from eli.core.runtime_settings import load_settings
        raw = (load_settings() or {}).get("audio_output_aliases") or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v).strip() for k, v in raw.items() if str(v).strip()}
    except Exception:
        return {}


def save_audio_alias(sink_id: str, name: str) -> Dict[str, Any]:
    """Set or clear a friendly name for one audio output."""
    sink_id = (sink_id or "").strip()
    name = (name or "").strip()
    if not sink_id:
        return {"ok": False, "error": "sink id required"}
    try:
        from eli.core.runtime_settings import load_settings, save_settings
        settings = load_settings() or {}
        aliases = dict(settings.get("audio_output_aliases") or {})
        if name:
            aliases[sink_id] = name[:64]
        else:
            aliases.pop(sink_id, None)
        settings["audio_output_aliases"] = aliases
        save_settings(settings)
        return {"ok": True, "sink": sink_id, "alias": name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _enrich_sinks_with_aliases(result: Dict[str, Any]) -> Dict[str, Any]:
    """Attach alias, display_name, device_number for UI + voice."""
    if not result.get("ok"):
        return result
    aliases = load_audio_aliases()
    sinks = result.get("sinks") or []
    for i, s in enumerate(sinks):
        sid = str(s.get("id") or "")
        alias = aliases.get(sid, "")
        os_name = str(s.get("name") or sid)
        s["device_number"] = i + 1
        s["alias"] = alias
        s["os_name"] = os_name
        s["display_name"] = alias or os_name
        s["voice_names"] = _voice_names_for_sink(alias, os_name, i + 1)
    result["aliases"] = aliases
    return result


def _voice_names_for_sink(alias: str, os_name: str, device_number: int) -> List[str]:
    names: List[str] = []
    if alias:
        names.append(alias.lower())
        for part in re.split(r"[\s/,-]+", alias.lower()):
            if len(part) > 2:
                names.append(part)
    if os_name:
        names.append(os_name.lower())
    names.append(f"device {device_number}")
    names.append(f"device{device_number}")
    # dedupe preserve order
    seen: set = set()
    out: List[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_audio_sink(query: str) -> Optional[Dict[str, Any]]:
    """Match a spoken/UI label to a sink — alias, device N, or OS name."""
    q = (query or "").strip().lower()
    if not q:
        return None
    listed = list_audio_outputs()
    sinks = listed.get("sinks") or []

    m = re.match(r"^(?:device|output|speaker)\s*#?\s*(\d+)$", q)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(sinks):
            return sinks[n - 1]

    for s in sinks:
        for vn in s.get("voice_names") or []:
            if q == vn or q in vn or vn in q:
                return s
        if q == str(s.get("id") or "").lower():
            return s
        if q == str(s.get("alias") or "").lower():
            return s
        if q == str(s.get("name") or "").lower():
            return s
        if q == str(s.get("display_name") or "").lower():
            return s

    # Partial match on alias/display (e.g. "kitchen" → "kitchen speaker")
    for s in sinks:
        for field in ("alias", "display_name", "name"):
            val = str(s.get(field) or "").lower()
            if val and (q in val or val in q):
                return s
    return None


def route_audio_by_name(name: str) -> Dict[str, Any]:
    """Voice/UI: switch default output by friendly name, device number, or OS label."""
    sink = resolve_audio_sink(name)
    if not sink:
        return {"ok": False, "error": f"No speaker called '{name}' — name it in Overview → Now playing"}
    res = set_default_audio(str(sink.get("id") or ""))
    if res.get("ok"):
        label = sink.get("alias") or sink.get("display_name") or name
        res["alias"] = label
        res["display_name"] = label
    return res


def refresh_bluetooth_audio() -> None:
    """Best-effort: wake A2DP profiles on connected BT devices so sinks appear in pactl."""
    if not shutil.which("pactl") or not shutil.which("bluetoothctl"):
        return
    try:
        from eli.runtime import bt_platform as bp
        from eli.runtime.device_drivers import BluetoothDriver as BT
    except Exception:
        return
    bp.ensure_radio()
    _, cards = _sh(["pactl", "list", "short", "cards"], timeout=10)
    for dev in bp.list_known_devices():
        if not dev.get("connected"):
            continue
        addr = str(dev.get("host") or "").strip()
        if not addr:
            continue
        try:
            info = BT._bt_device_info(addr)
            meta = BT.classify_bt_device(info, str(dev.get("name") or ""))
            if not meta.get("audio_capable"):
                continue
        except Exception:
            continue
        token = addr.replace(":", "_").upper()
        for line in cards.splitlines():
            if token not in line.upper():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            card_id = parts[1]
            activate_bt_a2dp(addr)
            break


def list_audio_outputs(*, refresh: bool = False) -> Dict[str, Any]:
    if refresh:
        refresh_bluetooth_audio()
    if shutil.which("pactl"):
        return _enrich_sinks_with_aliases(_list_sinks_pactl())
    if shutil.which("wpctl"):
        return _enrich_sinks_with_aliases(_list_sinks_wpctl())
    if sys.platform == "darwin" and shutil.which("SwitchAudioSource"):
        return _enrich_sinks_with_aliases(_list_sinks_mac())
    if sys.platform.startswith("win"):
        return _enrich_sinks_with_aliases(_list_sinks_windows())
    return {
        "ok": False,
        "error": "No audio router found (install PulseAudio/PipeWire pactl, wpctl, or use OS sound settings)",
        "sinks": [],
    }


def _list_sinks_pactl_raw() -> Dict[str, Any]:
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
    descriptions: Dict[str, str] = {}
    _, detail = _sh(["pactl", "list", "sinks"], timeout=12)
    cur_name = ""
    for line in detail.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            cur_name = s.split(":", 1)[-1].strip()
        elif s.startswith("Description:") and cur_name:
            descriptions[cur_name] = s.split(":", 1)[-1].strip()
    _, out = _sh(["pactl", "list", "short", "sinks"], timeout=10)
    sinks: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = re.split(r"\s+", line.strip(), maxsplit=2)
        if len(parts) < 2:
            continue
        sid = parts[1]
        desc = descriptions.get(sid) or sid
        if is_handsfree_sink(sid, desc):
            desc = f"{desc} (phone/handsfree — use Connect for music on headphones)"
        sinks.append({
            "id": sid,
            "name": desc,
            "is_default": sid == default,
            "kind": "bluetooth" if "bluez" in sid.lower() else "local",
            "profile": "handsfree" if is_handsfree_sink(sid, desc) else (
                "a2dp" if "bluez" in sid.lower() else "local"
            ),
        })
    return {"ok": True, "sinks": sinks, "default": default, "backend": "pactl"}


def _list_sinks_pactl() -> Dict[str, Any]:
    return _list_sinks_pactl_raw()


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


def _list_sinks_windows() -> Dict[str, Any]:
    from eli.runtime import bt_platform as bp
    rc, out = bp.powershell(
        "Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue |"
        " ForEach-Object { $_.FriendlyName }",
        timeout=15,
    )
    if rc != 0:
        return {"ok": False, "error": (out or "audio enumeration failed")[:200], "sinks": []}
    sinks = []
    for i, name in enumerate([ln.strip() for ln in (out or "").splitlines() if ln.strip()]):
        sinks.append({
            "id": name,
            "name": name,
            "is_default": i == 0,
            "kind": "bluetooth" if re.search(r"bluetooth|headphone|headset", name, re.I) else "local",
        })
    default = sinks[0]["id"] if sinks else ""
    return {"ok": bool(sinks), "sinks": sinks, "default": default, "backend": "windows-pnp"}


def set_default_audio(sink: str) -> Dict[str, Any]:
    sink = (sink or "").strip()
    if not sink:
        return {"ok": False, "error": "sink id or name required"}
    resolved = resolve_audio_sink(sink)
    if resolved:
        sink = str(resolved.get("id") or sink)
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
    if sys.platform.startswith("win"):
        return {
            "ok": True,
            "sink": sink,
            "note": "On Windows, set the default output in Settings → System → Sound",
            "backend": "windows-manual",
        }
    return {"ok": False, "error": "no audio routing tool available"}
