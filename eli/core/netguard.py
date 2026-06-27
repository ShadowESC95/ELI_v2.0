"""
Central network gating for ELI.

ELI is offline-by-default (see eli.core.config.network_allowed). Historically each
networked action (NEWS_FETCH, WEB_SEARCH, ...) had to *remember* to call
network_allowed() itself. That is opt-in, and opt-in gets forgotten — the weather
plugin called open-meteo directly with no gate at all, so it bypassed the Net
toggle entirely.

This module makes gating the default path instead of an afterthought:

  * offline_response(action, what)  -> the standard, honest refusal dict every
                                       networked action returns when the toggle is off.
  * guarded_urlopen / http_get_json -> outbound HTTP helpers that fail CLOSED:
                                       they raise OfflineError before touching the
                                       socket when network_allowed() is False.
  * install_socket_guard()          -> process-wide failsafe. Patches socket
                                       connect() so ANY outbound non-loopback
                                       connection raises OfflineError while offline,
                                       even from code that forgot to use the helpers.
                                       Loopback / unix sockets are always allowed
                                       (local GGUF servers, IPC, etc. keep working).

The rule for any new internet-based task: fetch through guarded_urlopen/http_get_json
(or check should_block_network first). With the socket guard installed you get
defence-in-depth — forgetting the helper fails closed rather than leaking.
"""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import urllib.request
from typing import Any, Dict, Optional


class OfflineError(RuntimeError):
    """Raised when a network operation is attempted while ELI is offline."""


# In-process, scoped override. A *deliberate, user-initiated* networked task
# (e.g. downloading a model the user picked in the first-boot wizard) can open a
# narrow window where network is permitted, WITHOUT changing the persisted
# offline-by-default policy. Everything still routes through this module —
# guarded_urlopen and the socket guard both consult _net_allowed() — so the
# download is gated, just temporarily allowed. The window closes automatically.
_allow_lock = threading.Lock()
_allow_depth = 0          # reentrant: nested allow_network() blocks
_allow_reason = ""        # last reason, for diagnostics


def network_override_active() -> bool:
    return _allow_depth > 0


@contextlib.contextmanager
def allow_network(reason: str = "user-initiated network task"):
    """Temporarily permit outbound network for an explicit, user-initiated task.

    Scoped and reentrant: offline-by-default is restored when the block exits,
    even on exception. This does NOT touch the persisted network_enabled setting.
    """
    global _allow_depth, _allow_reason
    with _allow_lock:
        _allow_depth += 1
        _allow_reason = str(reason or "")
    try:
        yield
    finally:
        with _allow_lock:
            _allow_depth = max(0, _allow_depth - 1)


def _net_allowed() -> bool:
    # A scoped allow_network() window wins — it is an explicit user action.
    if _allow_depth > 0:
        return True
    # ELI Full Control lifts the offline-by-default barrier (user opt-in).
    try:
        from eli.core.full_control import is_full_control
        if is_full_control():
            return True
    except Exception:
        pass
    try:
        from eli.core.config import network_allowed
        return bool(network_allowed())
    except Exception:
        # Fail closed: if we can't read the policy, assume offline.
        return False


def should_block_network() -> bool:
    """True when outbound network must be refused (the Net toggle is off)."""
    return not _net_allowed()


def offline_response(action: str, what: str = "do that") -> Dict[str, Any]:
    """Standard honest refusal for a networked action when offline.

    Keeps wording consistent with WEB_SEARCH/NEWS_FETCH so the model never
    fabricates live data it cannot fetch.
    """
    msg = (
        f"I can't {what} right now — network access is off. "
        "Turn on the Net toggle (or set network_enabled) and ask again "
        "and I'll fetch it live. I won't guess at facts I can't verify."
    )
    return {
        "ok": False,
        "action": action,
        "offline": True,
        "content": msg,
        "response": msg,
    }


