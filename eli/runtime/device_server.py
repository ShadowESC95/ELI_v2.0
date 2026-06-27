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
        self._sched_thread = None
        self._load()
        # Resume any saved automations after a restart.
        if self.list_automations():
            self._ensure_scheduler()

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
                        room: str = "", attrs: Optional[dict] = None) -> Dict[str, Any]:
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
                "room": (room.strip() if room else dev.get("room", "")),
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

    def set_room(self, device_id: str, room: str) -> Dict[str, Any]:
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return {"ok": False, "error": "unknown device"}
            dev["room"] = (room or "").strip()
            self._save()
        return {"ok": True, "device": dev}

    def rooms(self) -> List[Dict[str, Any]]:
        """Devices grouped by room. Named rooms first (alphabetical), 'Unassigned' last."""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        with self._lock:
            for d in self._devices.values():
                groups.setdefault((d.get("room") or "").strip() or "Unassigned", []).append(dict(d))
        named = sorted(k for k in groups if k != "Unassigned")
        order = named + (["Unassigned"] if "Unassigned" in groups else [])
        return [{"room": r, "devices": sorted(groups[r], key=lambda x: x.get("name") or x["id"])}
                for r in order]

    def control_room(self, room: str, command: str) -> Dict[str, Any]:
        """Turn every controllable device in a room on/off."""
        room = (room or "").strip() or "Unassigned"
        with self._lock:
            targets = [d["id"] for d in self._devices.values()
                       if ((d.get("room") or "").strip() or "Unassigned") == room
                       and d.get("command_topic")]
        if not targets:
            return {"ok": False, "error": f"no controllable devices in '{room}'"}
        results = [self.control(did, command) for did in targets]
        ok = any(r.get("ok") for r in results)
        return {"ok": ok, "room": room, "count": sum(1 for r in results if r.get("ok"))}

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
        changed = False
        with self._lock:
            dev = self._devices.get(device_id)
            if dev:
                changed = str(dev.get("state")) != state
                dev["state"] = state
                dev["last_seen"] = time.time()
                self._save()
        # Fire any "when this device reaches this state" automations.
        if changed:
            try:
                self.fire_device_state_triggers(device_id, state)
            except Exception:
                log.debug("device-state trigger dispatch failed", exc_info=True)

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
        self._record_usage(device_id, cmd, dev)
        return {"ok": True, "device": device_id, "command": cmd}

    # ── Usage / preference tracking + awareness ──────────────────────────────
    def _record_usage(self, device_id: str, cmd: str, dev: dict) -> None:
        """Append a usage event (for ELI to learn preferences) + feed the LLM's memory.
        Best-effort; never raises into control()."""
        try:
            row = {"id": device_id, "name": dev.get("name") or device_id, "type": dev.get("type"),
                   "room": dev.get("room") or "", "command": cmd, "ts": time.time(),
                   "hour": time.localtime().tm_hour}
            with self._lock:
                p = _registry_path().parent / "usage.jsonl"
                with p.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            log.debug("device_server: usage log failed", exc_info=True)
        # Let ELI's preference layer know (so 'what do you know about me' reflects home use).
        try:
            from eli.runtime import home_intel
            home_intel.note_usage(row)
        except Exception:
            pass

    def usage_summary(self, days: int = 14) -> Dict[str, Any]:
        """Aggregate recent device usage into preference signals: per-device counts and
        the typical hour of use. Drives proactive automation suggestions."""
        import collections
        since = time.time() - float(days) * 86400.0
        per: Dict[str, dict] = {}
        try:
            p = _registry_path().parent / "usage.jsonl"
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if (r.get("ts") or 0) < since:
                        continue
                    d = per.setdefault(r.get("id"), {"id": r.get("id"), "name": r.get("name"),
                                                     "room": r.get("room", ""), "count": 0,
                                                     "hours": collections.Counter(), "last": 0})
                    d["count"] += 1
                    d["hours"][r.get("hour")] += 1
                    d["last"] = max(d["last"], r.get("ts") or 0)
        except Exception:
            log.debug("device_server: usage summary failed", exc_info=True)
        out = []
        for d in per.values():
            fav = d["hours"].most_common(1)
            out.append({"id": d["id"], "name": d["name"], "room": d["room"], "uses": d["count"],
                        "favourite_hour": (fav[0][0] if fav else None), "last": d["last"]})
        out.sort(key=lambda x: x["uses"], reverse=True)
        return {"days": days, "devices": out}

    def home_state(self) -> Dict[str, Any]:
        """A compact snapshot of the home for ELI's self-awareness / LLM context:
        connection, rooms, devices and their states."""
        st = self.status()
        rooms = self.rooms()
        on = [d["name"] for r in rooms for d in r["devices"]
              if str(d.get("state", "")).upper() == "ON"]
        return {"connected": st.get("connected"), "broker": st.get("broker"),
                "device_count": st.get("device_count"), "on": on, "rooms": rooms}

    # ── Scenes (a named group of device actions: "movie mode" etc.) ──────────
    def _scenes_path(self) -> "Path":
        return _registry_path().parent / "scenes.json"

    def list_scenes(self) -> List[Dict[str, Any]]:
        try:
            p = self._scenes_path()
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, list):
                    return [s for s in d if isinstance(s, dict)]
        except Exception:
            log.debug("device_server: scenes load failed", exc_info=True)
        return []

    def _save_scenes(self, scenes: List[dict]) -> None:
        p = self._scenes_path()
        tmp = p.with_suffix(".json.part")
        tmp.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    def add_scene(self, name: str, actions: List[dict]) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "scene name required"}
        acts = [{"device": a.get("device"), "command": (a.get("command") or "on").lower(),
                 "value": a.get("value")} for a in (actions or []) if a.get("device")]
        if not acts:
            return {"ok": False, "error": "a scene needs at least one device action"}
        sc = {"id": "sc" + str(int(time.time() * 1000)), "name": name, "actions": acts}
        scenes = [s for s in self.list_scenes() if s.get("name", "").lower() != name.lower()]
        scenes.append(sc)
        self._save_scenes(scenes)
        return {"ok": True, "scene": sc}

    def remove_scene(self, scene_id: str) -> Dict[str, Any]:
        scenes = self.list_scenes()
        kept = [s for s in scenes if s.get("id") != scene_id and s.get("name") != scene_id]
        if len(kept) == len(scenes):
            return {"ok": False, "error": "no such scene"}
        self._save_scenes(kept)
        return {"ok": True}

    def activate_scene(self, scene_or_id: str) -> Dict[str, Any]:
        key = (scene_or_id or "").strip().lower()
        sc = next((s for s in self.list_scenes()
                   if s.get("id") == scene_or_id or s.get("name", "").lower() == key), None)
        if not sc:
            return {"ok": False, "error": f"no scene called '{scene_or_id}'"}
        results = [self.control(a["device"], a.get("command", "on"), a.get("value"))
                   for a in sc.get("actions", [])]
        return {"ok": any(r.get("ok") for r in results), "scene": sc["name"],
                "ran": sum(1 for r in results if r.get("ok"))}

    # ── Automations: a trigger (time / sun / device-state) runs an action ────
    def _automations_path(self) -> "Path":
        return _registry_path().parent / "automations.json"

    def _normalize_automation(self, a: dict) -> dict:
        # Back-compat: an old flat {device,command,time} record → trigger+action.
        if "trigger" not in a:
            a = {**a,
                 "trigger": {"type": "time", "time": a.get("time", ""), "days": a.get("days", "daily")},
                 "action": {"kind": "device", "device": a.get("device"),
                            "command": a.get("command", "on"), "value": a.get("value")}}
        return a

    def list_automations(self) -> List[Dict[str, Any]]:
        out: List[dict] = []
        try:
            p = self._automations_path()
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, list):
                    out = [self._normalize_automation(a) for a in d if isinstance(a, dict)]
        except Exception:
            log.debug("device_server: automations load failed", exc_info=True)
        return out

    def _save_automations(self, autos: List[dict]) -> None:
        p = self._automations_path()
        tmp = p.with_suffix(".json.part")
        tmp.write_text(json.dumps(autos, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    def _auto_label(self, trig: dict, act: dict) -> str:
        when = {"time": "at " + trig.get("time", ""),
                "sun": "at " + trig.get("event", ""),
                "device_state": f"when {trig.get('device')} {trig.get('state', '')}".strip()
                }.get(trig.get("type"), "")
        what = ("scene " + str(act.get("scene"))) if act.get("kind") == "scene" \
            else f"{act.get('device')} {act.get('command', 'on')}"
        return (what + " " + when).strip()

    def create_automation(self, name: str, trigger: dict, action: dict) -> Dict[str, Any]:
        import re as _re
        t, act = dict(trigger or {}), dict(action or {})
        typ = t.get("type", "time")
        if typ == "time":
            if not _re.match(r"^\d{1,2}:\d{2}$", (t.get("time") or "").strip()):
                return {"ok": False, "error": "time must be HH:MM"}
        elif typ == "sun":
            if t.get("event") not in ("sunrise", "sunset"):
                return {"ok": False, "error": "sun trigger event must be sunrise or sunset"}
        elif typ == "device_state":
            if not t.get("device"):
                return {"ok": False, "error": "device_state trigger needs a device"}
        else:
            return {"ok": False, "error": f"unknown trigger type: {typ}"}
        if act.get("kind") == "scene":
            if not act.get("scene"):
                return {"ok": False, "error": "scene action needs a scene"}
        else:
            act["kind"] = "device"
            if not act.get("device"):
                return {"ok": False, "error": "device action needs a device"}
        auto = {"id": "a" + str(int(time.time() * 1000)), "name": name or self._auto_label(t, act),
                "enabled": True, "trigger": t, "action": act}
        autos = self.list_automations()
        autos.append(auto)
        self._save_automations(autos)
        self._ensure_scheduler()
        return {"ok": True, "automation": auto}

    def add_automation(self, *, device: str, command: str, time_str: str,
                       value: Any = None, days: Any = "daily", name: str = "") -> Dict[str, Any]:
        """Back-compat helper: a clock-time trigger that controls one device."""
        with self._lock:
            dev = self._devices.get(device)
        label = name or (f"{(dev or {}).get('name', device)} → {command} at {time_str}")
        return self.create_automation(
            label, {"type": "time", "time": (time_str or "").strip(), "days": days or "daily"},
            {"kind": "device", "device": device, "command": (command or "on").lower().strip(), "value": value})

    def remove_automation(self, auto_id: str) -> Dict[str, Any]:
        autos = self.list_automations()
        kept = [a for a in autos if a.get("id") != auto_id]
        if len(kept) == len(autos):
            return {"ok": False, "error": "no such automation"}
        self._save_automations(kept)
        return {"ok": True}

    def set_automation_enabled(self, auto_id: str, enabled: bool) -> Dict[str, Any]:
        autos = self.list_automations()
        found = False
        for a in autos:
            if a.get("id") == auto_id:
                a["enabled"] = bool(enabled); found = True
        if not found:
            return {"ok": False, "error": "no such automation"}
        self._save_automations(autos)
        return {"ok": True}

    def _run_action(self, action: dict) -> Dict[str, Any]:
        if (action or {}).get("kind") == "scene":
            return self.activate_scene(action.get("scene"))
        return self.control(action.get("device"), action.get("command", "on"), action.get("value"))

    def _sun_hm(self) -> Dict[str, str]:
        try:
            from eli.core import config
            lat, lon = config.get("home_lat"), config.get("home_lon")
            if lat is None or lon is None:
                return {}
            return _sun_times_local(float(lat), float(lon)) or {}
        except Exception:
            return {}

    @staticmethod
    def _apply_offset(hm: str, offset_min: Any) -> str:
        try:
            h, m = hm.split(":")
            tot = (int(h) * 60 + int(m) + int(offset_min or 0)) % (24 * 60)
            return "%02d:%02d" % (tot // 60, tot % 60)
        except Exception:
            return hm

    def fire_device_state_triggers(self, device_id: str, state: str) -> None:
        """Run any 'when <device> reaches <state>' automations. Called on state updates."""
        s = (state or "").upper()
        for a in self.list_automations():
            if not a.get("enabled"):
                continue
            tr = a.get("trigger", {})
            if (tr.get("type") == "device_state" and tr.get("device") == device_id
                    and (not tr.get("state") or str(tr.get("state")).upper() == s)):
                try:
                    self._run_action(a.get("action", {}))
                except Exception:
                    log.debug("device_state automation failed", exc_info=True)

    def _ensure_scheduler(self) -> None:
        if getattr(self, "_sched_thread", None) and self._sched_thread.is_alive():
            return
        self._sched_thread = threading.Thread(target=self._sched_loop, daemon=True)
        self._sched_thread.start()

    def _sched_loop(self) -> None:
        last: Dict[str, str] = {}
        while True:
            try:
                now = time.localtime()
                hm = "%02d:%02d" % (now.tm_hour, now.tm_min)
                stamp = time.strftime("%Y-%m-%d %H:%M", now)
                sun = self._sun_hm()
                for a in self.list_automations():
                    if not a.get("enabled"):
                        continue
                    tr = a.get("trigger", {})
                    typ = tr.get("type")
                    fire = False
                    if typ == "time":
                        if tr.get("time") == hm:
                            days = tr.get("days")
                            fire = not (isinstance(days, list) and now.tm_wday not in days)
                    elif typ == "sun":
                        base = sun.get(tr.get("event"))
                        if base and self._apply_offset(base, tr.get("offset", 0)) == hm:
                            fire = True
                    # device_state triggers fire from on_message, not here.
                    if fire and last.get(a["id"]) != stamp:
                        last[a["id"]] = stamp
                        try:
                            self._run_action(a.get("action", {}))
                            log.debug("automation fired: %s", a.get("name"))
                        except Exception:
                            log.debug("automation fire failed", exc_info=True)
            except Exception:
                log.debug("scheduler loop error", exc_info=True)
            time.sleep(20)


def discover(timeout: float = 3.0) -> Dict[str, Any]:
    """Find MQTT brokers and smart devices on the LAN via mDNS — so the user doesn't
    have to know IPs/topics. Gated through netguard (a deliberate local-network scan);
    degrades cleanly if zeroconf isn't installed."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
    except Exception:
        return {"ok": False, "error": "zeroconf not installed (pip install zeroconf)", "found": []}

    # Service types worth surfacing: MQTT brokers + common smart-device advertisements.
    types = ["_mqtt._tcp.local.", "_esphomelib._tcp.local.", "_hap._tcp.local.",
             "_googlecast._tcp.local.", "_homekit._tcp.local.", "_http._tcp.local."]
    found: List[dict] = []

    class _L(ServiceListener):
        def _grab(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name, timeout=1500)
                if not info:
                    return
                addrs = []
                try:
                    addrs = info.parsed_addresses()
                except Exception:
                    pass
                found.append({"name": name.split("." + type_)[0] or name, "service": type_,
                              "host": addrs[0] if addrs else "", "port": getattr(info, "port", None)})
            except Exception:
                pass
        def add_service(self, zc, type_, name): self._grab(zc, type_, name)
        def update_service(self, zc, type_, name): pass
        def remove_service(self, zc, type_, name): pass

    try:
        from eli.core import netguard
        ctx = netguard.allow_network("mDNS device discovery")
    except Exception:
        import contextlib
        ctx = contextlib.nullcontext()
    try:
        with ctx:
            zc = Zeroconf()
            listener = _L()
            _browsers = [ServiceBrowser(zc, t, listener) for t in types]
            time.sleep(max(1.0, float(timeout)))
            zc.close()
    except Exception as e:
        return {"ok": False, "error": str(e), "found": []}

    # Dedupe + classify.
    seen, uniq = set(), []
    for f in found:
        key = (f.get("host"), f.get("port"), f.get("service"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    brokers = [f for f in uniq if f["service"].startswith("_mqtt") and f.get("host")]
    return {"ok": True, "found": uniq, "brokers": brokers}


def _sun_times_local(lat: float, lon: float) -> Optional[Dict[str, str]]:
    """Local sunrise/sunset 'HH:MM' for today at (lat, lon) — the standard sunrise
    equation, no network or extra deps. Returns None at the poles where the sun
    doesn't rise/set. Accurate to about a minute (fine for home automation)."""
    import math
    try:
        now = time.localtime()
        N = time.struct_time(now).tm_yday
        zenith = 90.833  # official sunrise/sunset
        lng_hour = lon / 15.0
        out: Dict[str, str] = {}
        for event, rising in (("sunrise", True), ("sunset", False)):
            t = N + ((6 if rising else 18) - lng_hour) / 24.0
            M = (0.9856 * t) - 3.289
            L = (M + 1.916 * math.sin(math.radians(M)) + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
            RA = (math.degrees(math.atan(0.91764 * math.tan(math.radians(L))))) % 360
            RA += (math.floor(L / 90) * 90) - (math.floor(RA / 90) * 90)
            RA /= 15.0
            sin_dec = 0.39782 * math.sin(math.radians(L))
            cos_dec = math.cos(math.asin(sin_dec))
            cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (cos_dec * math.cos(math.radians(lat)))
            if cos_h > 1 or cos_h < -1:
                return None
            H = (360 - math.degrees(math.acos(cos_h))) if rising else math.degrees(math.acos(cos_h))
            H /= 15.0
            T = H + RA - (0.06571 * t) - 6.622
            UT = (T - lng_hour) % 24
            offset = (-time.altzone if now.tm_isdst and time.daylight else -time.timezone) / 3600.0
            local = (UT + offset) % 24
            hh = int(local)
            mm = int(round((local - hh) * 60))
            if mm == 60:
                hh = (hh + 1) % 24
                mm = 0
            out[event] = "%02d:%02d" % (hh, mm)
        return out
    except Exception:
        log.debug("sun calc failed", exc_info=True)
        return None


_SERVER: Optional[DeviceServer] = None
_server_lock = threading.Lock()


def get_server() -> DeviceServer:
    global _SERVER
    if _SERVER is None:
        with _server_lock:
            if _SERVER is None:
                _SERVER = DeviceServer()
    return _SERVER
