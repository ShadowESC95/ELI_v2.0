"""Ollama host handling: scheme-less hosts, custom ports, IPv6 fallback, LAN access.

Ollama's own docs/installers set OLLAMA_HOST without a scheme ("127.0.0.1:11434"),
and users type "localhost:11434" into the host box. urllib rejects both with
"unknown url type", which silently broke Ollama support on every OS.
"""
from __future__ import annotations

import pytest

from eli.integrations.ollama import client


@pytest.mark.parametrize("raw,expected", [
    # Ollama's own documented env form — the reported breakage
    ("127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("0.0.0.0:11434", "http://0.0.0.0:11434"),
    # what users actually type
    ("localhost:11434", "http://localhost:11434"),
    ("localhost", "http://localhost:11434"),
    ("192.168.1.5", "http://192.168.1.5:11434"),
    ("192.168.1.5:11434", "http://192.168.1.5:11434"),
    # custom port must survive
    ("10.0.0.7:1234", "http://10.0.0.7:1234"),
    ("http://box.lan:9999", "http://box.lan:9999"),
    # already-valid input is untouched (bar the trailing slash)
    ("http://localhost:11434/", "http://localhost:11434"),
    ("https://ollama.box.lan", "https://ollama.box.lan:11434"),
    # IPv6 literal keeps its brackets and is not mistaken for host:port
    ("[::1]:11434", "http://[::1]:11434"),
    ("[2001:db8::1]", "http://[2001:db8::1]:11434"),
    # whitespace / empty
    ("  10.0.0.7:1234  ", "http://10.0.0.7:1234"),
    ("", client.DEFAULT_HOST),
    (None, client.DEFAULT_HOST),
])
def test_normalise_host(raw, expected):
    assert client.normalise_host(raw) == expected


def test_env_host_without_scheme_is_usable(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    assert client._host() == "http://127.0.0.1:11434"


def test_configured_host_without_scheme_is_usable(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(client, "_host", lambda: client.normalise_host("box.lan:9999"))
    assert client.candidate_hosts()[0] == "http://box.lan:9999"


def test_localhost_falls_back_to_ipv4():
    """localhost resolves to ::1 first on many Windows boxes while Ollama binds
    IPv4 — without this fallback that reads as 'Ollama is not running'."""
    assert client.candidate_hosts("localhost:11434") == [
        "http://localhost:11434", "http://127.0.0.1:11434"]


def test_explicit_ipv4_has_no_redundant_fallback():
    assert client.candidate_hosts("127.0.0.1:11434") == ["http://127.0.0.1:11434"]


def test_custom_port_is_preserved_in_fallback():
    assert client.candidate_hosts("localhost:9999") == [
        "http://localhost:9999", "http://127.0.0.1:9999"]


def test_lan_host_is_registered_with_netguard():
    """Ollama on another machine is a deliberate local service, not internet access;
    offline-by-default previously blocked it with no explanation."""
    from eli.core import netguard
    host = "192.168.77.88"
    netguard.unregister_local_service(host)
    client._registered_hosts.discard(f"http://{host}:11434")
    assert not netguard._is_local_host(host)
    client._allow_via_netguard(f"http://{host}:11434")
    assert netguard._is_local_host(host)
    netguard.unregister_local_service(host)


def test_install_hint_is_os_specific(monkeypatch):
    import sys as _sys
    for plat, needle in (("darwin", "brew"), ("win32", "Start menu"), ("linux", "systemctl")):
        monkeypatch.setattr(_sys, "platform", plat)
        assert needle in client.install_hint()


def test_gui_query_normalises_the_same_way(monkeypatch):
    """The startup picker/wizard must accept exactly what the client accepts."""
    try:
        from eli.gui.panels import startup
    except Exception as exc:  # Qt bindings are stubbed in the headless test env
        pytest.skip(f"GUI panels unavailable here: {exc}")
    seen = []

    def fake_urlopen(url, timeout=0):
        seen.append(url)
        raise OSError("no server")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    names, err = startup._query_ollama_tags("localhost:11434", timeout=1)
    assert names is None and err is not None
    assert seen and seen[0] == "http://localhost:11434/api/tags"
