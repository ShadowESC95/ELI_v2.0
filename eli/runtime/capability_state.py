"""Incremental per-capability state — what is actually known about each
action right now, built up one fact at a time instead of wiped and rebuilt
on every capability_manifest.json regen.

update_capability_manifest() (capability_updater.py) rebuilds its 9-field
list from a fresh AST scan every call — anything not re-derivable from that
scan + evidence_ledger was lost on every regen, which is why `active` has
always been a hardcoded True with no real detection: there was nowhere to
persist a real answer between regens. This module is that place. One row
per action, upserted whenever something new is actually known — never
wiped wholesale, unlike the manifest it feeds.

Deliberately NOT hash-chained like evidence_ledger/orchestrator_audit_ledger
— those are append-only event histories; this is current, mutable state
about each action, closer to user_model's one-row-per-subject shape.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from eli.runtime.evidence_arbitration import EvidenceState
from eli.utils.log import get_logger

log = get_logger(__name__)


def _default_db_path() -> Path:
    from eli.core.paths import capability_state_db_path
    return capability_state_db_path()


def _connect(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve() if db_path else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    from eli.core.sqlite_util import apply_pragmas
    apply_pragmas(conn, db_path=str(path), synchronous="NORMAL")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_state (
            action TEXT PRIMARY KEY,
            discovered_at REAL,
            dependency_ready INTEGER,
            permission_state TEXT,
            reachable INTEGER,
            device_available INTEGER,
            last_probe_at REAL,
            last_verified_success REAL,
            reliability REAL,
            calibrated_success REAL,
            evidence_state TEXT,
            updated_at REAL
        )
        """
    )


_FIELDS = (
    "discovered_at", "dependency_ready", "permission_state", "reachable",
    "device_available", "last_probe_at", "last_verified_success",
    "reliability", "calibrated_success", "evidence_state", "updated_at",
)
_BOOL_FIELDS = ("dependency_ready", "reachable", "device_available")
_COLUMNS = ("action",) + _FIELDS


def _row(row) -> Dict[str, Any]:
    out = dict(zip(_COLUMNS, row))
    for b in _BOOL_FIELDS:
        if out[b] is not None:
            out[b] = bool(out[b])
    return out


def get_state(action: str, *, db_path: Optional[str | Path] = None) -> Optional[Dict[str, Any]]:
    """The current known state for one action, or None if nothing has ever
    been recorded about it. Missing is not false — callers must not treat
    None the same as a confirmed-unavailable capability."""
    action = str(action or "").strip().upper()
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM capability_state WHERE action = ?",
            (action,),
        ).fetchone()
    finally:
        conn.close()
    return _row(row) if row else None


def all_states(*, db_path: Optional[str | Path] = None) -> Dict[str, Dict[str, Any]]:
    """Every action's known state, in one read."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM capability_state").fetchall()
    finally:
        conn.close()
    return {r[0]: _row(r) for r in rows}


def touch_discovered(action: str, *, now: Optional[float] = None,
                     db_path: Optional[str | Path] = None) -> None:
    """Record the first time this action was seen, without touching anything
    else about it. A no-op if it has already been recorded once — this is
    meant to be called from capability_updater.py's own discovery loop, on
    every action, every run."""
    action = str(action or "").strip().upper()
    if not action:
        return
    now = float(now if now is not None else time.time())
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO capability_state (action, discovered_at, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(action) DO NOTHING",
            (action, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_state(action: str, *, db_path: Optional[str | Path] = None,
                 now: Optional[float] = None, **fields: Any) -> None:
    """Merge the given fields into this action's row — fields the caller
    didn't pass are left exactly as they were, which is the whole point:
    this never wipes what it doesn't have fresh evidence for. Unknown keys
    raise rather than being silently accepted into nowhere."""
    bad = set(fields) - set(_FIELDS)
    if bad:
        raise ValueError(f"unknown capability_state field(s): {sorted(bad)}")
    action = str(action or "").strip().upper()
    if not action:
        return
    now = float(now if now is not None else time.time())
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO capability_state (action, updated_at) VALUES (?, ?) "
            "ON CONFLICT(action) DO NOTHING",
            (action, now),
        )
        for key, value in fields.items():
            if isinstance(value, bool):
                value = int(value)
            conn.execute(
                f"UPDATE capability_state SET {key} = ?, updated_at = ? WHERE action = ?",
                (value, now, action),
            )
        conn.commit()
    finally:
        conn.close()


def record_probe_result(action: str, evidence_state: str, *,
                        reachable: Optional[bool] = None,
                        device_available: Optional[bool] = None,
                        cost_estimate: Optional[float] = None,
                        now: Optional[float] = None,
                        db_path: Optional[str | Path] = None) -> None:
    """A probe just reported something real about this action. Also refreshes
    reliability/last_verified_success from evidence_ledger — that module stays
    the one place reliability math is computed; this just caches the current
    values alongside everything else so capability_updater.py has one row to
    read instead of querying two separate systems. cost_estimate is accepted
    for the caller's own logging/telemetry but not persisted — this table
    tracks capability STATE, not a probe cost history."""
    now = float(now if now is not None else time.time())
    fields: Dict[str, Any] = {"evidence_state": str(evidence_state), "last_probe_at": now}
    if reachable is not None:
        fields["reachable"] = bool(reachable)
    if device_available is not None:
        fields["device_available"] = bool(device_available)
    try:
        from eli.runtime.evidence_ledger import last_verified_success, predict_success
        lvs = last_verified_success(action)
        if lvs is not None:
            fields["last_verified_success"] = lvs
        rel = predict_success(action)
        if rel is not None:
            fields["reliability"] = rel
    except Exception:
        log.debug("evidence_ledger lookup failed while recording a probe result", exc_info=True)
    upsert_state(action, now=now, db_path=db_path, **fields)


# ── freshness policy ──────────────────────────────────────────────────────
# Static per-dimension TTLs, not a learned/adaptive policy — matches "don't
# over-engineer" over a speculative future need there is no usage data to
# calibrate against yet.
_FRESHNESS_S: Dict[str, float] = {
    "reachable": 5 * 60.0,
    "device_available": 10 * 60.0,
    "permission_state": 60 * 60.0,
}


# A failure that names something missing from this machine, not a mistake in the request: a module,
# a program, an extra. A missing file is left out: that is usually the user's file, not ELI's part.
_MISSING_PART_RE = re.compile(r"no module named|modulenotfounderror|\b(?:isn't|is not|not) installed\b|command not found",
                              re.I)


def observe_run(action: str, outcome: str, detail: str = "", *, db_path: Optional[str | Path] = None) -> None:
    """What a real run says about whether an action can run here. A success: it can. A failure naming a
    missing module or program: it can't, until what it needs is installed and it works again."""
    if outcome == "ok":
        upsert_state(action, db_path=db_path, dependency_ready=True)
    elif outcome == "failed" and _MISSING_PART_RE.search(str(detail or "")):
        upsert_state(action, db_path=db_path, dependency_ready=False)