# Loopback / local addresses are always permitted even when offline — these are
# local IPC, not internet access (e.g. a local inference server).
_LOCAL_HOST_PREFIXES = ("127.", "0.0.0.0", "::1", "localhost", "::ffff:127.")


# Explicitly-registered LOCAL-network services (e.g. a user-configured MQTT broker on
# the LAN). These are deliberate, user-configured local endpoints — like a local
# inference server — NOT internet access. ONLY the exact registered host(s) are
# permitted; the global offline-by-default policy is unchanged for every other host.
_local_services_lock = threading.Lock()
_LOCAL_SERVICES: set = set()


def _norm_host(host: Optional[str]) -> str:
    return str(host or "").strip().lower().strip("[]")


def register_local_service(*hosts: str) -> None:
    """Permit outbound connections to specific user-configured LAN hosts (and only
    those), without weakening the offline-by-default default for anything else."""
    with _local_services_lock:
        for h in hosts:
            nh = _norm_host(h)
            if nh:
                _LOCAL_SERVICES.add(nh)


def unregister_local_service(*hosts: str) -> None:
    with _local_services_lock:
        for h in hosts:
            _LOCAL_SERVICES.discard(_norm_host(h))


def local_services() -> list:
    with _local_services_lock:
        return sorted(_LOCAL_SERVICES)


def _is_local_host(host: Optional[str]) -> bool:
    if not host:
        return False
    h = _norm_host(host)
    if h in ("localhost", "::1"):
        return True
    if any(h.startswith(p) for p in _LOCAL_HOST_PREFIXES):
        return True
    with _local_services_lock:
        return h in _LOCAL_SERVICES


def guarded_urlopen(url, *args, timeout: float = 20, **kwargs):
    """urllib.request.urlopen that refuses (fails closed) when offline.

    Accepts a str URL or a Request. Raises OfflineError before any socket work
    if the Net toggle is off.
    """
    if should_block_network():
        target = getattr(url, "full_url", url)
        raise OfflineError(f"network disabled (offline mode): blocked request to {target}")
    return urllib.request.urlopen(url, *args, timeout=timeout, **kwargs)


def http_get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 20) -> dict:
    """GET a URL and parse JSON, gated through guarded_urlopen."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ELI/1.0"})
    with guarded_urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Process-wide failsafe                                                        #
# --------------------------------------------------------------------------- #

_GUARD_INSTALLED = False
_REAL_CONNECT = None
_REAL_CREATE_CONNECTION = None


def install_socket_guard() -> bool:
    """Install a process-wide tripwire on outbound socket connections.

    While the Net toggle is off, any connect() to a non-loopback address raises
    OfflineError. Loopback and unix sockets are always allowed. Idempotent.

    This is the guarantee that *every* internet-based task — including ones that
    forgot to call network_allowed() — is gated: it fails closed at the socket
    boundary rather than leaking.
    """
    global _GUARD_INSTALLED, _REAL_CONNECT, _REAL_CREATE_CONNECTION
    if _GUARD_INSTALLED:
        return False

    _REAL_CONNECT = socket.socket.connect
    _REAL_CREATE_CONNECTION = socket.create_connection

    def _addr_host(address) -> Optional[str]:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return None

    def _guarded_connect(self, address):
        # AF_UNIX (str address) and loopback are always local → allow.
        if isinstance(address, tuple) and not _is_local_host(_addr_host(address)):
            if should_block_network():
                raise OfflineError(
                    f"network disabled (offline mode): blocked connection to {address}"
                )
        return _REAL_CONNECT(self, address)

    def _guarded_create_connection(address, *args, **kwargs):
        host = _addr_host(address) if isinstance(address, tuple) else None
        if host and not _is_local_host(host) and should_block_network():
            raise OfflineError(
                f"network disabled (offline mode): blocked connection to {address}"
            )
        return _REAL_CREATE_CONNECTION(address, *args, **kwargs)

    socket.socket.connect = _guarded_connect
    socket.create_connection = _guarded_create_connection
    _GUARD_INSTALLED = True
    return True
