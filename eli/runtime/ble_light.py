"""BLE light control — the GATT writes ELI never had.

`BluetoothDriver.control` maps ``on`` to ``connect`` and ``off`` to
``disconnect``. That is Bluetooth *link* management: it establishes or drops a
connection and leaves the bulb exactly as it was, while reporting success. A BLE
bulb is only switched by writing a vendor payload to a GATT characteristic, and
before this module there was no `write_gatt_char` anywhere in the codebase.

**Discovery first, not a guess.** Cheap BLE bulbs are a handful of reference
designs rebadged endlessly, and the same shell ships with different firmware.
Hardcoding one vendor's payload gets it wrong for most bulbs and — worse —
reports success either way, because a GATT write to a characteristic that
ignores it still "succeeds" at the protocol level. So this connects, reads the
characteristic table the bulb actually exposes, and only then picks a protocol
whose write characteristic is genuinely present. A bulb matching nothing known
is reported as unsupported *with its characteristic list*, so the next person
can add it, rather than being silently failed at.

What this module does NOT claim: that the light visibly changed. GATT gives no
read-back on these bulbs. `set_power` reports the write it performed and the
protocol it matched — never "the light is on".
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from eli.utils.log import get_logger

log = get_logger(__name__)

# Bluetooth base UUID — 16-bit IDs are expanded into this for comparison.
_BASE = "-0000-1000-8000-00805f9b34fb"


def _u(short: str) -> str:
    """0xFFE9 → the full 128-bit UUID string, lowercased."""
    return f"0000{short.lower()}{_BASE}"


@dataclass(frozen=True)
class BleLightProtocol:
    """One bulb protocol family: where to write, and what."""

    name: str
    write_chars: Sequence[str]          # candidate characteristic UUIDs, best first
    on: bytes
    off: bytes
    #: brightness/colour builders are optional — many bulbs only do power well
    rgb: Optional[str] = None           # format key, see _rgb_payload
    notes: str = ""


# Families are matched by the characteristic the bulb actually exposes, so the
# order here is a tiebreak, not an assumption about which bulb you own.
PROTOCOLS: List[BleLightProtocol] = [
    BleLightProtocol(
        name="triones",
        write_chars=(_u("ffe9"), _u("ffe1")),
        on=bytes.fromhex("cc2333"),
        off=bytes.fromhex("cc2433"),
        rgb="triones",
        notes="Triones / Happy Lighting / many Magic-Home clones (service 0xffe5).",
    ),
    BleLightProtocol(
        name="elk-bledom",
        write_chars=(_u("fff3"),),
        on=bytes.fromhex("7e0004f0000100ef"),
        off=bytes.fromhex("7e000400000000ef"),
        rgb="bledom",
        notes="ELK-BLEDOM strip controllers (service 0xfff0).",
    ),
    BleLightProtocol(
        name="zengge",
        write_chars=(_u("ffd9"),),
        on=bytes.fromhex("cc2333"),
        off=bytes.fromhex("cc2433"),
        rgb="triones",
        notes="Zengge / LEDnet variants reusing the Triones frame on 0xffd9.",
    ),
]

#: Characteristic property that lets us write at all.
_WRITABLE = ("write", "write-without-response")


@dataclass
class BleProbe:
    """What a bulb turned out to expose."""

    address: str
    name: str = ""
    connected: bool = False
    services: Dict[str, List[str]] = field(default_factory=dict)   # service → chars
    writable: List[str] = field(default_factory=list)
    protocol: Optional[BleLightProtocol] = None
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "connected": self.connected,
            "services": self.services,
            "writable_characteristics": self.writable,
            "protocol": self.protocol.name if self.protocol else None,
            "error": self.error,
        }


def _rgb_payload(fmt: str, r: int, g: int, b: int) -> Optional[bytes]:
    r, g, b = (max(0, min(255, int(v))) for v in (r, g, b))
    if fmt == "triones":
        return bytes([0x56, r, g, b, 0x00, 0xF0, 0xAA])
    if fmt == "bledom":
        return bytes([0x7E, 0x00, 0x05, 0x03, r, g, b, 0x00, 0xEF])
    return None


def _match_protocol(writable: Sequence[str]) -> Optional[BleLightProtocol]:
    """Pick the family whose write characteristic this bulb actually has."""
    have = {c.lower() for c in writable}
    for proto in PROTOCOLS:
        for cand in proto.write_chars:
            if cand.lower() in have:
                return proto
    return None


async def _probe(address: str, timeout: float) -> BleProbe:
    out = BleProbe(address=address)
    try:
        from bleak import BleakClient, BleakScanner
    except Exception as exc:  # pragma: no cover - optional dependency
        out.error = f"bleak not installed ({exc}) — pip install bleak"
        return out

    try:
        dev = await BleakScanner.find_device_by_address(address, timeout=timeout)
    except Exception as exc:
        out.error = f"scan failed: {exc}"
        return out
    if dev is None:
        # The commonest real case by far, and worth saying plainly: an unplugged
        # or sleeping bulb is indistinguishable from a broken one otherwise.
        out.error = ("not advertising — the bulb is powered off, out of range, or "
                     "already connected to another device")
        return out

    out.name = getattr(dev, "name", "") or ""
    try:
        async with BleakClient(dev, timeout=timeout) as client:
            out.connected = bool(client.is_connected)
            for svc in client.services:
                chars = []
                for ch in svc.characteristics:
                    chars.append(ch.uuid)
                    if any(p in ch.properties for p in _WRITABLE):
                        out.writable.append(ch.uuid)
                out.services[svc.uuid] = chars
    except Exception as exc:
        out.error = f"connect failed: {exc}"
        return out

    out.protocol = _match_protocol(out.writable)
    if out.protocol is None and out.writable:
        out.error = ("connected, but no known light protocol matches its writable "
                     "characteristics — see writable_characteristics")
    return out


def probe(address: str, timeout: float = 20.0) -> dict:
    """Connect and report what the bulb exposes. Never raises."""
    try:
        return asyncio.run(_probe(address, timeout)).as_dict()
    except Exception as exc:
        return BleProbe(address=address, error=f"probe failed: {exc}").as_dict()


async def _write(address: str, payload: bytes, timeout: float) -> dict:
    probe_result = await _probe(address, timeout)
    if probe_result.error and not probe_result.protocol:
        return {"ok": False, "error": probe_result.error, "probe": probe_result.as_dict()}
    proto = probe_result.protocol
    if proto is None:
        return {"ok": False, "error": "no known BLE light protocol on this device",
                "probe": probe_result.as_dict()}

    target = next((c for c in proto.write_chars
                   if c.lower() in {w.lower() for w in probe_result.writable}), None)
    from bleak import BleakClient, BleakScanner
    dev = await BleakScanner.find_device_by_address(address, timeout=timeout)
    if dev is None:
        return {"ok": False, "error": "device stopped advertising between probe and write"}
    try:
        async with BleakClient(dev, timeout=timeout) as client:
            await client.write_gatt_char(target, payload, response=False)
    except Exception as exc:
        return {"ok": False, "error": f"GATT write failed: {exc}",
                "protocol": proto.name, "characteristic": target}
    # Deliberately not "the light is on": these bulbs give no read-back, so the
    # only honest claim is which bytes went where.
    return {"ok": True, "protocol": proto.name, "characteristic": target,
            "wrote": payload.hex(), "verified": False,
            "note": "command written; BLE bulbs report no state back, so this is "
                    "not a confirmation the light changed"}


def set_power(address: str, on: bool, timeout: float = 20.0) -> dict:
    """Switch a BLE bulb on or off. Never raises."""
    try:
        proto_probe = asyncio.run(_probe(address, timeout))
        if proto_probe.protocol is None:
            return {"ok": False,
                    "error": proto_probe.error or "no known BLE light protocol",
                    "probe": proto_probe.as_dict()}
        payload = proto_probe.protocol.on if on else proto_probe.protocol.off
        return asyncio.run(_write(address, payload, timeout))
    except Exception as exc:
        return {"ok": False, "error": f"ble light control failed: {exc}"}


def set_rgb(address: str, r: int, g: int, b: int, timeout: float = 20.0) -> dict:
    """Set colour, when the matched protocol supports it. Never raises."""
    try:
        proto_probe = asyncio.run(_probe(address, timeout))
        proto = proto_probe.protocol
        if proto is None:
            return {"ok": False,
                    "error": proto_probe.error or "no known BLE light protocol",
                    "probe": proto_probe.as_dict()}
        if not proto.rgb:
            return {"ok": False, "error": f"{proto.name} has no colour frame in this driver"}
        payload = _rgb_payload(proto.rgb, r, g, b)
        if payload is None:
            return {"ok": False, "error": f"unknown colour format {proto.rgb!r}"}
        return asyncio.run(_write(address, payload, timeout))
    except Exception as exc:
        return {"ok": False, "error": f"ble colour control failed: {exc}"}


def is_ble_address(value: str) -> bool:
    """True for AA:BB:CC:DD:EE:FF — how BLE devices are identified in the registry."""
    parts = str(value or "").split(":")
    return len(parts) == 6 and all(len(p) == 2 and all(c in "0123456789abcdefABCDEF" for c in p)
                                   for p in parts)