def is_stale(action: str, dimension: str, *, now: Optional[float] = None,
            db_path: Optional[str | Path] = None) -> bool:
    """Whether the given dimension's evidence is old enough to need
    re-checking. Unknown (never probed) counts as stale — there is nothing
    fresh about an absence. A dimension with no freshness policy registered
    is never forced stale by this function."""
    ttl = _FRESHNESS_S.get(dimension)
    if ttl is None:
        return False
    state = get_state(action, db_path=db_path)
    if not state or not state.get("last_probe_at"):
        return True
    now = float(now if now is not None else time.time())
    return (now - float(state["last_probe_at"])) > ttl


# ── probe adapters ────────────────────────────────────────────────────────
# Three existing probes, three incompatible native return shapes:
#   mic_diag._probe_device          -> Optional[int]             (mean RMS, or None)
#   ble_light.probe                 -> dict                      (BleProbe.as_dict())
#   mqtt_setup.probe_broker_connection -> Dict[str, Any]
# Each adapter below normalizes one probe's raw return into
# (evidence_state, cost_estimate, detail).
#
# None of them has a caller in the running pipeline yet, and none corresponds to a capability
# manifest action; they are built and tested so a real caller can use them.

def _adapt_mic_probe(rms: Optional[int]) -> Tuple[str, Optional[float], str]:
    if rms is None:
        return EvidenceState.NOT_FOUND, None, "device could not be read"
    return EvidenceState.FOUND, None, f"mean RMS {rms}"


def _adapt_ble_probe(result: Dict[str, Any]) -> Tuple[str, Optional[float], str]:
    if result.get("error"):
        return EvidenceState.INSPECTION_FAILED, None, str(result["error"])
    if result.get("protocol"):
        return EvidenceState.FOUND, None, f"protocol: {result['protocol']}"
    return EvidenceState.NOT_FOUND, None, "connected, no known light protocol matched"


def _adapt_mqtt_probe(result: Dict[str, Any]) -> Tuple[str, Optional[float], str]:
    if result.get("ok"):
        return EvidenceState.FOUND, None, "broker reachable"
    return (EvidenceState.NOT_FOUND, None,
            str(result.get("error") or result.get("hint") or "broker unreachable"))


_ADAPTERS = {
    "mic_probe": _adapt_mic_probe,
    "ble_probe": _adapt_ble_probe,
    "mqtt_probe": _adapt_mqtt_probe,
}


# ── probe selection ────────────────────────────────────────────────────────
# A real but modest first version: given a dimension missing evidence, pick
# the cheapest registered adapter that actually resolves it. Not a full
# expected-information-value optimizer — the plan itself flags that as an
# explicit stretch goal, not v1, since building it without real usage data
# to calibrate against would be speculative complexity. Costs below are
# relative orderings grounded in what each probe mechanically does (a plain
# TCP connect is cheaper than a BLE GATT negotiation, which is cheaper than
# opening an audio device and sampling it) — not measured data, since none
# exists yet.
_DIMENSION_ADAPTERS: Dict[str, Tuple[Tuple[str, float], ...]] = {
    "reachable": (("mqtt_probe", 1.0), ("ble_probe", 3.0)),
    "device_available": (("mic_probe", 2.0),),
}


def select_cheapest_adapter(dimension: str) -> Optional[str]:
    """The cheapest registered adapter name that resolves the given
    dimension, or None if nothing registered resolves it."""
    candidates = _DIMENSION_ADAPTERS.get(dimension)
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[1])[0]


__all__ = [
    "ensure_schema", "get_state", "all_states", "touch_discovered", "upsert_state",
    "record_probe_result", "observe_run", "is_stale", "select_cheapest_adapter",
    "_adapt_mic_probe", "_adapt_ble_probe", "_adapt_mqtt_probe",
]
