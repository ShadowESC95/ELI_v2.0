"""Trust for custom agent code — provenance, not just a hash in a dict.

The previous gate hashed each `.py` and stored `{filename: sha256}`. Three things
were wrong with that, and all three are the kind that look fine until they don't:

  * **Keyed on the basename.** Two files called `helper.py` in two different
    directories share one entry, so trusting one silently authorises the other.
    Identity is now the full resolved path, with the basename kept only for
    display.

  * **No provenance.** A hash on its own cannot answer "who approved this, when,
    and what did it look like then?" — the questions you actually ask after
    something goes wrong. Grants now record the time, the approver, the size, the
    static-analysis verdict at approval, and the spec the code was paired with.

  * **Nothing looked at the code.** The gate proved a file had not changed since it
    was approved; it never asked whether approving it was reasonable. Trusting now
    runs the same static analysis and malware engines the plugin marketplace uses,
    and refuses outright on a malicious verdict.

Revocation is real: a revoked entry is remembered as revoked rather than deleted,
so re-adding the same file does not silently re-trust it.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_lock = threading.RLock()

TRUSTED, UNTRUSTED, MODIFIED, REVOKED, REFUSED = (
    "trusted", "untrusted", "modified", "revoked", "refused")


def registry_path() -> Path:
    override = os.environ.get("ELI_AGENT_TRUST_FILE")
    if override:
        return Path(override).expanduser()
    from eli.core.paths import config_dir
    return Path(config_dir()) / "trusted_agents.json"


def _identity(path: Path) -> str:
    """Stable identity for a grant: the resolved absolute path.

    The old registry keyed on `path.name`, so `~/a/helper.py` and `~/b/helper.py`
    were the same entry.
    """
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def file_hash(path: Any) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load() -> Dict[str, Any]:
    p = registry_path()
    if not p.is_file():
        return {"version": 2, "agents": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        log.debug("[AGENT-TRUST] unreadable registry", exc_info=True)
        return {"version": 2, "agents": {}}

    if isinstance(data, dict) and "agents" in data:
        return data

    # Migrate the v1 shape ({filename: hash}) rather than discarding it — an
    # operator's existing approvals should survive the upgrade. They are marked
    # legacy so it is visible that they were granted without the checks below.
    agents = {}
    if isinstance(data, dict):
        for name, h in data.items():
            if isinstance(h, str):
                agents[name] = {"sha256": h, "legacy": True, "basename": name,
                                "granted_at": "", "granted_by": "migrated-from-v1",
                                "note": "Approved before provenance was recorded."}
    return {"version": 2, "agents": agents}


def _save(data: Dict[str, Any]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def list_grants() -> List[Dict[str, Any]]:
    with _lock:
        data = _load()
    return [{"identity": k, **v} for k, v in sorted(data["agents"].items())]


def _lookup(data: Dict[str, Any], path: Path) -> Optional[Dict[str, Any]]:
    agents = data["agents"]
    ident = _identity(path)
    if ident in agents:
        return agents[ident]
    # A legacy (v1) entry is keyed by basename. Honour it once, so upgrading does
    # not un-trust everything, but report it as legacy so it can be re-granted.
    legacy = agents.get(Path(path).name)
    if legacy and legacy.get("legacy"):
        return legacy
    return None


def inspect(path: Any) -> Dict[str, Any]:
    """Current trust state of one agent file, with the reason spelled out."""
    p = Path(path)
    if not p.is_file():
        return {"status": UNTRUSTED, "ok": False, "reason": f"{p} does not exist."}

    with _lock:
        data = _load()
        entry = _lookup(data, p)

    if entry is None:
        return {"status": UNTRUSTED, "ok": False, "identity": _identity(p),
                "reason": ("This agent has never been approved. ELI will not execute "
                           "unapproved code.")}
    if entry.get("revoked"):
        return {"status": REVOKED, "ok": False, "identity": _identity(p),
                "reason": (f"Approval for this agent was revoked on "
                           f"{entry.get('revoked_at', 'an earlier date')}.")}

    actual = file_hash(p)
    if actual != entry.get("sha256"):
        return {"status": MODIFIED, "ok": False, "identity": _identity(p),
                "expected": entry.get("sha256"), "actual": actual,
                "reason": ("The file has changed since it was approved. Review the "
                           "changes and approve it again.")}

    return {"status": TRUSTED, "ok": True, "identity": _identity(p),
            "sha256": actual, "granted_at": entry.get("granted_at", ""),
            "granted_by": entry.get("granted_by", ""),
            "legacy": bool(entry.get("legacy")),
            "scan_verdict": entry.get("scan_verdict"),
            "reason": (f"Approved {entry.get('granted_at') or 'previously'}"
                       + (" (legacy grant — re-approve to record provenance)."
                          if entry.get("legacy") else "."))}


def scan(path: Any, spec: Any = None) -> Dict[str, Any]:
    """Static + malware analysis of agent code, using the marketplace engines.

    A plugin declares its capabilities in a manifest, so "uses X without declaring
    it" is a real finding there. An agent has no manifest unless it was paired with
    an AgentSpec, so that check would fire on every legitimate agent and drown the
    findings that matter. When a spec is supplied its permissions are used; when
    none is, the capability check is neutralised and the genuine malware engines —
    credential access, persistence, C2 patterns, obfuscation, ClamAV, YARA — do the
    work unchanged.
    """
    p = Path(path)
    try:
        source = p.read_text(encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "verdict": "malicious",
                "summary": f"Could not read {p}: {exc}", "findings": []}
    try:
        from eli.plugins.security_scan import scan as _scan
        if spec is not None and getattr(spec, "permissions", None) is not None:
            declared = list(spec.permissions)
        else:
            from eli.plugins.permissions import ALL_CAPABILITIES
            declared = list(ALL_CAPABILITIES)
        return _scan(source, {"id": p.stem, "permissions": declared}, deep=True)
    except Exception as exc:
        log.debug("[AGENT-TRUST] scan unavailable", exc_info=True)
        return {"ok": False, "verdict": "suspicious", "complete": False,
                "summary": f"Scanner unavailable: {exc}", "findings": []}


def grant(path: Any, *, approved_by: str = "operator", spec_hash: str = "",
          spec: Any = None, force: bool = False) -> Dict[str, Any]:
    """Approve an agent file for execution, recording why it was reasonable to.

    Refuses on a malicious scan verdict unless `force` is set, which exists for the
    case where the operator wrote the code themselves and understands a finding —
    and even then the verdict is recorded alongside the grant.
    """
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "problems": [f"{p} does not exist."]}

    report = scan(p, spec=spec)
    if report.get("verdict") == "malicious" and not force:
        return {"ok": False, "status": REFUSED, "scan": report,
                "problems": [report.get("summary", "Malicious code detected.")]
                            + [f"[{f['severity']}] {f['title']}"
                               for f in report.get("findings", [])[:8]]}

    digest = file_hash(p)
    with _lock:
        data = _load()
        data["agents"][_identity(p)] = {
            "sha256": digest,
            "basename": p.name,
            "size": p.stat().st_size,
            "granted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "granted_by": str(approved_by),
            "spec_hash": str(spec_hash or ""),
            "scan_verdict": report.get("verdict"),
            "scan_score": report.get("score"),
            "scan_complete": report.get("complete"),
            "forced": bool(force and report.get("verdict") == "malicious"),
            "revoked": False,
        }
        _save(data)

    return {"ok": True, "status": TRUSTED, "sha256": digest, "scan": report,
            "problems": [],
            "response": (f"'{p.name}' approved. It will load until the file changes; "
                         f"any edit revokes the approval automatically.")}


def revoke(path: Any) -> Dict[str, Any]:
    """Withdraw approval. The entry is KEPT and marked revoked, so re-adding the
    same file later does not quietly become trusted again."""
    p = Path(path)
    with _lock:
        data = _load()
        ident = _identity(p)
        entry = data["agents"].get(ident) or data["agents"].get(p.name)
        if entry is None:
            return {"ok": False, "problems": [f"No approval on record for {p.name}."]}
        entry["revoked"] = True
        entry["revoked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        data["agents"][ident] = entry
        _save(data)
    return {"ok": True, "problems": []}


def forget(path: Any) -> Dict[str, Any]:
    """Remove an entry entirely — the deliberate 'let me start over' action."""
    p = Path(path)
    with _lock:
        data = _load()
        removed = data["agents"].pop(_identity(p), None) or data["agents"].pop(p.name, None)
        _save(data)
    return {"ok": removed is not None, "problems": []
            if removed else [f"No entry for {p.name}."]}


__all__ = ["inspect", "grant", "revoke", "forget", "scan", "list_grants",
           "file_hash", "registry_path",
           "TRUSTED", "UNTRUSTED", "MODIFIED", "REVOKED", "REFUSED"]
