"""Process-wide socket guard — offline must block raw socket.connect, not just helpers."""
from __future__ import annotations

import socket

import pytest

from eli.core.netguard import OfflineError, install_socket_guard


def test_socket_guard_blocks_remote_connect_when_offline(monkeypatch):
    monkeypatch.setenv("ELI_OFFLINE", "1")
    install_socket_guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OfflineError, match="network disabled"):
            sock.connect(("203.0.113.1", 80))
    finally:
        sock.close()


def test_socket_guard_allows_loopback_when_offline(monkeypatch):
    monkeypatch.setenv("ELI_OFFLINE", "1")
    install_socket_guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            # Closed port on loopback — connection refused, not OfflineError.
            sock.connect(("127.0.0.1", 1))
    finally:
        sock.close()
