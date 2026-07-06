"""ELI home mesh — tiered brains with LAN failover.

Primary (Tier-2) PC runs full cognition. Secondary / tertiary nodes watch heartbeats
and take over smart-home control when the primary drops — no cloud, all local HTTP
on your LAN.

Roles:
  primary   — main brain; publishes heartbeats, owns cognition when healthy
  secondary — backup brain (Tier-3); promotes to acting when primary is down
  tertiary  — third backup; promotes only if primary + secondary are down
  reflex    — room node / edge only; no brain election
  off       — mesh disabled on this install

State lives beside the device registry under artifacts/devices/.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ROLES = {"primary", "secondary", "tertiary", "reflex", "off"}
_ROLE_PRIORITY = {"primary": 3, "secondary": 2, "tertiary": 1, "reflex": 0, "off": -1}
_DEFAULT = {
    "enabled": False,
    "role": "off",
    "node_id": "",
    "node_name": "",
    "primary_url": "",
    "peers": [],
    "heartbeat_interval_sec": 5.0,
    "failover_after_sec": 18.0,
    "auto_takeover": True,
}
_lock = threading.Lock()
_watch_started = False
_watch_thread: Optional[threading.Thread] = None
_runtime: Dict[str, Any] = {
    "mode": "off",
    "acting_brain": "",
    "primary_alive": False,
    "last_primary_seen": 0.0,
    "last_failover": 0.0,
    "failover_reason": "",
    "peers_seen": {},
}


def _mesh_dir() -> Path:
    try:
        from eli.core.paths import get_paths
        p = Path(get_paths().artifacts_dir) / "devices"
    except Exception:
        p = Path("artifacts") / "devices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _config_path() -> Path:
    return _mesh_dir() / "mesh.json"


def _state_path() -> Path:
    return _mesh_dir() / "mesh_state.json"


def _local_node_name() -> str:
    try:
        from eli.core.runtime_settings import load_settings
        s = load_settings() or {}
        zone = str(s.get("hub_zone") or "").strip() or "Home"
        return f"Eli · {zone}"
    except Exception:
        return socket.gethostname()


def _ensure_node_id(cfg: Dict[str, Any]) -> str:
    nid = str(cfg.get("node_id") or "").strip()
    if nid:
        return nid
    nid = f"eli-{uuid.uuid4().hex[:12]}"
    cfg["node_id"] = nid
    return nid


def load_config() -> Dict[str, Any]:
    p = _config_path()
    cfg = dict(_DEFAULT)
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            log.debug("home_mesh: load_config failed", exc_info=True)
    _ensure_node_id(cfg)
    if not str(cfg.get("node_name") or "").strip():
        cfg["node_name"] = _local_node_name()
    role = str(cfg.get("role") or "off").lower()
    cfg["role"] = role if role in _ROLES else "off"
    return cfg


def save_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(cfg or {})
    _ensure_node_id(cfg)
    role = str(cfg.get("role") or "off").lower()
    cfg["role"] = role if role in _ROLES else "off"
    peers = []
    for row in cfg.get("peers") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip().rstrip("/")
        if not url:
            continue
        peers.append({
            "id": str(row.get("id") or "").strip(),
            "name": str(row.get("name") or "").strip(),
            "url": url,
            "role": str(row.get("role") or "secondary").lower(),
        })
    cfg["peers"] = peers
    try:
        tmp = _config_path().with_suffix(".json.part")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_config_path())
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "config": cfg}


def _load_state() -> Dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        tmp = _state_path().with_suffix(".json.part")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_state_path())
    except Exception:
        log.debug("home_mesh: save_state failed", exc_info=True)


def _http_ping(url: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Reach another ELI node's mesh ping endpoint."""
    base = (url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "error": "no url"}
    ping_url = f"{base}/v1/home/mesh/ping"
    headers = {"Accept": "application/json"}
    token = (os.environ.get("ELI_API_TOKEN") or os.environ.get("ELI_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(ping_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode(errors="ignore")
            data = json.loads(body) if body.strip() else {}
            if isinstance(data, dict):
                data.setdefault("ok", True)
                return data
            return {"ok": True}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _device_count() -> int:
    try:
        from eli.runtime.device_server import get_server
        st = get_server().home_state()
        return int(st.get("device_count") or 0)
    except Exception:
        return 0


def ping_payload() -> Dict[str, Any]:
    cfg = load_config()
    with _lock:
        rt = dict(_runtime)
    return {
        "ok": True,
        "node_id": cfg.get("node_id"),
        "node_name": cfg.get("node_name"),
        "role": cfg.get("role"),
        "mode": rt.get("mode") or "off",
        "acting_brain": rt.get("acting_brain") or "",
        "ts": time.time(),
        "device_count": _device_count(),
        "hostname": socket.gethostname(),
    }


def record_peer_heartbeat(peer_id: str, payload: Dict[str, Any]) -> None:
    if not peer_id:
        return
    with _lock:
        _runtime["peers_seen"][peer_id] = {
            "ts": time.time(),
            "role": payload.get("role"),
            "mode": payload.get("mode"),
            "node_name": payload.get("node_name"),
        }


def _pick_acting_backup(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Highest-priority local backup role wins (secondary before tertiary)."""
    role = str(cfg.get("role") or "off")
    if role in ("secondary", "tertiary") and cfg.get("enabled"):
        return {"node_id": cfg.get("node_id"), "role": role, "local": True}
    best = None
    best_pri = -1
    for peer in cfg.get("peers") or []:
        pr = str(peer.get("role") or "secondary")
        pri = _ROLE_PRIORITY.get(pr, 0)
        if pri > best_pri:
            best_pri = pri
            best = peer
    return best


def _set_mode(mode: str, acting: str = "", reason: str = "") -> None:
    with _lock:
        prev = _runtime.get("mode")
        _runtime["mode"] = mode
        _runtime["acting_brain"] = acting
        if reason and mode != prev:
            _runtime["last_failover"] = time.time()
            _runtime["failover_reason"] = reason
    state = _load_state()
    state.update({
        "mode": mode,
        "acting_brain": acting,
        "updated": time.time(),
        "failover_reason": reason,
    })
    _save_state(state)
    if mode in ("acting_secondary", "acting_tertiary", "cognition"):
        try:
            from eli.runtime.device_server import get_server
            get_server().maybe_auto_connect()
        except Exception:
            pass


def _watch_primary(cfg: Dict[str, Any]) -> None:
    role = str(cfg.get("role") or "off")
    if not cfg.get("enabled") or role in ("off", "reflex", "primary"):
        if role == "primary" and cfg.get("enabled"):
            with _lock:
                _runtime["primary_alive"] = True
                _runtime["acting_brain"] = str(cfg.get("node_id") or "")
            _set_mode("cognition", str(cfg.get("node_id") or ""), "")
        return

    primary_url = str(cfg.get("primary_url") or "").strip().rstrip("/")
    if not primary_url:
        for peer in cfg.get("peers") or []:
            if str(peer.get("role") or "") == "primary":
                primary_url = str(peer.get("url") or "").strip().rstrip("/")
                break
    if not primary_url:
        with _lock:
            _runtime["primary_alive"] = False
        return

    res = _http_ping(primary_url, timeout=4.0)
    alive = bool(res.get("ok"))
    now = time.time()
    with _lock:
        if alive:
            _runtime["primary_alive"] = True
            _runtime["last_primary_seen"] = now
            if str(cfg.get("role")) in ("secondary", "tertiary"):
                _runtime["mode"] = "standby"
                _runtime["acting_brain"] = str(res.get("node_id") or res.get("acting_brain") or "")
        else:
            _runtime["primary_alive"] = False

    if alive:
        if str(cfg.get("role")) in ("secondary", "tertiary"):
            _set_mode("standby", str(res.get("node_id") or ""), "")
        return

    last_seen = float(_runtime.get("last_primary_seen") or 0)
    gap = now - last_seen if last_seen else now
    threshold = float(cfg.get("failover_after_sec") or 18.0)
    if last_seen and gap < threshold:
        return
    if not cfg.get("auto_takeover"):
        _set_mode("reflex", "", "primary offline — auto takeover disabled")
        return

    my_role = str(cfg.get("role") or "")
    if my_role == "secondary":
        _set_mode("acting_secondary", str(cfg.get("node_id") or ""), "primary unreachable — secondary took over")
        log.warning("home_mesh: secondary brain acting — primary %s down", primary_url)
    elif my_role == "tertiary":
        sec_alive = False
        for peer in cfg.get("peers") or []:
            if str(peer.get("role") or "") != "secondary":
                continue
            sec = _http_ping(str(peer.get("url") or ""), timeout=3.0)
            if sec.get("ok") and str(sec.get("mode") or "") in ("acting_secondary", "cognition", "standby"):
                sec_alive = True
                break
        if not sec_alive:
            _set_mode("acting_tertiary", str(cfg.get("node_id") or ""), "primary + secondary down — tertiary took over")
            log.warning("home_mesh: tertiary brain acting")


def _watch_loop() -> None:
    while True:
        try:
            cfg = load_config()
            if cfg.get("enabled"):
                if str(cfg.get("role")) == "primary":
                    with _lock:
                        _runtime["primary_alive"] = True
                        _runtime["last_primary_seen"] = time.time()
                        _runtime["acting_brain"] = str(cfg.get("node_id") or "")
                    _set_mode("cognition", str(cfg.get("node_id") or ""), "")
                else:
                    _watch_primary(cfg)
        except Exception:
            log.debug("home_mesh: watch loop error", exc_info=True)
        interval = float(load_config().get("heartbeat_interval_sec") or 5.0)
        time.sleep(max(2.0, interval))


def ensure_watchdog() -> None:
    global _watch_started, _watch_thread
    with _lock:
        if _watch_started:
            return
        _watch_started = True
    t = threading.Thread(target=_watch_loop, name="eli-home-mesh", daemon=True)
    _watch_thread = t
    t.start()


def mesh_status() -> Dict[str, Any]:
    cfg = load_config()
    with _lock:
        rt = dict(_runtime)
    persisted = _load_state()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "config": {
            "node_id": cfg.get("node_id"),
            "node_name": cfg.get("node_name"),
            "role": cfg.get("role"),
            "primary_url": cfg.get("primary_url"),
            "peers": cfg.get("peers") or [],
            "heartbeat_interval_sec": cfg.get("heartbeat_interval_sec"),
            "failover_after_sec": cfg.get("failover_after_sec"),
            "auto_takeover": cfg.get("auto_takeover"),
        },
        "runtime": {
            "mode": rt.get("mode") or ("cognition" if cfg.get("role") == "primary" else "off"),
            "acting_brain": rt.get("acting_brain") or persisted.get("acting_brain") or "",
            "primary_alive": bool(rt.get("primary_alive")),
            "last_primary_seen": rt.get("last_primary_seen") or persisted.get("last_primary_seen"),
            "last_failover": rt.get("last_failover") or persisted.get("updated"),
            "failover_reason": rt.get("failover_reason") or persisted.get("failover_reason") or "",
            "peers_seen": rt.get("peers_seen") or {},
        },
        "node": ping_payload(),
    }


def update_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    for key in ("enabled", "role", "node_name", "primary_url", "auto_takeover"):
        if key in patch:
            cfg[key] = patch[key]
    for key in ("heartbeat_interval_sec", "failover_after_sec"):
        if key in patch and patch[key] is not None:
            try:
                cfg[key] = float(patch[key])
            except Exception:
                pass
    if "peers" in patch and isinstance(patch["peers"], list):
        cfg["peers"] = patch["peers"]
    res = save_config(cfg)
    if res.get("ok") and cfg.get("enabled"):
        ensure_watchdog()
    return res


def manual_takeover() -> Dict[str, Any]:
    cfg = load_config()
    role = str(cfg.get("role") or "off")
    if role not in ("secondary", "tertiary"):
        return {"ok": False, "error": "only secondary/tertiary nodes can take over"}
    mode = "acting_secondary" if role == "secondary" else "acting_tertiary"
    _set_mode(mode, str(cfg.get("node_id") or ""), "manual takeover")
    return {"ok": True, "mode": mode, "acting_brain": cfg.get("node_id")}


def mesh_context_line() -> str:
    st = mesh_status()
    if not st.get("enabled"):
        return ""
    mode = (st.get("runtime") or {}).get("mode") or "off"
    if mode == "cognition":
        return "Home mesh: primary brain online."
    if mode == "standby":
        return "Home mesh: standby — watching primary."
    if mode == "acting_secondary":
        return "Home mesh: secondary brain active (primary offline)."
    if mode == "acting_tertiary":
        return "Home mesh: tertiary brain active (primary offline)."
    if mode == "reflex":
        return "Home mesh: reflex mode — local devices only."
    return ""
