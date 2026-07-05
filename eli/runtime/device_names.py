"""User-chosen device names — stable keys for voice control across hardware/OS."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_MAC_IN_SINK = re.compile(r"([0-9A-Fa-f]{2}[_:]){5}[0-9A-Fa-f]{2}")


def _mac_from_token(token: str) -> str:
    t = (token or "").strip().upper().replace("_", ":")
    if re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", t):
        return t
    return ""


def mac_from_sink_id(sink_id: str) -> str:
    """Extract Bluetooth MAC from a PipeWire sink id (stable across reconnects)."""
    sid = (sink_id or "").upper()
    m = _MAC_IN_SINK.search(sid)
    if not m:
        return ""
    return _mac_from_token(m.group(0))


def bt_key(addr: str) -> str:
    mac = _mac_from_token(addr)
    return f"bt:{mac}" if mac else ""


def sink_key(sink_id: str) -> str:
    mac = mac_from_sink_id(sink_id)
    if mac:
        return f"sink:{mac}"
    sid = (sink_id or "").strip()
    return f"sinkid:{sid}" if sid else ""


def registry_key(device_id: str) -> str:
    did = (device_id or "").strip()
    return f"dev:{did}" if did else ""


def load_custom_names() -> Dict[str, str]:
    """All user labels: {stable_key: 'Kitchen speaker'}."""
    names: Dict[str, str] = {}
    try:
        from eli.core.runtime_settings import load_settings
        settings = load_settings() or {}
        raw = settings.get("device_custom_names") or {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if str(v).strip():
                    names[str(k)] = str(v).strip()[:64]
        # Legacy audio aliases keyed by sink id — merge + MAC keys.
        for sid, alias in (settings.get("audio_output_aliases") or {}).items():
            if not str(alias).strip():
                continue
            names[sink_key(str(sid))] = str(alias).strip()[:64]
            mac = mac_from_sink_id(str(sid))
            if mac:
                names[f"sink:{mac}"] = str(alias).strip()[:64]
    except Exception:
        pass
    return names


def save_custom_name(key: str, name: str) -> Dict[str, Any]:
    key = (key or "").strip()
    name = (name or "").strip()
    if not key:
        return {"ok": False, "error": "device key required"}
    try:
        from eli.core.runtime_settings import load_settings, save_settings
        settings = load_settings() or {}
        names = dict(settings.get("device_custom_names") or {})
        if name:
            names[key] = name[:64]
        else:
            names.pop(key, None)
        settings["device_custom_names"] = names
        # Keep audio_output_aliases in sync for sink:* keys (voice router compat).
        if key.startswith("sink:") or key.startswith("sinkid:"):
            aliases = dict(settings.get("audio_output_aliases") or {})
            if key.startswith("sink:"):
                mac = key[5:]
                for sid, _ in list(aliases.items()):
                    if mac_from_sink_id(sid) == mac:
                        if name:
                            aliases[sid] = name[:64]
                        else:
                            aliases.pop(sid, None)
            elif key.startswith("sinkid:"):
                sid = key[7:]
                if name:
                    aliases[sid] = name[:64]
                else:
                    aliases.pop(sid, None)
            settings["audio_output_aliases"] = aliases
        save_settings(settings)
        return {"ok": True, "key": key, "name": name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def lookup_name(key: str, default: str = "") -> str:
    if not key:
        return default
    return load_custom_names().get(key) or default


def apply_name(row: Dict[str, Any], key: str, os_name: str = "") -> None:
    """Attach custom_name, display_name, voice_names to a device/sink row."""
    custom = lookup_name(key, "")
    os_name = os_name or str(row.get("name") or row.get("os_name") or row.get("id") or "")
    row["custom_name"] = custom
    row["name_key"] = key
    row["os_name"] = os_name
    row["display_name"] = custom or os_name
    row["alias"] = custom or row.get("alias") or ""
    if custom:
        row["voice_names"] = _voice_tokens(custom, os_name, row.get("device_number"))


def _voice_tokens(custom: str, os_name: str, device_number: Any = None) -> List[str]:
    names: List[str] = []
    if custom:
        names.append(custom.lower())
        for part in re.split(r"[\s/,-]+", custom.lower()):
            if len(part) > 2:
                names.append(part)
    if os_name:
        names.append(str(os_name).lower())
    if device_number:
        n = int(device_number)
        names.append(f"device {n}")
        names.append(f"device{n}")
    seen: set = set()
    out: List[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def list_nameable_devices() -> List[Dict[str, Any]]:
    """Everything the user can label — registry, speakers, Bluetooth."""
    names = load_custom_names()
    rows: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(key: str, kind: str, os_name: str, extra: Optional[Dict[str, Any]] = None) -> None:
        if not key or key in seen:
            return
        seen.add(key)
        row: Dict[str, Any] = {"key": key, "kind": kind, "os_name": os_name or key}
        if extra:
            row.update(extra)
        apply_name(row, key, os_name)
        row["saved_name"] = names.get(key, "")
        rows.append(row)

    try:
        from eli.runtime.device_server import get_server
        for d in get_server().list_devices():
            _add(registry_key(d.get("id", "")), d.get("driver") or "device",
                 str(d.get("name") or d.get("id") or ""), {"device_id": d.get("id")})
    except Exception:
        pass

    try:
        from eli.runtime.local_connectivity import list_audio_outputs
        listed = list_audio_outputs(refresh=False)
        for i, s in enumerate(listed.get("sinks") or []):
            sid = str(s.get("id") or "")
            os_name = str(s.get("name") or sid)
            _add(sink_key(sid), s.get("kind") or "audio", os_name,
                 {"sink": sid, "device_number": i + 1, "is_default": s.get("is_default")})
    except Exception:
        pass

    try:
        from eli.runtime import bt_platform as bp
        for d in bp.list_known_devices():
            addr = str(d.get("host") or "")
            if not addr:
                continue
            k = bt_key(addr)
            if k:
                _add(k, "bluetooth", str(d.get("name") or addr), {"address": addr})
    except Exception:
        pass

    rows.sort(key=lambda r: (0 if r.get("kind") == "audio" else 1, r.get("kind", ""), r.get("display_name", "")))
    return rows


def match_bluetooth_name(name_l: str, devices: List[dict]) -> Optional[dict]:
    """Resolve spoken name against OS names and user custom labels."""
    if not name_l:
        return None
    names = load_custom_names()
    _GENERIC = {"headphones", "headphone", "headset", "earbuds", "speaker", "speakers",
                "bluetooth", "device", "it", "music"}
    if name_l not in _GENERIC:
        for d in devices:
            addr = str(d.get("host") or d.get("address") or "")
            k = bt_key(addr)
            custom = names.get(k, "").lower() if k else ""
            osn = str(d.get("name") or "").lower()
            if name_l in custom or name_l in osn:
                return d
            if custom and any(w in custom for w in name_l.split() if w not in _GENERIC):
                return d
            words = [w for w in name_l.split() if w not in _GENERIC]
            if words and any(w in osn for w in words):
                return d
    return None
