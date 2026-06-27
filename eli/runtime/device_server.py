"""ELI's own device server — original, MQTT-first. No Home Assistant.

ELI keeps its own device registry and talks to devices directly over MQTT (the open
DIY-IoT lingua franca: ESPHome / Tasmota / Zigbee2MQTT, or anything that speaks MQTT).
Two ways devices appear:
  • manual — register a device with its command/state topics, or
  • discovery — if you set a discovery prefix, ELI auto-populates from the standard
    retained MQTT discovery messages those firmwares already publish.

Design notes:
  • The broker is a LOCAL-network service; ELI registers its host with netguard so the
    offline-by-default socket guard permits *that host only* (nothing else opens up).
  • Fully degrades: with no broker configured or paho-mqtt absent, every call returns
    ``{"ok": False, ...}`` with a helpful message — ELI never crashes offline.
  • State arrives on a background MQTT thread; the registry is lock-guarded.

This module is ELI-native; it does not import or require Home Assistant.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_DEVICE_TYPES = {"light", "switch", "fan", "sensor", "climate", "media", "cover", "outlet"}


def _registry_path() -> Path:
    try:
        from eli.core.paths import get_paths
        p = Path(get_paths().artifacts_dir) / "devices"
    except Exception:
        p = Path("artifacts") / "devices"
    p.mkdir(parents=True, exist_ok=True)
    return p / "registry.json"


def _cfg() -> Dict[str, Any]:
    try:
        from eli.core import config
        return {
            "host": (config.get("mqtt_host") or "").strip(),
            "port": int(config.get("mqtt_port") or 1883),
            "username": config.get("mqtt_username") or "",
            "password": config.get("mqtt_password") or "",
            "discovery_prefix": (config.get("mqtt_discovery_prefix") or "").strip(),
            "tls": bool(config.get("mqtt_tls") or False),
        }
    except Exception:
        return {"host": "", "port": 1883, "username": "", "password": "",
                "discovery_prefix": "", "tls": False}


class DeviceServer:
    """ELI-native MQTT device hub: registry + connection + control."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._client = None
        self._connected = False
        self._last_error = ""
        self._load()

    # ── Persistence ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            p = _registry_path()
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._devices = {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            log.debug("device_server: registry load failed", exc_info=True)

    def _save(self) -> None:
        try:
            tmp = _registry_path().with_suffix(".json.part")
            tmp.write_text(json.dumps(self._devices, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(_registry_path())
        except Exception:
            log.debug("device_server: registry save failed", exc_info=True)

    # ── Registry ────────────────────────────────────────────────────────────
    def register_device(self, *, device_id: str, name: str = "", dtype: str = "switch",
                        command_topic: str = "", state_topic: str = "",
                        attrs: Optional[dict] = None) -> Dict[str, Any]:
        did = (device_id or "").strip()
        if not did:
            return {"ok": False, "error": "device_id required"}
        dtype = dtype if dtype in _DEVICE_TYPES else "switch"
        with self._lock:
            dev = self._devices.get(did, {})
            dev.update({
                "id": did,
                "name": name or dev.get("name") or did,
                "type": dtype,
                "command_topic": command_topic or dev.get("command_topic", ""),
                "state_topic": state_topic or dev.get("state_topic", ""),
                "attrs": {**(dev.get("attrs") or {}), **(attrs or {})},
                "state": dev.get("state", "unknown"),
                "last_seen": dev.get("last_seen", 0),
            })
            self._devices[did] = dev
            self._save()
        # If already connected, (re)subscribe to its state topic.
        if self._connected and dev.get("state_topic"):
            self._subscribe(dev["state_topic"])
        return {"ok": True, "device": dev}

    def remove_device(self, device_id: str) -> Dict[str, Any]:
        with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]
                self._save()
                return {"ok": True}
        return {"ok": False, "error": "unknown device"}

    def list_devices(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(d) for d in self._devices.values()]

    # ── Connection ──────────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        cfg = _cfg()
        with self._lock:
            n = len(self._devices)
        return {
            "configured": bool(cfg["host"]),
            "connected": self._connected,
            "broker": (f"{cfg['host']}:{cfg['port']}" if cfg["host"] else ""),
            "discovery": bool(cfg["discovery_prefix"]),
            "device_count": n,
            "error": self._last_error or None,
        }

    def configure(self, **kw) -> Dict[str, Any]:
        """Persist broker settings (host/port/username/password/discovery_prefix/tls)."""
        try:
            from eli.core import config
            for key in ("mqtt_host", "mqtt_port", "mqtt_username", "mqtt_password",
                        "mqtt_discovery_prefix", "mqtt_tls"):
                short = key[len("mqtt_"):]
                if short in kw and kw[short] is not None:
                    config.set(key, kw[short])
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "status": self.status()}

    def connect(self) -> Dict[str, Any]:
        cfg = _cfg()
        if not cfg["host"]:
            return {"ok": False, "error": "no MQTT broker configured (set mqtt_host)"}
        try:
            import paho.mqtt.client as mqtt
        except Exception:
            return {"ok": False, "error": "paho-mqtt not installed (pip install paho-mqtt)"}

        # Permit the broker host (and its resolved IP) through netguard — that host
        # ONLY; the offline-by-default policy is otherwise unchanged.
        try:
            from eli.core import netguard
            hosts = [cfg["host"]]
            try:
                import socket as _s
                hosts.append(_s.gethostbyname(cfg["host"]))
            except Exception:
                pass
            netguard.register_local_service(*hosts)
        except Exception:
            log.debug("device_server: netguard registration skipped", exc_info=True)

        try:
            if self._client is not None:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:
                    pass
            # paho 2.x requires a callback API version; fall back to the 1.x signature.
            try:
                client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
            except (AttributeError, TypeError):
                client = mqtt.Client()
            if cfg["username"]:
                client.username_pw_set(cfg["username"], cfg["password"] or None)
            if cfg["tls"]:
                client.tls_set()
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect
            self._client = client
            client.connect_async(cfg["host"], int(cfg["port"]), keepalive=45)
            client.loop_start()
            self._last_error = ""
            return {"ok": True, "status": self.status()}
        except Exception as e:
            self._last_error = str(e)
            return {"ok": False, "error": str(e)}

    def disconnect(self) -> Dict[str, Any]:
        try:
            if self._client is not None:
                self._client.loop_stop()
                self._client.disconnect()
        except Exception:
            pass
        self._connected = False
        return {"ok": True}

    def _subscribe(self, topic: str) -> None:
        try:
            if self._client and topic:
                self._client.subscribe(topic)
        except Exception:
            log.debug("device_server: subscribe failed %s", topic, exc_info=True)

    # ── MQTT callbacks (background thread) ───────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc, *args) -> None:
        self._connected = (rc == 0)
        if rc != 0:
            self._last_error = f"broker refused connection (rc={rc})"
            return
        cfg = _cfg()
        # Subscribe to every known device's state topic.
        with self._lock:
            topics = [d.get("state_topic") for d in self._devices.values() if d.get("state_topic")]
        for t in topics:
            self._subscribe(t)
        # Optional auto-discovery over the standard retained MQTT discovery messages.
        if cfg["discovery_prefix"]:
            self._subscribe(cfg["discovery_prefix"].rstrip("/") + "/#")

    def _on_disconnect(self, *args) -> None:
        self._connected = False

    def _on_message(self, client, userdata, msg) -> None:
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8", "replace") if msg.payload else ""
            cfg = _cfg()
            prefix = cfg["discovery_prefix"].rstrip("/")
            if prefix and topic.startswith(prefix + "/") and topic.endswith("/config"):
                self._handle_discovery(topic, payload)
                return
            # State update for a known device.
            with self._lock:
                matches = [d for d in self._devices.values() if d.get("state_topic") == topic]
            for dev in matches:
                self._apply_state(dev["id"], payload)
        except Exception:
            log.debug("device_server: on_message failed", exc_info=True)

    def _handle_discovery(self, topic: str, payload: str) -> None:
        try:
            cfg_obj = json.loads(payload) if payload else None
        except Exception:
            return
        if not isinstance(cfg_obj, dict):
            return
        parts = topic.split("/")
        component = parts[1] if len(parts) > 2 else "switch"
        tmap = {"light": "light", "switch": "switch", "fan": "fan", "sensor": "sensor",
                "binary_sensor": "sensor", "climate": "climate", "cover": "cover"}
        dtype = tmap.get(component, "switch")
        did = str(cfg_obj.get("unique_id") or cfg_obj.get("uniq_id") or "/".join(parts[1:-1]))
        self.register_device(
            device_id=did,
            name=str(cfg_obj.get("name") or did),
            dtype=dtype,
            command_topic=str(cfg_obj.get("command_topic") or cfg_obj.get("cmd_t") or ""),
            state_topic=str(cfg_obj.get("state_topic") or cfg_obj.get("stat_t") or ""),
            attrs={"brightness_command_topic": cfg_obj.get("brightness_command_topic")
                   or cfg_obj.get("bri_cmd_t") or "", "discovered": True},
        )

    def _apply_state(self, device_id: str, payload: str) -> None:
        state = payload.strip()
        # JSON state payloads (ESPHome/Z2M) — pull the common 'state' key.
        if state.startswith("{"):
            try:
                obj = json.loads(state)
                state = str(obj.get("state", obj.get("value", state)))
            except Exception:
                pass
        with self._lock:
            dev = self._devices.get(device_id)
            if dev:
                dev["state"] = state
                dev["last_seen"] = time.time()
                self._save()

    # ── Control ─────────────────────────────────────────────────────────────
    def control(self, device_id: str, command: str, value: Any = None) -> Dict[str, Any]:
        with self._lock:
            dev = self._devices.get(device_id)
        if not dev:
            return {"ok": False, "error": f"unknown device: {device_id}"}
        if not self._connected or self._client is None:
            return {"ok": False, "error": "not connected to a broker"}
        cmd = (command or "").lower().strip()
        try:
            if cmd in ("on", "off"):
                topic = dev.get("command_topic")
                if not topic:
                    return {"ok": False, "error": "device has no command_topic"}
                self._client.publish(topic, "ON" if cmd == "on" else "OFF")
            elif cmd in ("brightness", "set_brightness"):
                bt = (dev.get("attrs") or {}).get("brightness_command_topic") or dev.get("command_topic")
                if not bt:
                    return {"ok": False, "error": "device has no brightness topic"}
                self._client.publish(bt, str(int(value)))
            elif cmd == "set":
                topic = dev.get("command_topic")
                self._client.publish(topic, str(value))
            else:
                return {"ok": False, "error": f"unsupported command: {command}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "device": device_id, "command": cmd}


_SERVER: Optional[DeviceServer] = None
_server_lock = threading.Lock()


def get_server() -> DeviceServer:
    global _SERVER
    if _SERVER is None:
        with _server_lock:
            if _SERVER is None:
                _SERVER = DeviceServer()
    return _SERVER
