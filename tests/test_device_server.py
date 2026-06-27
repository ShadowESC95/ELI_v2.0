"""Unit tests: ELI's own MQTT device server (eli.runtime.device_server).

ELI keeps its own device registry and talks to devices over MQTT — no Home Assistant.
Verifies: manual registration + persistence, control publishes the right MQTT payload,
standard MQTT discovery auto-registers a device, a state message updates it, and
connecting registers the broker host with netguard (so the offline socket guard permits
that host only).

paho-mqtt is faked in-process, so the test runs without a broker or the real library.
"""
import json
import sys
import types

import pytest


@pytest.fixture()
def fake_paho(monkeypatch):
    published = []

    class CB:
        VERSION1 = "v1"

    class Client:
        def __init__(self, *a, **k):
            self.on_connect = self.on_message = self.on_disconnect = None

        def username_pw_set(self, *a, **k): pass
        def tls_set(self, *a, **k): pass
        def connect_async(self, *a, **k): pass
        def loop_start(self):
            if self.on_connect:
                self.on_connect(self, None, None, 0)
        def loop_stop(self): pass
        def disconnect(self): pass
        def subscribe(self, t): pass
        def publish(self, topic, payload): published.append((topic, payload))

    paho = types.ModuleType("paho")
    mqtt = types.ModuleType("paho.mqtt")
    client = types.ModuleType("paho.mqtt.client")
    client.Client = Client
    client.CallbackAPIVersion = CB
    mqtt.client = client
    paho.mqtt = mqtt
    monkeypatch.setitem(sys.modules, "paho", paho)
    monkeypatch.setitem(sys.modules, "paho.mqtt", mqtt)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", client)
    return published


@pytest.fixture()
def server(tmp_path, monkeypatch):
    import eli.runtime.device_server as ds
    # Isolate the registry file and the config store so tests never touch the real
    # artifacts/ registry or settings.json (and can't pollute each other).
    regfile = tmp_path / "registry.json"
    monkeypatch.setattr(ds, "_registry_path", lambda: regfile)
    store = {}
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(cfg, "set", lambda k, v: store.__setitem__(k, v))
    # netguard's local-service allowlist is a process global — clear it so each test
    # starts with a clean slate (broker registration is asserted per-test).
    from eli.core import netguard
    netguard._LOCAL_SERVICES.clear()
    return ds.DeviceServer()


def test_manual_register_and_persist(server, tmp_path):
    r = server.register_device(device_id="lamp1", name="Desk Lamp", dtype="light",
                               command_topic="home/lamp/set", state_topic="home/lamp/state")
    assert r["ok"]
    ids = [d["id"] for d in server.list_devices()]
    assert "lamp1" in ids
    # persisted to disk
    reg = tmp_path / "registry.json"
    assert reg.exists() and "lamp1" in json.loads(reg.read_text())


def test_control_publishes_payload(server, fake_paho):
    server.register_device(device_id="lamp1", dtype="light",
                           command_topic="home/lamp/set", state_topic="home/lamp/state")
    server.configure(host="192.168.1.50", port=1883)
    assert server.connect()["ok"]
    assert server.control("lamp1", "on")["ok"]
    assert fake_paho[-1] == ("home/lamp/set", "ON")
    server.control("lamp1", "off")
    assert fake_paho[-1] == ("home/lamp/set", "OFF")


def test_control_unknown_device(server, fake_paho):
    server.configure(host="192.168.1.50")
    server.connect()
    r = server.control("nope", "on")
    assert r["ok"] is False and "unknown" in r["error"]


def test_discovery_registers_device(server, fake_paho, monkeypatch):
    server.configure(host="192.168.1.50", discovery_prefix="homeassistant")
    server.connect()

    class M:
        topic = "homeassistant/switch/boiler/config"
        payload = json.dumps({"name": "Boiler", "unique_id": "boiler1",
                              "command_topic": "home/boiler/set",
                              "state_topic": "home/boiler/state"}).encode()
    server._on_message(None, None, M())
    ids = [d["id"] for d in server.list_devices()]
    assert "boiler1" in ids


def test_state_message_updates_device(server, fake_paho):
    server.register_device(device_id="lamp1", dtype="light",
                           command_topic="home/lamp/set", state_topic="home/lamp/state")
    server.configure(host="192.168.1.50")
    server.connect()

    class S:
        topic = "home/lamp/state"
        payload = b"ON"
    server._on_message(None, None, S())
    dev = [d for d in server.list_devices() if d["id"] == "lamp1"][0]
    assert dev["state"] == "ON"


def test_connect_registers_broker_with_netguard(server, fake_paho):
    from eli.core import netguard
    server.configure(host="192.168.1.50", port=1883)
    assert netguard._is_local_host("192.168.1.50") is False
    server.connect()
    assert netguard._is_local_host("192.168.1.50") is True
    # an unrelated LAN host is still blocked — only the configured broker opened up
    assert netguard._is_local_host("10.9.9.9") is False


def test_no_broker_configured_degrades(server):
    r = server.connect()
    assert r["ok"] is False and "broker" in r["error"]
