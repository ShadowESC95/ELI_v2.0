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
