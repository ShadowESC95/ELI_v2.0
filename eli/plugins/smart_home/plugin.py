"""
Smart Home plugin — Home Assistant REST API integration.
Configure in config/settings.json:
  "hass_url": "http://homeassistant.local:8123"
  "hass_token": "<your long-lived access token>"
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional, Tuple

from eli.plugins.base import Plugin


class SmartHomePlugin(Plugin):
    name = "smart_home"
    description = "Control smart home devices via Home Assistant"

    def __init__(self):
        self.actions = {
            "on": self.turn_on,
            "off": self.turn_off,
            "turn_on": self.turn_on,
            "turn_off": self.turn_off,
            "state": self.get_state,
            "list": self.list_devices,
        }
        super().__init__()

    # ── Config ──────────────────────────────────────────────────────────────

    def _cfg(self) -> Dict[str, str]:
        try:
            from eli.core import config
            return {
                "url": (config.get("hass_url") or "").rstrip("/"),
                "token": config.get("hass_token") or "",
            }
        except Exception:
            return {"url": "", "token": ""}

    # ── HTTP ────────────────────────────────────────────────────────────────

    def _hass(self, method: str, path: str, body: Optional[dict] = None) -> Tuple[Any, Optional[str]]:
        cfg = self._cfg()
        if not cfg["url"]:
            return None, "Home Assistant not configured. Add hass_url and hass_token to settings."
        url = cfg["url"] + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {cfg['token']}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return (json.loads(raw) if raw else {}), None
        except urllib.error.HTTPError as e:
            return None, f"HASS {e.code}: {e.reason}"
        except Exception as e:
            return None, str(e)

    # ── Entity resolution ───────────────────────────────────────────────────

    _DEFAULTS: Dict[str, str] = {
        "light": "light.living_room",
        "lights": "light.living_room",
        "tv": "media_player.tv",
        "television": "media_player.tv",
        "heater": "climate.living_room",
        "thermostat": "climate.living_room",
        "ac": "climate.living_room",
    }

    def _entity(self, name: str) -> str:
        if not name:
            return "light.living_room"
        if "." in name:
            return name
        slug = name.lower().strip()
        if slug in self._DEFAULTS:
            return self._DEFAULTS[slug]
        return f"light.{slug.replace(' ', '_')}"

    # ── Actions ─────────────────────────────────────────────────────────────

    def turn_on(self, args: dict) -> dict:
        device = args.get("device") or args.get("name") or args.get("entity_id") or ""
        entity = self._entity(device)
        extra: dict = {}
        if "brightness" in args:
            extra["brightness"] = int(args["brightness"])
        if "color" in args:
            extra["color_name"] = args["color"]
        _, err = self._hass("POST", "/api/services/homeassistant/turn_on",
                             {"entity_id": entity, **extra})
        if err:
            return {"ok": False, "content": f"Could not turn on {device or entity}: {err}",
                    "response": f"Could not turn on {device or entity}: {err}"}
        return {"ok": True, "content": f"Turned on {entity}.", "response": f"Turned on {device or entity}."}

    def turn_off(self, args: dict) -> dict:
        device = args.get("device") or args.get("name") or args.get("entity_id") or ""
        entity = self._entity(device)
        _, err = self._hass("POST", "/api/services/homeassistant/turn_off", {"entity_id": entity})
        if err:
            return {"ok": False, "content": f"Could not turn off {device or entity}: {err}",
                    "response": f"Could not turn off {device or entity}: {err}"}
        return {"ok": True, "content": f"Turned off {entity}.", "response": f"Turned off {device or entity}."}

    def get_state(self, args: dict) -> dict:
        device = args.get("device") or args.get("name") or args.get("entity_id") or ""
        entity = self._entity(device)
        result, err = self._hass("GET", f"/api/states/{entity}")
        if err:
            return {"ok": False, "content": f"State unavailable for {device or entity}: {err}",
                    "response": err}
        state = result.get("state", "unknown")
        attrs = result.get("attributes", {})
        friendly = attrs.get("friendly_name", entity)
        msg = f"{friendly}: {state}"
        if "brightness" in attrs:
            msg += f" (brightness {attrs['brightness']})"
        if "current_temperature" in attrs:
            msg += f" (temp {attrs['current_temperature']}°)"
        return {"ok": True, "content": msg, "response": msg, "state": state, "attributes": attrs}

    def list_devices(self, args: dict) -> dict:
        result, err = self._hass("GET", "/api/states")
        if err:
            return {"ok": False, "content": err, "response": err}
        _DOMAINS = {"light", "switch", "climate", "media_player", "sensor", "binary_sensor", "cover"}
        entities = []
        for e in (result or []):
            eid = e.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            if domain in _DOMAINS:
                entities.append({
                    "entity_id": eid,
                    "state": e.get("state", "?"),
                    "name": e.get("attributes", {}).get("friendly_name", eid),
                })
        if not entities:
            return {"ok": True, "content": "No devices found (HASS not connected or no devices).",
                    "response": "No devices found."}
        lines = [f"Smart home devices ({len(entities)}):"]
        for e in entities[:25]:
            lines.append(f"  {e['entity_id']:40s} {e['state']:10s} {e['name']}")
        return {"ok": True, "content": "\n".join(lines), "response": "\n".join(lines), "devices": entities}
