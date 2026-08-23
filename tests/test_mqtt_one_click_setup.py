"""Behaviour locks for MQTT device setup.

Reported: "the mqtt on the server is not advanced enough, and not
connecting/searching properly, and it needs to be simple to use for average
user, one click etc."

What was actually there:
  * DeviceServer.connect() returned "no MQTT broker configured (set mqtt_host)"
    whenever the user had not typed a hostname into settings by hand. That is
    a dead end for anyone who does not know what MQTT is.
  * suggest_local_hosts() existed but nothing in the codebase ever called it.
  * There was no mDNS discovery at all, despite zeroconf already being a
    pinned dependency - so a broker advertising itself on the LAN was invisible.
  * There was no single entry point that goes from nothing to working.
"""
import inspect
from pathlib import Path

import pytest

from eli.runtime import mqtt_setup
from eli.runtime import device_server


# ── discovery ──────────────────────────────────────────────────────────────
def test_mdns_discovery_exists():
    assert hasattr(mqtt_setup, "discover_brokers_mdns")
    src = inspect.getsource(mqtt_setup.discover_brokers_mdns)
    assert "_mqtt._tcp" in src, "does not browse the standard MQTT service type"


def test_mdns_discovery_never_raises_without_zeroconf(monkeypatch):
    """Discovery is best-effort: a missing or broken zeroconf must degrade to
    'found nothing', never take the setup flow down with it."""
    import builtins
    real_import = builtins.__import__

    def _no_zeroconf(name, *a, **k):
        if name == "zeroconf":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_zeroconf)
    assert mqtt_setup.discover_brokers_mdns(timeout=0.1) == []


def test_autodetect_probes_rather_than_assuming(monkeypatch):
    """An open port is not a broker. A candidate only counts once a broker has
    actually accepted a connection."""
    monkeypatch.setattr(mqtt_setup, "discover_brokers_mdns", lambda timeout=2.0: [])
    probed = []

    def _probe(*, host, port=1883, username="", password="", tls=False, timeout=5.0):
        probed.append(host)
        return {"ok": host == "mqtt.local", "host": host, "port": port}

    monkeypatch.setattr(mqtt_setup, "probe_broker_connection", _probe)
    res = mqtt_setup.autodetect_broker(timeout=0.1)
    assert res["ok"] is True
    assert res["broker"]["host"] == "mqtt.local"
    assert probed, "nothing was probed"


def test_autodetect_prefers_mdns_over_guesswork(monkeypatch):
    monkeypatch.setattr(mqtt_setup, "discover_brokers_mdns",
                        lambda timeout=2.0: [{"host": "10.0.0.5", "port": 1883,
                                              "name": "hub", "tls": False,
                                              "source": "mdns"}])
    monkeypatch.setattr(mqtt_setup, "probe_broker_connection",
                        lambda **kw: {"ok": True, "host": kw["host"], "port": kw["port"]})
    res = mqtt_setup.autodetect_broker(timeout=0.1)
    assert res["broker"]["host"] == "10.0.0.5"
    assert res["broker"]["source"] == "mdns"


def test_autodetect_reports_what_it_tried(monkeypatch):
    """A silent 'not found' gives the user nothing to act on."""
    monkeypatch.setattr(mqtt_setup, "discover_brokers_mdns", lambda timeout=2.0: [])
    monkeypatch.setattr(mqtt_setup, "probe_broker_connection",
                        lambda **kw: {"ok": False, "error": "refused"})
    res = mqtt_setup.autodetect_broker(timeout=0.1)
    assert res["ok"] is False
    assert res["tried"], "no record of what was attempted"
    assert all("host" in t for t in res["tried"])


# ── one-click ──────────────────────────────────────────────────────────────
def test_one_click_setup_exists():
    assert hasattr(mqtt_setup, "one_click_setup")


def test_one_click_without_a_broker_returns_the_install_step(monkeypatch):
    """When there is genuinely no broker, 'install one' IS the single next
    step, so the guide has to come back with the failure."""
    monkeypatch.setattr(mqtt_setup, "autodetect_broker",
                        lambda timeout=2.0: {"ok": False, "error": "none", "tried": []})
    res = mqtt_setup.one_click_setup(timeout=0.1)
    assert res["ok"] is False
    assert res["found"] is False
    assert res.get("guide"), "no install guide offered"
    assert "broker" in str(res.get("content", "")).lower()


def test_one_click_explains_mqtt_in_plain_language(monkeypatch):
    """The audience is someone who does not know the word 'broker'."""
    monkeypatch.setattr(mqtt_setup, "autodetect_broker",
                        lambda timeout=2.0: {"ok": False, "error": "none", "tried": []})
    text = str(mqtt_setup.one_click_setup(timeout=0.1).get("content", ""))
    assert "smart devices" in text.lower(), "no plain-language explanation"


# ── connect() must configure itself ────────────────────────────────────────
def _code_only(src: str) -> str:
    """Source with whole-line comments removed -- a structural check must read
    code, not the comment quoting the old broken behaviour."""
    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))


def test_connect_autodetects_when_nothing_is_configured():
    src = _code_only(inspect.getsource(device_server.DeviceServer.connect))
    assert "autodetect_broker" in src, "connect() still dead-ends on an unset mqtt_host"
    assert "set mqtt_host" not in src, "the dead-end error message is back"


def test_connect_autodetect_can_be_turned_off():
    """Callers that manage configuration themselves must be able to opt out."""
    sig = inspect.signature(device_server.DeviceServer.connect)
    assert "autodetect" in sig.parameters
    assert sig.parameters["autodetect"].default is True


def test_setup_endpoint_is_exposed():
    src = Path("api/server.py").read_text(encoding="utf-8")
    assert "/v1/devices/setup" in src, "no one-click endpoint on the API surface"
    assert "one_click_setup" in src
