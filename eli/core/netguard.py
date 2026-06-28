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
import os
import queue
import socket
import threading
import time
import urllib.request
from collections import deque
from typing import Any, Dict, List, Optional


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


# --------------------------------------------------------------------------- #
# Egress monitoring                                                           #
# Offline-by-default is enforced above. When the owner deliberately enables    #
# network, the toggle is no longer a blind hole: every ALLOWED non-loopback    #
# connection is RECORDED — into an in-memory ring buffer (live dashboard view) #
# and, throttled, into the tamper-evident audit ledger — so "internet on" is   #
# reviewable. Recording is best-effort and OFF the hot path (a background      #
# writer drains a queue); it never delays or breaks a connection.              #
# --------------------------------------------------------------------------- #
_EGRESS_RING_MAX = 500
_egress_ring: "deque" = deque(maxlen=_EGRESS_RING_MAX)
_egress_ring_lock = threading.Lock()
_egress_total = 0                       # monotonic count of recorded egress events
_egress_q: "Optional[queue.Queue]" = None
_egress_writer_started = False
_egress_writer_lock = threading.Lock()


def _egress_log_window() -> float:
    """Seconds between durable ledger rows for the same host:port (a burst of
    connections to one host yields one audit row per window, not thousands).
    The in-memory ring still captures every event. 0 disables throttling.
    Tunable via ELI_EGRESS_LOG_WINDOW (default 300s)."""
    try:
        return float(os.environ.get("ELI_EGRESS_LOG_WINDOW", "300"))
    except Exception:
        return 300.0


def _egress_ledger_enabled() -> bool:
    return os.environ.get("ELI_EGRESS_LEDGER", "1").strip().lower() not in ("0", "false", "no", "off")


def _egress_writer_loop() -> None:
    last_logged: Dict[str, int] = {}
    while True:
        try:
            item = _egress_q.get()  # type: ignore[union-attr]
        except Exception:
            continue
        if item is None:
            continue
        host, port, ts = item
        try:
            win = _egress_log_window()
            key = f"{host}:{port}"
            bucket = int(ts // win) if win > 0 else int(ts)
            if win > 0 and last_logged.get(key) == bucket:
                continue                # already logged this host this window
            last_logged[key] = bucket
            if len(last_logged) > 4096:  # cap the throttle map
                last_logged.clear()
            from eli.runtime.evidence_ledger import record_event
            # The window bucket is in `content` (part of the dedup signature) so each
            # window produces a distinct durable row rather than collapsing to one ever.
            record_event(
                "net_egress",
                source="netguard",
                action="OUTBOUND",
                subject=key,
                content=f"egress to {key} @w{bucket}",
                severity="info",
                payload={"host": host, "port": port, "window_bucket": bucket},
            )
        except Exception:
            continue


def _start_egress_writer() -> None:
    global _egress_q, _egress_writer_started
    if _egress_writer_started:
        return
    with _egress_writer_lock:
        if _egress_writer_started:
            return
        _egress_q = queue.Queue(maxsize=2048)
        threading.Thread(target=_egress_writer_loop, name="eli-egress-writer",
                         daemon=True).start()
        _egress_writer_started = True


def _record_egress(host: Optional[str], port: Any = None) -> None:
    """Record an ALLOWED non-loopback outbound connection. Best-effort, never raises,
    never blocks the connection (ledger write happens on a background thread)."""
    global _egress_total
    if not host:
        return
    try:
        nh = _norm_host(host)
        ts = time.time()
        with _egress_ring_lock:
            _egress_ring.append({"host": nh, "port": port, "ts": ts})
            _egress_total += 1
        if _egress_ledger_enabled():
            _start_egress_writer()
            if _egress_q is not None:
                try:
                    _egress_q.put_nowait((nh, port, ts))
                except Exception:
                    pass            # queue full → ring still has it; drop the ledger write
    except Exception:
        pass


def recent_egress(limit: int = 100) -> List[Dict[str, Any]]:
    """Most-recent allowed outbound connections (newest last) for the dashboard."""
    with _egress_ring_lock:
        items = list(_egress_ring)
    return items[-limit:] if (limit and limit > 0) else items


def egress_total() -> int:
    """Total allowed outbound connections recorded since process start."""
    return _egress_total


def _addr_host_port(address) -> tuple:
    if isinstance(address, tuple) and address:
        return str(address[0]), (address[1] if len(address) > 1 else None)
    return None, None


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
            # Allowed non-loopback egress → record it (this is the single chokepoint
            # every outbound connection passes through, so it's the one place to watch).
            _host, _port = _addr_host_port(address)
            _record_egress(_host, _port)
        return _REAL_CONNECT(self, address)

    def _guarded_create_connection(address, *args, **kwargs):
        host = _addr_host(address) if isinstance(address, tuple) else None
        if host and not _is_local_host(host):
            if should_block_network():
                raise OfflineError(
                    f"network disabled (offline mode): blocked connection to {address}"
                )
            _host, _port = _addr_host_port(address)
            _record_egress(_host, _port)
        return _REAL_CREATE_CONNECTION(address, *args, **kwargs)

    socket.socket.connect = _guarded_connect
    socket.create_connection = _guarded_create_connection
    _GUARD_INSTALLED = True
    return True
