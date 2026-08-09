"""Locks on BLE light control — the GATT writes that did not exist.

`BluetoothDriver.control` maps ``on``→``connect`` and ``off``→``disconnect``,
which is Bluetooth *link* management: it opens or drops a connection, leaves the
bulb exactly as it was, and reports success. Before `ble_light`, there was no
`write_gatt_char` anywhere in the codebase, so ELI could not switch a BLE bulb at
all while appearing to.

The design constraint that shapes these tests: a GATT write to a characteristic
the bulb ignores still "succeeds" at the protocol level, and these bulbs report
no state back. So the driver must (a) pick a protocol from what the device
actually exposes rather than assume a vendor, and (b) never claim the light
changed — only which bytes it wrote where.
"""
import pytest

from eli.runtime import ble_light
from eli.runtime.ble_light import PROTOCOLS, _match_protocol, _rgb_payload, _u, is_ble_address


# ── addressing ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("addr,expected", [
    ("AC:15:18:17:93:0E", True),
    ("ac:15:18:17:93:0e", True),
    ("kitchen_lamp", False),
    ("192.168.1.50", False),
    ("", False),
    ("AC:15:18:17:93", False),
])
def test_ble_address_detection(addr, expected):
    assert is_ble_address(addr) is expected


# ── protocol is chosen from what the bulb exposes ───────────────────────────
@pytest.mark.parametrize("char,expected", [
    ("ffe9", "triones"),
    ("fff3", "elk-bledom"),
    ("ffd9", "zengge"),
])
def test_protocol_matched_from_characteristics(char, expected):
    assert _match_protocol([_u(char)]).name == expected


def test_unknown_bulb_matches_nothing():
    """Guessing a protocol is worse than admitting none fits: the write would
    'succeed' and the light would not move."""
    assert _match_protocol([_u("1234"), _u("abcd")]) is None


def test_matching_is_case_insensitive():
    assert _match_protocol([_u("FFE9").upper()]) is not None


def test_every_protocol_has_distinct_on_and_off():
    for p in PROTOCOLS:
        assert p.on and p.off and p.on != p.off, f"{p.name} on/off payloads are unusable"


def test_every_protocol_declares_a_write_characteristic():
    for p in PROTOCOLS:
        assert p.write_chars, f"{p.name} has nowhere to write"


# ── colour frames ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("fmt", ["triones", "bledom"])
def test_rgb_payload_encodes_the_channels(fmt):
    payload = _rgb_payload(fmt, 10, 20, 30)
    assert payload is not None
    assert 10 in payload and 20 in payload and 30 in payload


def test_rgb_channels_are_clamped():
    """A caller passing 300 or -5 must not corrupt the frame."""
    payload = _rgb_payload("triones", 300, -5, 128)
    assert payload is not None
    assert all(0 <= b <= 255 for b in payload)


def test_unknown_colour_format_returns_none():
    assert _rgb_payload("nonesuch", 1, 2, 3) is None


# ── honesty: never claim the light moved ────────────────────────────────────
def test_absent_bulb_fails_loudly_not_silently(monkeypatch):
    """The old path reported success for a bulb that never received anything."""
    monkeypatch.setattr(ble_light, "_probe", _fake_probe_absent)

    res = ble_light.set_power("AC:15:18:17:93:0E", True)

    assert res["ok"] is False
    assert "advertising" in res["error"] or "powered off" in res["error"]


def test_unmatched_bulb_reports_its_characteristics(monkeypatch):
    """So the next person can add the protocol instead of guessing again."""
    monkeypatch.setattr(ble_light, "_probe", _fake_probe_unmatched)

    res = ble_light.set_power("AC:15:18:17:93:0E", False)

    assert res["ok"] is False
    assert res["probe"]["writable_characteristics"], "must surface what it did expose"


def test_probe_never_raises_on_a_bad_address():
    out = ble_light.probe("not-an-address", timeout=0.1)
    assert out["error"], "probe must report, not raise"


def test_set_power_never_raises():
    out = ble_light.set_power("not-an-address", True, timeout=0.1)
    assert out["ok"] is False and out["error"]


# ── helpers ─────────────────────────────────────────────────────────────────
async def _fake_probe_absent(address, timeout):
    return ble_light.BleProbe(
        address=address,
        error="not advertising — the bulb is powered off, out of range, or "
              "already connected to another device",
    )


async def _fake_probe_unmatched(address, timeout):
    p = ble_light.BleProbe(address=address, connected=True)
    p.writable = [_u("1234")]
    p.error = "connected, but no known light protocol matches"
    return p
