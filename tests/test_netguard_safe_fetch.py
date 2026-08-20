"""Fetching from sources the operator does not own.

`guarded_urlopen` answers one question — is the network switch on? — which is right
for ELI's own outbound calls and wrong for a URL that came from a community plugin
registry. urllib follows redirects silently, and the socket guard permits loopback
unconditionally, so before `safe_fetch` a hostile listing could aim a marketplace
download at ELI's own API server or a LAN device and use ELI as the confused deputy.

Demonstrated at the time: a 302 from a registry to `http://127.0.0.1:.../internal`
was followed and the body handed back to the caller.
"""
import json
import threading

import pytest

from eli.core.netguard import (
    MAX_FETCH_BYTES, UnresolvableHostError, UnsafeURLError, assert_safe_url, safe_fetch,
)


@pytest.fixture()
def online(monkeypatch):
    monkeypatch.setenv("ELI_OFFLINE", "0")
    return True


@pytest.fixture()
def server():
    """A local server that redirects into loopback and can serve an oversized body."""
    import http.server
    import socketserver

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect-inward":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/internal")
                self.end_headers()
            elif self.path == "/big":
                body = b"x" * 200_000
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/undeclared-big":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"y" * 200_000)
            else:
                body = json.dumps({"secret": "INTERNAL SERVICE DATA"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


# ── scheme pinning ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/x",
    "data:text/plain;base64,aGk=",
    "gopher://example.com/",
])
def test_only_http_schemes_are_fetched(url):
    """file:, ftp: and data: can read local resources through the same call."""
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


# ── address filtering ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,what", [
    ("http://127.0.0.1/x", "loopback"),
    ("http://localhost/x", "loopback by name"),
    ("http://10.0.0.5/x", "private"),
    ("http://192.168.1.1/x", "private"),
    ("http://172.16.0.1/x", "private"),
    ("http://169.254.169.254/latest/meta-data/", "cloud metadata"),
    ("http://[::1]/x", "IPv6 loopback"),
])
def test_non_public_addresses_are_refused(url, what):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_operator_owned_private_source_can_be_opted_into():
    """An operator running their own LAN registry is legitimate — but it has to be
    an explicit decision, never inferred from the URL an attacker controls."""
    assert assert_safe_url("http://127.0.0.1/x", allow_private=True)


def test_unresolvable_is_its_own_error():
    """'Does not resolve' and 'resolves somewhere private' are different facts.
    Conflating them made an unreachable public registry look like a deliberate
    LAN one, and silently granted it private-network access."""
    with pytest.raises(UnresolvableHostError):
        assert_safe_url("https://nonexistent.invalid/index.json")


# ── the redirect hole ──────────────────────────────────────────────────────────

def test_redirect_into_loopback_is_refused_mid_flight(online, server):
    """Validating only the URL the caller passed is worth little: the interesting
    address is the last one, and the server chooses it."""
    with pytest.raises(UnsafeURLError):
        safe_fetch(f"{server}/redirect-inward", allow_private=False, timeout=5)


# ── size caps ──────────────────────────────────────────────────────────────────

def test_declared_oversize_is_refused(online, server):
    with pytest.raises(ValueError):
        safe_fetch(f"{server}/big", allow_private=True, max_bytes=50_000, timeout=5)


def test_undeclared_oversize_is_still_capped(online, server):
    """A server that omits Content-Length must not be able to stream unbounded data
    into memory."""
    with pytest.raises(ValueError):
        safe_fetch(f"{server}/undeclared-big", allow_private=True, max_bytes=50_000,
                   timeout=5)


def test_a_normal_body_comes_back_intact(online, server):
    body = safe_fetch(f"{server}/internal", allow_private=True, timeout=5)
    assert json.loads(body.decode())["secret"] == "INTERNAL SERVICE DATA"


# ── the offline switch still wins ──────────────────────────────────────────────

def test_offline_still_blocks_even_a_safe_url(monkeypatch, server):
    from eli.core.netguard import OfflineError
    monkeypatch.setenv("ELI_OFFLINE", "1")
    with pytest.raises(OfflineError):
        safe_fetch(f"{server}/internal", allow_private=True, timeout=5)


def test_the_cap_is_a_sane_default():
    assert 1_000_000 < MAX_FETCH_BYTES < 100_000_000
