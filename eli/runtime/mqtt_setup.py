"""Cross-platform MQTT broker onboarding for ELI redistribution.

Provides platform-specific install guidance, discovery-prefix presets, and a
connection probe that works on Linux, Windows, macOS, and headless servers.
"""
from __future__ import annotations

import socket
from typing import Any, Dict, List, Optional

DISCOVERY_PRESETS: List[Dict[str, str]] = [
    {
        "id": "",
        "label": "Manual devices only",
        "hint": "Add each light/switch yourself with its MQTT command and state topics.",
    },
    {
        "id": "homeassistant",
        "label": "Home Assistant / ESPHome / Tasmota / Zigbee2MQTT",
        "hint": "Standard homeassistant/… discovery messages (most DIY firmware).",
    },
    {
        "id": "tasmota/discovery",
        "label": "Tasmota native discovery",
        "hint": "Tasmota devices publishing to tasmota/discovery/…",
    },
    {
        "id": "zigbee2mqtt",
        "label": "Zigbee2MQTT bridge",
        "hint": "Zigbee devices exposed by a Zigbee2MQTT gateway.",
    },
]

COMMON_BROKER_PORTS = (1883, 8883, 1884, 9001)


def detect_platform() -> str:
    try:
        from eli.utils.platform_compat import ANDROID, LINUX, MACOS, WINDOWS
        if ANDROID:
            return "android"
        if WINDOWS:
            return "windows"
        if MACOS:
            return "macos"
        if LINUX:
            return "linux"
    except Exception:
        pass
    import sys
    p = sys.platform.lower()
    if p.startswith("win"):
        return "windows"
    if p == "darwin":
        return "macos"
    if p.startswith("linux"):
        return "linux"
    return "other"


def broker_install_guide(platform: Optional[str] = None) -> Dict[str, Any]:
    """Return human-readable, platform-specific Mosquitto / MQTT broker steps."""
    plat = (platform or detect_platform()).lower()
    guides: Dict[str, Dict[str, Any]] = {
        "linux": {
            "title": "Linux — install Mosquitto locally or on a Pi/NAS",
            "steps": [
                "Debian/Ubuntu: sudo apt update && sudo apt install -y mosquitto mosquitto-clients",
                "Fedora/RHEL: sudo dnf install -y mosquitto",
                "Arch: sudo pacman -S mosquitto",
                "Start the service: sudo systemctl enable --now mosquitto",
                "Test: mosquitto_pub -h 127.0.0.1 -t test -m hello",
                "Use 127.0.0.1 or your machine's LAN IP below; default port is 1883.",
            ],
            "notes": "ELI's NetGuard allows only the broker host you configure — the rest of the internet stays blocked unless you enable network.",
        },
        "windows": {
            "title": "Windows — Mosquitto or any MQTT broker on your LAN",
            "steps": [
                "Option A: winget install EclipseFoundation.Mosquitto",
                "Option B: Download the Mosquitto installer from https://mosquitto.org/download/",
                "During setup, allow the Windows Firewall prompt for port 1883 on private networks.",
                "Start the Mosquitto service (Services app → Mosquitto → Start).",
                "Use 127.0.0.1 if Mosquitto runs on this PC, or the broker PC's LAN IP.",
                "Default port: 1883 (8883 if you enabled TLS).",
            ],
            "notes": "Home Assistant on another machine, a Raspberry Pi, or a router with MQTT also work — enter that device's IP as the broker host.",
        },
        "macos": {
            "title": "macOS — Homebrew Mosquitto or a LAN broker",
            "steps": [
                "brew install mosquitto",
                "brew services start mosquitto",
                "Test: mosquitto_pub -h 127.0.0.1 -t test -m hello",
                "Use 127.0.0.1 for a local broker, or your NAS/Pi IP for a remote one.",
                "Default port: 1883.",
            ],
            "notes": "Many users run Mosquitto on a Raspberry Pi and point ELI at pi.local:1883.",
        },
        "android": {
            "title": "Android / Termux — use ELI as a client, not the broker host",
            "steps": [
                "Run ELI's web UI on your desktop or server (recommended).",
                "Point the phone browser at http://<server-ip>:8081",
                "Configure MQTT with your home broker's LAN IP (Pi, HA, router, NAS).",
                "Termux can run ELI headless but is not the typical MQTT broker host.",
            ],
            "notes": "MQTT control from a phone uses the ELI server API; the broker stays on your LAN.",
        },
        "other": {
            "title": "Any platform — connect to an existing MQTT broker",
            "steps": [
                "You need a broker reachable on your LAN: Mosquitto, Home Assistant, OpenHAB, etc.",
                "Find its IP or hostname (e.g. 192.168.1.50 or mosquitto.local).",
                "Default MQTT port is 1883 (8883 for TLS).",
                "Enter host + port in ELI, then Save & connect.",
                "Use discovery prefix homeassistant if your devices use standard DIY discovery.",
            ],
            "notes": "ELI talks MQTT directly — no Home Assistant integration required.",
        },
    }
    base = guides.get(plat, guides["other"])
    return {
        "platform": plat,
        "title": base["title"],
        "steps": list(base["steps"]),
        "notes": base.get("notes", ""),
        "discovery_presets": list(DISCOVERY_PRESETS),
        "default_port": 1883,
        "common_ports": list(COMMON_BROKER_PORTS),
    }


