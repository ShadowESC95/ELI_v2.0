"""Pluggable LOCAL-control drivers for ELI's device server — control devices that don't
speak MQTT (AirPlay, Fire TV, Chromecast, UPnP/DLNA renderers), entirely on the LAN.

Design (matches the rest of ELI: lazy, fail-soft, no surprise deps):
  • Every driver lazy-imports its third-party library. If it's absent, the driver reports
    ``available() -> (False, "<pip package>")`` instead of crashing — the dashboard then
    offers a one-click install. Nothing heavy is imported at module load.
  • Drivers are LOCAL only. They never reach the internet; control stays on your network.
  • Pairing is uniform: ``pair(dev, code=None)`` returns a small state machine result —
    ``need_code`` (enter the PIN shown on the device), ``instructions`` (do X on the device,
    then retry), ``paired`` (store the returned credentials on the device), or ``error``.
    So the dashboard can drive any protocol's pairing with one widget.
  • Control is uniform: ``control(dev, command, value)`` → ``{ok, ...}``.

A registry device carries ``driver`` (default "mqtt"). DeviceServer.control() dispatches
non-mqtt devices here; MQTT stays on its existing path.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


def _creds_dir() -> Path:
    """Per-device credentials (ADB keys, AirPlay creds) live beside the registry, 0700."""
    try:
        from eli.core.paths import get_paths
        p = Path(get_paths().artifacts_dir) / "devices" / "creds"
    except Exception:
        p = Path("artifacts") / "devices" / "creds"
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(0o700)
    except Exception:
        pass
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Driver base
# ─────────────────────────────────────────────────────────────────────────────
class Driver:
    name: str = "base"
    label: str = "Device"
    pip: Optional[str] = None          # pip package that powers it (None = no dep)
    needs_pairing: bool = False
    # How pairing works, for the UI: "accept" (confirm on the device, then retry),
    # "pin" (enter a code the device shows), or "" (none).
    pair_style: str = ""

    def available(self) -> Tuple[bool, str]:
        """(importable?, message). No dep → always available."""
        if not self.pip:
            return True, "ready"
        try:
            self._import()
            return True, "ready"
        except Exception:
            return False, self.pip

    def _import(self):  # pragma: no cover - trivial, overridden where there's a dep
        return None

    def capabilities(self, dev: Dict[str, Any]) -> List[str]:
        return []

    def pair(self, dev: Dict[str, Any], code: Optional[str] = None) -> Dict[str, Any]:
        return {"ok": True, "paired": True}  # no pairing needed by default

    def control(self, dev: Dict[str, Any], command: str, value: Any = None) -> Dict[str, Any]:
        return {"ok": False, "error": f"{self.name}: unsupported command {command!r}"}

    # Small helper so async libs can be driven from the sync device server.
    @staticmethod
    def _run(coro):
        import asyncio
        return asyncio.new_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# UPnP / DLNA MediaRenderer — raw SOAP, NO dependency, NO pairing
# ─────────────────────────────────────────────────────────────────────────────
class UpnpDriver(Driver):
    name = "upnp"
    label = "Media renderer (UPnP/DLNA)"
    pip = None

    def capabilities(self, dev):
        return ["play", "pause", "stop", "volume"]

    def _control_url(self, dev) -> Tuple[Optional[str], Optional[str], str]:
        """Resolve AVTransport + RenderingControl control URLs from the device's SSDP
        description XML (cached on the device dict after first lookup)."""
        attrs = dev.get("attrs") or {}
        av = attrs.get("av_control_url")
        rc = attrs.get("rc_control_url")
        base = attrs.get("upnp_base") or ""
        if av or rc:
            return av, rc, base
        loc = dev.get("location") or attrs.get("location")
        if not loc:
            return None, None, ""
        import urllib.request
        from urllib.parse import urljoin
        import xml.etree.ElementTree as ET
        with urllib.request.urlopen(loc, timeout=4) as r:  # local LAN URL
            xml = r.read().decode(errors="ignore")
        base = loc
        ns = {"u": "urn:schemas-upnp-org:device-1-0"}
        root = ET.fromstring(xml)
        for svc in root.iter():
            if not svc.tag.endswith("service"):
                continue
            st = (svc.findtext("{*}serviceType") or "")
            cu = (svc.findtext("{*}controlURL") or "")
            if not cu:
                continue
            full = urljoin(base, cu)
            if "AVTransport" in st:
                av = full
            elif "RenderingControl" in st:
                rc = full
        attrs["av_control_url"], attrs["rc_control_url"], attrs["upnp_base"] = av, rc, base
        dev["attrs"] = attrs
        return av, rc, base

    def _soap(self, url: str, service: str, action: str, body_args: str) -> str:
        import urllib.request
        envelope = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{service}">{body_args}</u:{action}>'
            '</s:Body></s:Envelope>'
        ).encode()
        req = urllib.request.Request(url, data=envelope, headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service}#{action}"',
        })
        with urllib.request.urlopen(req, timeout=4) as r:  # local LAN
            return r.read().decode(errors="ignore")

    def control(self, dev, command, value=None):
        av, rc, _ = self._control_url(dev)
        AVT = "urn:schemas-upnp-org:service:AVTransport:1"
        RND = "urn:schemas-upnp-org:service:RenderingControl:1"
        cmd = (command or "").lower()
        try:
            if cmd in ("play", "on"):
                self._soap(av, AVT, "Play", "<InstanceID>0</InstanceID><Speed>1</Speed>")
            elif cmd in ("pause",):
                self._soap(av, AVT, "Pause", "<InstanceID>0</InstanceID>")
            elif cmd in ("stop", "off"):
                self._soap(av, AVT, "Stop", "<InstanceID>0</InstanceID>")
            elif cmd in ("volume", "set_volume"):
                vol = max(0, min(100, int(value if value is not None else 30)))
                self._soap(rc, RND, "SetVolume",
                           f"<InstanceID>0</InstanceID><Channel>Master</Channel>"
                           f"<DesiredVolume>{vol}</DesiredVolume>")
            else:
                return {"ok": False, "error": f"upnp: unsupported command {command!r}"}
        except Exception as e:
            return {"ok": False, "error": f"upnp: {e}"}
        return {"ok": True, "device": dev.get("id"), "command": cmd}


# ─────────────────────────────────────────────────────────────────────────────
# Google Cast / Chromecast — pychromecast, NO pairing (open on LAN)
# ─────────────────────────────────────────────────────────────────────────────
class CastDriver(Driver):
    name = "cast"
    label = "Google Cast"
    pip = "pychromecast"

    def _import(self):
        import pychromecast  # noqa: F401
        return pychromecast

    def capabilities(self, dev):
        return ["play", "pause", "stop", "volume"]

    def _cast(self, dev):
        pcc = self._import()
        host = dev.get("host")
        casts, browser = pcc.get_listed_chromecasts(known_hosts=[host]) if host else ([], None)
        if not casts:
            casts, browser = pcc.get_chromecasts()
            casts = [c for c in casts if c.cast_info.host == host] or casts
        if not casts:
            raise RuntimeError("cast device not reachable")
        cast = casts[0]
        cast.wait(timeout=5)
        return cast, browser

    def control(self, dev, command, value=None):
        cmd = (command or "").lower()
        try:
            cast, browser = self._cast(dev)
            try:
                mc = cast.media_controller
                if cmd in ("play", "on"):
                    mc.play()
                elif cmd == "pause":
                    mc.pause()
                elif cmd in ("stop", "off"):
                    mc.stop()
                elif cmd in ("volume", "set_volume"):
                    cast.set_volume(max(0.0, min(1.0, float(value) / 100.0)))
                else:
                    return {"ok": False, "error": f"cast: unsupported command {command!r}"}
            finally:
                try:
                    if browser:
                        browser.stop_discovery()
                except Exception:
                    pass
        except Exception as e:
            return {"ok": False, "error": f"cast: {e}"}
        return {"ok": True, "device": dev.get("id"), "command": cmd}


# ─────────────────────────────────────────────────────────────────────────────
# Amazon Fire TV / Android TV — androidtv (ADB). Pairing = accept-on-device.
# ─────────────────────────────────────────────────────────────────────────────
class FireTVDriver(Driver):
    name = "firetv"
    label = "Amazon Fire TV"
    pip = "androidtv[async]"
    needs_pairing = True
    pair_style = "accept"

    def _import(self):
        from androidtv import setup  # noqa: F401
        return setup

    def capabilities(self, dev):
        return ["play", "pause", "home", "back", "up", "down", "left", "right",
                "select", "on", "off", "volume_up", "volume_down"]

    def _adbkey(self) -> str:
        key = _creds_dir() / "adbkey"
        if not key.exists():
            try:
                from adb_shell.auth.keygen import keygen
                keygen(str(key))
            except Exception as e:
                raise RuntimeError(f"could not generate ADB key ({e})")
        return str(key)

    def _connect(self, dev):
        setup = self._import()
        host = dev.get("host")
        port = 5555  # Fire TV ADB network port (independent of the mDNS advert port)
        aftv = setup(host, self._adbkey(), port=port, device_class="firetv",
                     auth_timeout_s=2.0)
        return aftv

    def pair(self, dev, code=None):
        """ADB 'pairing' = the TV pops an 'Allow debugging from this computer?' dialog the
        first time we connect with our key. There's no PIN; the user taps Allow, then we
        retry and the key is trusted thereafter."""
        try:
            aftv = self._connect(dev)
        except Exception as e:
            return {"ok": False, "error": str(e),
                    "instructions": [
                        "On the Fire TV: Settings → My Fire TV → About → click the build a few "
                        "times to unlock Developer Options.",
                        "Settings → My Fire TV → Developer Options → turn ON 'ADB debugging'.",
                        "Click Pair again and accept 'Allow debugging from this computer?' on the TV.",
                    ]}
        ok = bool(getattr(aftv, "available", False)) or self._available(aftv)
        if ok:
            attrs = dev.get("attrs") or {}
            attrs["adbkey"] = str(_creds_dir() / "adbkey")
            attrs["adb_port"] = 5555
            dev["attrs"] = attrs
            return {"ok": True, "paired": True}
        return {"ok": False, "error": "not yet authorised",
                "instructions": [
                    "Accept the 'Allow debugging from this computer?' prompt on the Fire TV,",
                    "tick 'Always allow', then click Pair again.",
                ], "retry": True}

    @staticmethod
    def _available(aftv) -> bool:
        try:
            aftv.adb_connect(timeout=2.0)
            return bool(aftv.available)
        except Exception:
            return False

    def control(self, dev, command, value=None):
        cmd = (command or "").lower()
        try:
            aftv = self._connect(dev)
            if not self._available(aftv):
                return {"ok": False, "error": "not paired/authorised — pair the Fire TV first",
                        "need_pair": True}
            keymap = {
                "play": aftv.media_play, "pause": aftv.media_pause,
                "home": lambda: aftv.adb_shell("input keyevent 3"),
                "back": lambda: aftv.adb_shell("input keyevent 4"),
                "up": lambda: aftv.adb_shell("input keyevent 19"),
                "down": lambda: aftv.adb_shell("input keyevent 20"),
                "left": lambda: aftv.adb_shell("input keyevent 21"),
                "right": lambda: aftv.adb_shell("input keyevent 22"),
                "select": lambda: aftv.adb_shell("input keyevent 23"),
                "on": aftv.turn_on, "off": aftv.turn_off,
                "volume_up": lambda: aftv.adb_shell("input keyevent 24"),
                "volume_down": lambda: aftv.adb_shell("input keyevent 25"),
            }
            fn = keymap.get(cmd)
            if not fn:
                return {"ok": False, "error": f"firetv: unsupported command {command!r}"}
            fn()
        except Exception as e:
            return {"ok": False, "error": f"firetv: {e}"}
        return {"ok": True, "device": dev.get("id"), "command": cmd}


# ─────────────────────────────────────────────────────────────────────────────
# AirPlay (Apple TV / AirPlay-2 receivers / some TVs) — pyatv. Pairing = PIN.
# ─────────────────────────────────────────────────────────────────────────────
class AirPlayDriver(Driver):
    name = "airplay"
    label = "AirPlay"
    pip = "pyatv"
    needs_pairing = True
    pair_style = "pin"

    def _import(self):
        import pyatv  # noqa: F401
        return pyatv

    def capabilities(self, dev):
        return ["play", "pause", "stop", "next", "previous", "volume"]

    async def _scan_one(self, pyatv, host, timeout: float = 6.0):
        """Locate the receiver robustly. A targeted unicast scan to AirPlay devices is
        flaky (Apple TV / Sky / Now boxes often ignore unicast mDNS), so if it comes up
        empty we fall back to a full broadcast sweep and match by address. On failure we
        report what we *did* see, so 'not found' is actionable instead of a dead end."""
        import asyncio
        loop = asyncio.get_event_loop()
        # 1) targeted unicast scan (fast path)
        confs = []
        try:
            confs = await pyatv.scan(loop, hosts=[host], timeout=timeout)
        except Exception:
            confs = []
        if confs:
            return confs[0]
        # 2) broadcast sweep, match by address
        try:
            confs = await pyatv.scan(loop, timeout=timeout)
        except Exception:
            confs = []
        for c in confs or []:
            if str(getattr(c, "address", "")) == str(host):
                return c
        if confs:
            names = ", ".join(sorted({str(getattr(c, "name", "?")) for c in confs})[:6])
            raise RuntimeError(
                f"that address didn't answer AirPlay pairing; receivers I can see: {names}. "
                "If yours isn't listed it may not support AirPlay PIN pairing.")
        raise RuntimeError(
            "no AirPlay receiver answered — make sure it's powered on, awake, and on this "
            "same Wi-Fi/LAN, then try again")

    def pair(self, dev, code=None):
        """Two-step PIN pairing. First call (no code): begin pairing — the device shows a
        PIN. Second call (with code): finish — store the returned credentials."""
        pyatv = self._import()
        from pyatv.const import Protocol
        host = dev.get("host")
        import asyncio

        async def _begin():
            loop = asyncio.get_event_loop()
            conf = await self._scan_one(pyatv, host)
            pairing = await pyatv.pair(conf, Protocol.AirPlay, loop)
            await pairing.begin()
            return pairing

        async def _finish(pairing, pin):
            pairing.pin(pin)
            await pairing.finish()
            creds = pairing.service.credentials
            await pairing.close()
            return creds

        try:
            if not code:
                # Begin, then immediately close — we only needed to make the device show a PIN.
                pairing = self._run(_begin())
                self._run(pairing.close())
                return {"ok": False, "need_code": True,
                        "prompt": "Enter the 4-digit code shown on your AirPlay device."}
            # Finish: re-begin (stateless across HTTP calls) and submit the code.
            pairing = self._run(_begin())
            creds = self._run(_finish(pairing, str(code)))
            attrs = dev.get("attrs") or {}
            attrs["airplay_credentials"] = creds
            dev["attrs"] = attrs
            return {"ok": True, "paired": True}
        except Exception as e:
            return {"ok": False, "error": f"airplay: {e}"}

    def control(self, dev, command, value=None):
        pyatv = self._import()
        from pyatv.const import Protocol
        creds = (dev.get("attrs") or {}).get("airplay_credentials")
        if not creds:
            return {"ok": False, "error": "not paired — pair this AirPlay device first",
                    "need_pair": True}
        host, cmd = dev.get("host"), (command or "").lower()
        import asyncio

        async def _do():
            loop = asyncio.get_event_loop()
            conf = await self._scan_one(pyatv, host)
            conf.set_credentials(Protocol.AirPlay, creds)
            atv = await pyatv.connect(conf, loop)
            try:
                rc = atv.remote_control
                if cmd in ("play", "on"):
                    await rc.play()
                elif cmd == "pause":
                    await rc.pause()
                elif cmd in ("stop", "off"):
                    await rc.stop()
                elif cmd == "next":
                    await rc.next()
                elif cmd == "previous":
                    await rc.previous()
                elif cmd in ("volume", "set_volume"):
                    await atv.audio.set_volume(max(0.0, min(100.0, float(value))))
                else:
                    return {"ok": False, "error": f"airplay: unsupported command {command!r}"}
            finally:
                atv.close()
            return {"ok": True, "device": dev.get("id"), "command": cmd}

        try:
            return self._run(_do())
        except Exception as e:
            return {"ok": False, "error": f"airplay: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Bluetooth — pair / connect / disconnect + route system audio to the device.
# Uses the OS Bluetooth stack, NO python dep: bluetoothctl + pactl/pipewire on Linux,
# blueutil (+ switchaudio-osx) on macOS. Windows control is not wired yet (roadmap).
# Every branch degrades to a clean, actionable message — it never raises.
# ─────────────────────────────────────────────────────────────────────────────
class BluetoothDriver(Driver):
    name = "bluetooth"
    label = "Bluetooth device"
    pip = None                    # OS tools, no python package
    needs_pairing = True
    pair_style = "accept"         # usually confirm/accept the pairing on the device itself
    BRAND = "Eli"
    DEFAULT_HUB_ZONE = "Home"
    MAX_ALIAS_LEN = 48            # TVs truncate long Bluetooth names

    def capabilities(self, dev):
        return ["connect", "disconnect", "pair", "trust", "use_for_audio"]

    @staticmethod
    def _addr(dev: Dict[str, Any]) -> str:
        a = str(dev.get("host") or dev.get("address") or "").strip()
        if not a and str(dev.get("id", "")).startswith("ble:"):
            a = str(dev["id"])[4:]
        return a

    @staticmethod
    def _sh(args, timeout: float = 25.0):
        import subprocess
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except FileNotFoundError:
            return 127, "tool-not-found"
        except Exception as e:  # timeout / permission / anything — stay graceful
            return 1, str(e)

    def pair(self, dev, code=None):
        return self.control(dev, "pair")

    def control(self, dev, command, value=None):
        addr = self._addr(dev)
        if not addr:
            return {"ok": False, "error": "bluetooth: no device address"}
        cmd = (command or "").lower().replace("-", "_")
        if cmd in ("use_for_audio", "audio", "route_audio", "listen", "output"):
            info = self._bt_device_info(addr)
            meta = self.classify_bt_device(info, str(dev.get("name") or ""))
            if not meta.get("audio_capable"):
                return {
                    "ok": False,
                    "error": f"{meta.get('label', 'Device')} is not an audio output — pair your headphones, not printers/adapters",
                }
            return self._route_audio(addr)
        action = {
            "connect": "connect", "on": "connect",
            "disconnect": "disconnect", "off": "disconnect",
            "pair": "pair", "trust": "trust",
        }.get(cmd)
        if not action:
            return {"ok": False, "error": f"bluetooth: unsupported command {command!r}"}
        return self._bt_action(addr, action)

    @classmethod
    def resolve_adapter_alias(cls) -> str:
        """Hub label on Bluetooth pairing screens: Eli · {zone}, or a settings override."""
        try:
            from eli.core.runtime_settings import load_settings
            s = load_settings() or {}
        except Exception:
            s = {}
        override = str(s.get("bluetooth_display_name") or "").strip()
        if override:
            return override[: cls.MAX_ALIAS_LEN]
        zone = str(s.get("hub_zone") or "").strip() or cls.DEFAULT_HUB_ZONE
        return f"{cls.BRAND} · {zone}"[: cls.MAX_ALIAS_LEN]

    @classmethod
    def ensure_adapter_alias(cls, alias: Optional[str] = None) -> Dict[str, Any]:
        """Set this PC's Bluetooth friendly name (what TVs/speakers show when pairing)."""
        import shutil, sys
        name = (alias or cls.resolve_adapter_alias()).strip() or cls.resolve_adapter_alias()
        if sys.platform == "darwin":
            return {"ok": False, "alias": name,
                    "note": "macOS uses System Settings → General → Sharing → Local hostname"}
        if not shutil.which("bluetoothctl"):
            return {"ok": False, "alias": name, "error": "bluetoothctl not found"}
        _, show = cls._sh(["bluetoothctl", "show"], timeout=8)
        for line in show.splitlines():
            if line.strip().lower().startswith("alias:"):
                current = line.split(":", 1)[1].strip()
                if current == name:
                    return {"ok": True, "alias": name, "already_set": True}
                break
        try:
            import subprocess
            cls._bt_prepare_radio()
            r = subprocess.run(
                ["bluetoothctl"],
                input=f"power on\nsystem-alias {name}\nquit\n",
                capture_output=True,
                text=True,
                timeout=12,
            )
            out = (r.stdout or "") + (r.stderr or "")
            return {"ok": True, "alias": name, "output": out.strip()[:200]}
        except Exception as e:
            return {"ok": False, "alias": name, "error": str(e)}

    @classmethod
    def _bt_ensure_controller(cls) -> Tuple[bool, str]:
        """Select an available controller and power the radio on."""
        import re, shutil, sys
        if sys.platform != "linux" or not shutil.which("bluetoothctl"):
            return False, "bluetoothctl not found"
        _, out = cls._sh(["bluetoothctl", "list"], timeout=8)
        addrs = re.findall(r"Controller\s+([0-9A-Fa-f:]{17})", out or "")
        if not addrs:
            return False, "no Bluetooth controller — enable in system settings or replug USB adapter"
        for addr in addrs:
            cls._sh(["bluetoothctl", "select", addr], timeout=6)
            cls._sh(["bluetoothctl", "power", "on"], timeout=10)
            _, show = cls._sh(["bluetoothctl", "show"], timeout=8)
            if "powered: yes" in show.lower():
                return True, addr
        return False, "Bluetooth radio off"

    @classmethod
    def _bt_prepare_radio(cls) -> None:
        """Power on + pairable so outbound pairing to headphones works."""
        ok, _ = cls._bt_ensure_controller()
        if not ok:
            return
        try:
            import subprocess
            subprocess.run(
                ["bluetoothctl"],
                input="pairable on\ndiscoverable off\nquit\n",
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception:
            pass

    @classmethod
    def _device_in_cache(cls, addr: str) -> bool:
        _, listing = cls._sh(["bluetoothctl", "devices"], timeout=8)
        return addr.upper() in (listing or "").upper()

    @classmethod
    def _wait_for_bt_device(cls, addr: str, timeout: float = 18.0) -> bool:
        """Scan until BlueZ lists the device (headphones must be in pairing mode)."""
        import time
        addr_u = addr.upper()
        ok, _ = cls._bt_ensure_controller()
        if not ok:
            return False
        if cls._device_in_cache(addr_u):
            return True
        secs = max(8, min(int(timeout), 20))
        cls._sh(["bluetoothctl", "--timeout", str(secs), "scan", "on"], timeout=secs + 6)
        deadline = time.time() + secs
        while time.time() < deadline:
            if cls._device_in_cache(addr_u):
                cls._bt_ensure_controller()
                return True
            time.sleep(2)
        cls._bt_ensure_controller()
        return cls._device_in_cache(addr_u)

    @classmethod
    def _is_paired(cls, addr: str) -> bool:
        return cls._bt_device_info(addr).get("paired", "").lower() == "yes"

    @classmethod
    def _bt_device_info(cls, addr: str) -> Dict[str, Any]:
        _, out = cls._sh(["bluetoothctl", "info", addr], timeout=10)
        info: Dict[str, Any] = {"uuids": []}
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

    @classmethod
    def classify_bt_device(cls, info: Dict[str, Any], name: str = "") -> Dict[str, Any]:
        """Label printers/TVs/adapters/headphones so the UI routes audio correctly."""
        nm = (name or info.get("name") or info.get("alias") or "").lower()
        icon = (info.get("icon") or "").lower()
        uuids = [u.lower() for u in info.get("uuids") or []]

        is_printer = (
            any(x in nm for x in ("deskjet", "printer", "laserjet", "officejet", "envy"))
            or "printer" in icon
            or any("fdb4" in u or "fdf7" in u or "fe78" in u for u in uuids)
        )
        is_tv = "tv" in nm or "[tv]" in nm
        is_adapter = any(x in nm for x in ("hoco", "adapter", "dongle", "transmitter", "receiver"))
        has_sink = any("audio sink" in u or "0000110b" in u for u in uuids)
        has_headphones = any(x in icon for x in ("headset", "headphones", "audio-headphones"))

        if is_printer:
            return {"bt_type": "printer", "audio_capable": False, "label": "Printer"}
        if is_adapter:
            return {"bt_type": "adapter", "audio_capable": False, "label": "BT adapter (not headphones)"}
        if is_tv:
            return {"bt_type": "tv", "audio_capable": True, "label": "TV / speaker"}
        if has_headphones or (has_sink and not is_adapter):
            return {"bt_type": "headphones", "audio_capable": True, "label": "Headphones / audio"}
        if has_sink:
            return {"bt_type": "speaker", "audio_capable": True, "label": "Speaker"}
        return {"bt_type": "device", "audio_capable": False, "label": "Bluetooth device"}

    @classmethod
    def _pair_steps_for(cls, addr: str) -> List[str]:
        if cls._is_paired(addr):
            return ["trust", "connect"]
        return ["pair", "trust", "connect"]

    @staticmethod
    def _parse_bt_ok(out: str) -> bool:
        low = (out or "").lower()
        if "authentication failed" in low or "org.bluez.error" in low:
            return False
        if ("failed to pair" in low or "failed to connect" in low) and "connection successful" not in low:
            return False
        if "connection successful" in low or "already connected" in low:
            return True
        if "paired: yes" in low or "connected: yes" in low or "changing" in low:
            return True
        return False

    @staticmethod
    def _bt_error_hint(out: str, action: str) -> str:
        low = (out or "").lower()
        if "authentication failed" in low or "rejected" in low:
            return "Pairing rejected — accept the prompt on the device, then tap Pair again"
        if "failed to connect" in low or "br-connection" in low:
            return "Could not connect — put headphones in pairing mode (LED flashing), then tap Pair"
        if "not available" in low:
            return "Device not in range — open the headphones case / hold power until LED flashes, then Pair again"
        if action == "pair":
            return ("Pairing did not finish — keep headphones in pairing mode (LED flashing), "
                    "then tap Pair again (scan takes ~15s)")
        if action == "connect":
            return "Connect failed — tap Pair first (headphones: pairing mode with LED flashing)"
        tail = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
        return (tail[-1][:140] if tail else "Bluetooth command failed")

    @staticmethod
    def _btctl_batch(addr: str, steps: List[str], timeout: float = 45.0, agent: str = "NoInputNoOutput"):
        """Run bluetoothctl with a pairing agent (headphones: NoInputNoOutput, TVs: DisplayYesNo)."""
        import subprocess
        BluetoothDriver._bt_ensure_controller()
        alias_name = BluetoothDriver.resolve_adapter_alias()
        script = "\n".join([
            f"agent {agent}",
            "default-agent",
            "power on",
            "pairable on",
            "discoverable off",
            f"system-alias {alias_name}",
            *[f"{step} {addr}" for step in steps],
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
            return BluetoothDriver._parse_bt_ok(out), out
        except FileNotFoundError:
            return False, "bluetoothctl not found"
        except Exception as e:
            return False, str(e)

    def _find_bt_sink(self, addr: str) -> Optional[str]:
        token = addr.replace(":", "_").upper()
        _, sinks = self._sh(["pactl", "list", "short", "sinks"])
        for line in sinks.splitlines():
            if token in line.upper() and "bluez" in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
        return None

    def _bt_action(self, addr, action):
        import shutil, sys
        if sys.platform == "darwin":
            if not shutil.which("blueutil"):
                return {"ok": False, "error": "bluetooth on macOS needs blueutil (brew install blueutil)"}
            flag = {"connect": "--connect", "disconnect": "--disconnect",
                    "pair": "--pair", "trust": "--connect"}[action]
            rc, out = self._sh(["blueutil", flag, addr])
            ok = rc == 0
            res = {"ok": ok, "command": action, "device": addr, "output": out[:300]}
            if not ok:
                res["error"] = out.strip()[:200] or "bluetooth command failed"
            return res
        if not shutil.which("bluetoothctl"):
            if sys.platform.startswith("win"):
                return {"ok": False, "error": "bluetooth control on Windows isn't wired yet (roadmap)"}
            return {"ok": False, "error": "bluetooth: bluetoothctl not found (install bluez)"}
        self.ensure_adapter_alias()
        self._bt_prepare_radio()
        if action == "disconnect":
            rc, out = self._sh(["bluetoothctl", "disconnect", addr], timeout=25)
            ok = rc == 0 or "successful" in out.lower() or "disconnected" in out.lower()
        elif action == "pair":
            info = self._bt_device_info(addr)
            meta = self.classify_bt_device(info, str(info.get("name") or ""))
            if meta.get("bt_type") == "printer":
                return {"ok": False, "error": "That is a printer — not pairable for audio"}
            if meta.get("bt_type") == "adapter":
                return {"ok": False, "error": "That is a Bluetooth adapter/dongle — pair your headphones instead"}
            dev_name = str(info.get("name") or info.get("alias") or "headphones")
            if not self._is_paired(addr) and not self._wait_for_bt_device(addr, timeout=18.0):
                return {
                    "ok": False,
                    "error": f"{dev_name} not found — keep them in pairing mode (LED flashing) and tap Pair",
                }
            steps = self._pair_steps_for(addr)
            agents = (["DisplayYesNo", "NoInputNoOutput"] if meta.get("bt_type") == "tv"
                      else ["NoInputNoOutput", "DisplayYesNo"])
            ok, out = False, ""
            for agent in agents:
                ok, out = self._btctl_batch(addr, steps, timeout=90.0, agent=agent)
                if ok or self._is_paired(addr):
                    ok = True
                    break
            if ok and "connect" in steps:
                self._btctl_batch(addr, ["connect"], timeout=45.0)
        else:
            steps = {"connect": ["connect"], "trust": ["trust"]}[action]
            ok, out = self._btctl_batch(addr, steps, timeout=45.0)
        res = {"ok": ok, "command": action, "device": addr, "output": out.strip()[:400]}
        if not ok:
            res["error"] = self._bt_error_hint(out, action)
        return res

    def _route_audio(self, addr):
        """Make this Bluetooth device the system audio output (Linux PulseAudio/PipeWire)."""
        import shutil, sys, time
        if sys.platform == "darwin":
            if shutil.which("SwitchAudioSource"):
                rc, out = self._sh(["SwitchAudioSource", "-t", "output", "-s", addr])
                ok = rc == 0
                res = {"ok": ok, "routed": ok, "output": out[:200]}
                if not ok:
                    res["error"] = out.strip()[:200] or "audio routing failed"
                return res
            return {"ok": False, "error": "macOS audio routing needs switchaudio-osx (brew install switchaudio-osx)"}
        if not shutil.which("pactl"):
            return {"ok": False, "error": "audio routing needs PulseAudio/PipeWire (pactl not found)"}
        sink = self._find_bt_sink(addr)
        if not sink:
            conn = self._bt_action(addr, "connect")
            if not conn.get("ok"):
                conn = self._bt_action(addr, "pair")
            if not conn.get("ok"):
                return {
                    "ok": False,
                    "error": conn.get("error") or "Could not connect — tap Pair, accept on the TV, then Use for audio",
                    "output": conn.get("output", ""),
                }
            for _ in range(20):
                sink = self._find_bt_sink(addr)
                if sink:
                    break
                time.sleep(0.5)
        if not sink:
            return {
                "ok": False,
                "error": "No Bluetooth audio output for this device — connect first, or use HDMI / a speaker",
            }
        rc, _ = self._sh(["pactl", "set-default-sink", sink])
        _, inputs = self._sh(["pactl", "list", "short", "sink-inputs"])
        for line in inputs.splitlines():
            parts = line.split()
            if parts:
                self._sh(["pactl", "move-sink-input", parts[0], sink])
        ok = rc == 0
        res = {"ok": ok, "routed": ok, "sink": sink, "device": addr}
        if not ok:
            res["error"] = "Could not set default audio output"
        return res


# ─────────────────────────────────────────────────────────────────────────────
# Registry + on-demand install
# ─────────────────────────────────────────────────────────────────────────────
_DRIVERS: Dict[str, Driver] = {
    d.name: d for d in (UpnpDriver(), CastDriver(), FireTVDriver(), AirPlayDriver(),
                        BluetoothDriver())
}


def get_driver(name: str) -> Optional[Driver]:
    return _DRIVERS.get((name or "").lower())


def driver_status() -> List[Dict[str, Any]]:
    """For the dashboard: every non-MQTT driver, whether its library is installed, and how
    it pairs — so the UI can show Install / Pair / Ready states."""
    out = []
    for d in _DRIVERS.values():
        ok, msg = d.available()
        out.append({"name": d.name, "label": d.label, "pip": d.pip,
                    "installed": ok, "needs_pairing": d.needs_pairing,
                    "pair_style": d.pair_style, "detail": msg})
    return out


def install_driver(name: str, timeout: float = 600.0) -> Dict[str, Any]:
    """One-click, on-demand install of a driver's library into ELI's OWN venv. Admin-gated
    at the API layer. Returns the pip outcome. We deliberately install only the specific,
    documented package for the driver the user chose — nothing else changes."""
    d = get_driver(name)
    if not d:
        return {"ok": False, "error": f"unknown driver {name!r}"}
    if not d.pip:
        return {"ok": True, "installed": True, "note": "no dependency needed"}
    ok, _ = d.available()
    if ok:
        return {"ok": True, "installed": True, "note": "already installed"}
    pip_target = d.pip
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_target],
            capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return {"ok": False, "error": f"install failed: {e}"}
    ok_now, _ = d.available()
    if proc.returncode == 0 and ok_now:
        return {"ok": True, "installed": True, "package": pip_target}
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
    return {"ok": False, "error": "pip install did not complete",
            "package": pip_target, "log": "\n".join(tail)}


def adb_available() -> bool:
    """Optional: the system `adb` binary makes Fire TV pairing more robust, but androidtv's
    pure-python adb works without it. Surfaced as a hint only."""
    return shutil.which("adb") is not None
