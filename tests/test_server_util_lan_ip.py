"""resolve_lan_ip() must pick the phone-reachable LAN IP, not a virtual bridge.

Reported: "qr codes for the web server are broken for some reason." Traced to
`resolve_lan_ip()`'s tie-break: every 192.168.x.x candidate scored identically
(4), so a hypervisor/container virtual bridge in that same private range (most
commonly libvirt/KVM's default NAT bridge, 192.168.122.1, present on any
machine with KVM installed) could tie with the real Wi-Fi/Ethernet IP and win
purely on which candidate-source happened to run first — order that isn't
guaranteed (it depends on whether the UDP-connect-to-8.8.8.8 trick succeeds,
which needs an internet route and can fail on a LAN-only/air-gapped network).
A QR encoding a virtual bridge address is one no phone on the Wi-Fi can reach.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from eli.runtime import server_util


def _fake_udp_socket(getsockname_ip: str):
    sock = MagicMock()
    sock.getsockname.return_value = (getsockname_ip, 0)
    return sock


def test_prefers_real_lan_ip_over_libvirt_bridge_even_when_bridge_seen_first():
    # hostname -I lists the libvirt bridge BEFORE the real Wi-Fi IP -- the
    # exact ordering that let the virtual bridge win the old tie-break.
    with patch("socket.gethostbyname", return_value="192.168.122.1"), \
         patch("socket.socket", return_value=_fake_udp_socket("192.168.122.1")), \
         patch(
             "subprocess.run",
             return_value=subprocess.CompletedProcess(
                 args=["hostname", "-I"], returncode=0,
                 stdout="192.168.122.1 192.168.1.116\n", stderr="",
             ),
         ):
        assert server_util.resolve_lan_ip() == "192.168.1.116"


def test_prefers_real_lan_ip_over_virtualbox_hostonly_bridge():
    with patch("socket.gethostbyname", return_value="192.168.56.1"), \
         patch("socket.socket", return_value=_fake_udp_socket("192.168.56.1")), \
         patch(
             "subprocess.run",
             return_value=subprocess.CompletedProcess(
                 args=["hostname", "-I"], returncode=0,
                 stdout="192.168.56.1 10.0.0.42\n", stderr="",
             ),
         ):
        assert server_util.resolve_lan_ip() == "10.0.0.42"


def test_falls_back_to_virtual_bridge_when_it_is_the_only_candidate():
    # No real LAN IP anywhere -- still return SOMETHING rather than the
    # "<this-computer-ip>" placeholder, since a virtual-only box has no
    # better answer to give and the placeholder isn't a URL a phone can use.
    with patch("socket.gethostbyname", return_value="192.168.122.1"), \
         patch("socket.socket", return_value=_fake_udp_socket("192.168.122.1")), \
         patch(
             "subprocess.run",
             return_value=subprocess.CompletedProcess(
                 args=["hostname", "-I"], returncode=0,
                 stdout="192.168.122.1\n", stderr="",
             ),
         ):
        assert server_util.resolve_lan_ip() == "<this-computer-ip>"


def test_real_lan_ip_still_wins_normally():
    with patch("socket.gethostbyname", return_value="192.168.1.116"), \
         patch("socket.socket", return_value=_fake_udp_socket("192.168.1.116")), \
         patch(
             "subprocess.run",
             return_value=subprocess.CompletedProcess(
                 args=["hostname", "-I"], returncode=0,
                 stdout="192.168.1.116\n", stderr="",
             ),
         ):
        assert server_util.resolve_lan_ip() == "192.168.1.116"


def test_only_a_server_that_says_it_is_eli_v2_is_taken_for_this_eli(monkeypatch):
    """ELI v3 answers on the same port with the same health check: each took the other for
    itself and talked to the wrong ELI ("ELI is already running")."""
    from eli.runtime import server_util

    monkeypatch.setattr(server_util, "port_in_use", lambda port: True)
    answers = {"/health": {"status": "healthy"},
               "/api": {"service": "ELI Cognitive OS Agent", "version": "1.0.0"}}
    monkeypatch.setattr(server_util, "_http_json",
                        lambda url, headers=None: next((v for k, v in answers.items() if url.endswith(k)), None))
    seen = server_util.probe_eli_server(18999)
    assert seen["in_use"] and not seen["eli_running"]
    answers["/api"] = {"service": "ELI Cognitive OS Agent", "product": "eli_v3", "version": "3.0.145"}
    assert not server_util.probe_eli_server(18999)["eli_running"]
    answers["/api"] = {"product": server_util.PRODUCT, "version": "2.5.35"}
    assert server_util.probe_eli_server(18999)["eli_running"]


def test_the_next_free_port_is_found_beside_a_held_one(monkeypatch):
    from eli.runtime import server_util

    monkeypatch.setattr(server_util, "port_in_use", lambda port: port <= 8083)
    assert server_util.free_port_after(8081) == 8084


def test_the_api_names_which_eli_it_is():
    import asyncio
    from api.server import api_info
    from eli.runtime import server_util

    info = asyncio.run(api_info())
    assert info["product"] == server_util.PRODUCT and info["version"]