def probe_broker_connection(
    *,
    host: str,
    port: int = 1883,
    username: str = "",
    password: str = "",
    tls: bool = False,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Probe broker reachability without starting the full device server."""
    host = (host or "").strip()
    if not host:
        return {"ok": False, "error": "broker host is required"}
    try:
        port = int(port or 1883)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid port"}

    try:
        import paho.mqtt.client as mqtt
    except Exception:
        return {
            "ok": False,
            "error": "paho-mqtt not installed — run: pip install paho-mqtt",
            "need_install": True,
        }

    result: Dict[str, Any] = {"ok": False, "host": host, "port": port}
    done = {"finished": False, "rc": -1, "error": ""}

    def _on_connect(client, userdata, flags, rc, *args):
        done["rc"] = int(rc)
        done["finished"] = True
        try:
            client.disconnect()
        except Exception:
            pass

    try:
        try:
            client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1)
        except (AttributeError, TypeError):
            client = mqtt.Client()
        if username:
            client.username_pw_set(username, password or None)
        if tls:
            client.tls_set()
        client.on_connect = _on_connect
        client.connect(host, port, keepalive=30)
        client.loop_start()
        import time
        deadline = time.time() + max(1.0, float(timeout))
        while time.time() < deadline and not done["finished"]:
            time.sleep(0.05)
        try:
            client.loop_stop()
        except Exception:
            pass
    except Exception as exc:
        hint = _connection_hint(str(exc), host, port)
        return {"ok": False, "error": str(exc), "hint": hint, "host": host, "port": port}

    rc = done["rc"]
    if rc == 0:
        return {"ok": True, "message": f"Connected to {host}:{port}", "host": host, "port": port}
    errors = {
        1: "incorrect MQTT protocol version",
        2: "invalid client identifier",
        3: "broker unavailable",
        4: "bad username or password",
        5: "not authorised",
    }
    msg = errors.get(rc, f"broker refused connection (rc={rc})")
    return {
        "ok": False,
        "error": msg,
        "hint": _connection_hint(msg, host, port),
        "host": host,
        "port": port,
    }


def _connection_hint(error: str, host: str, port: int) -> str:
    low = (error or "").lower()
    if "111" in low or "connection refused" in low or "actively refused" in low:
        return (
            f"Nothing is listening on {host}:{port}. "
            "Start Mosquitto (or your broker), confirm the port (usually 1883), "
            "and check firewall rules on private/LAN networks."
        )
    if "name or service not known" in low or "getaddrinfo" in low or "nodename" in low:
        return f"Could not resolve hostname '{host}'. Try the broker's IP address instead."
    if "timed out" in low or "timeout" in low:
        return (
            f"Broker at {host}:{port} did not answer in time. "
            "Ensure this machine and the broker are on the same network/VLAN."
        )
    if "not authorised" in low or "bad username" in low or "rc=4" in low or "rc=5" in low:
        return "Check MQTT username and password — leave both blank if your broker has no auth."
    return "Verify host, port, firewall, and that the broker allows connections from this machine."


def suggest_local_hosts() -> List[str]:
    """Best-effort list of hosts worth trying on a fresh install."""
    hosts = ["127.0.0.1", "localhost", "mosquitto.local", "mqtt.local"]
    try:
        hostname = socket.gethostname()
        if hostname:
            hosts.append(hostname)
    except Exception:
        pass
    try:
        import socket as _s
        _, _, addrs = _s.gethostbyname_ex(_s.gethostname())
        for a in addrs:
            if a and a not in hosts:
                hosts.append(a)
    except Exception:
        pass
    return hosts
