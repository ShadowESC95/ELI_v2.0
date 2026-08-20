"""Integrity and publisher identity for community plugins.

The marketplace belongs to the community, so there is no vendor to vouch for an
upload and ELI must never pretend otherwise. What ELI CAN do is make two much
narrower promises, both verifiable on the operator's own machine:

  * **You got what the listing described.** The listing carries a sha256 of the
    plugin source; the download is hashed before it is ever written to disk. A
    mismatch is a hard refusal — this is what stops a compromised mirror, a
    man-in-the-middle on a plain-http source, or a publisher silently swapping the
    file under an unchanged listing.

  * **It came from a publisher you already chose to trust.** Optional ed25519
    signatures verified against keys the OPERATOR added. Not a key the ELI author
    holds — there is no central authority here by design. An unsigned plugin, or
    one from an unknown key, is not blocked; it is reported as unverified, loudly,
    and the operator decides.

Hash checking is mandatory and dependency-free. Signature checking needs
`cryptography`; where it is absent the plugin is reported as unverifiable rather
than treated as verified.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

VERIFIED_SIGNED = "signed_trusted"
VERIFIED_HASH_ONLY = "hash_only"
UNVERIFIED = "unverified"
FAILED = "failed"

_lock = threading.RLock()


def _publishers_path() -> Path:
    from eli.core.paths import config_dir
    return Path(config_dir()) / "plugin_publishers.json"


# ── hashing ────────────────────────────────────────────────────────────────────

def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_hash(data: bytes, expected: Optional[str]) -> Dict[str, Any]:
    """Compare a download against the hash the listing promised.

    A listing with no hash is not an error here — it is reported as unpinned so the
    caller can decide. It is, however, the single biggest quality signal about a
    publisher, and the install flow surfaces it as such.
    """
    actual = sha256_of(data)
    if not expected:
        return {"ok": True, "pinned": False, "actual": actual,
                "reason": "The listing did not pin a checksum, so ELI cannot tell "
                          "whether this is the file the publisher intended."}
    expected = str(expected).strip().lower()
    if actual != expected:
        return {"ok": False, "pinned": True, "actual": actual, "expected": expected,
                "reason": ("The downloaded file does not match the checksum in the "
                           "listing. It has been altered in transit or at the source. "
                           "Installation refused.")}
    return {"ok": True, "pinned": True, "actual": actual, "expected": expected,
            "reason": "Matches the checksum in the listing."}


# ── publisher trust ────────────────────────────────────────────────────────────

def _load_publishers() -> Dict[str, Dict[str, Any]]:
    p = _publishers_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("publishers", {}) if isinstance(data, dict) else {}
    except Exception:
        log.debug("[PLUGIN-TRUST] unreadable publisher file", exc_info=True)
        return {}


def _save_publishers(pubs: Dict[str, Dict[str, Any]]) -> None:
    p = _publishers_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "publishers": pubs}, indent=2), encoding="utf-8")
    tmp.replace(p)


def trusted_publishers() -> Dict[str, Dict[str, Any]]:
    with _lock:
        return {k: dict(v) for k, v in _load_publishers().items()}


def trust_publisher(publisher_id: str, public_key_b64: str, label: str = "") -> Dict[str, Any]:
    """Add a publisher key the operator has decided to trust.

    Deliberately an explicit act with no 'trust on first use' shortcut: TOFU here
    would mean the first plugin you install from anyone becomes trusted forever,
    which is the same as no check at all.
    """
    publisher_id = str(publisher_id or "").strip()
    if not publisher_id:
        return {"ok": False, "problems": ["Publisher id is required."]}
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        return {"ok": False, "problems": [f"Public key is not valid base64: {exc}"]}
    if len(raw) != 32:
        return {"ok": False, "problems": [
            f"An ed25519 public key is 32 bytes; this is {len(raw)}."]}

    with _lock:
        pubs = _load_publishers()
        pubs[publisher_id] = {
            "public_key": base64.b64encode(raw).decode("ascii"),
            "label": str(label or publisher_id),
            "added": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fingerprint": hashlib.sha256(raw).hexdigest()[:16],
        }
        _save_publishers(pubs)
    return {"ok": True, "publisher": publisher_id,
            "fingerprint": pubs[publisher_id]["fingerprint"], "problems": []}


def untrust_publisher(publisher_id: str) -> Dict[str, Any]:
    with _lock:
        pubs = _load_publishers()
        if publisher_id not in pubs:
            return {"ok": False, "problems": [f"Publisher {publisher_id!r} is not trusted."]}
        pubs.pop(publisher_id)
        _save_publishers(pubs)
    return {"ok": True, "problems": []}


# ── signatures ─────────────────────────────────────────────────────────────────

def signing_available() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: F401
        return True
    except Exception:
        return False


def verify_signature(data: bytes, signature_b64: Optional[str],
                     publisher_id: Optional[str]) -> Dict[str, Any]:
    """Check an ed25519 signature against a publisher key the operator trusts."""
    if not signature_b64 or not publisher_id:
        return {"ok": False, "status": UNVERIFIED,
                "reason": "This plugin is not signed. ELI cannot confirm who wrote it."}

    pubs = trusted_publishers()
    entry = pubs.get(str(publisher_id))
    if not entry:
        return {"ok": False, "status": UNVERIFIED,
                "reason": (f"Signed by '{publisher_id}', who is not in your list of trusted "
                           f"publishers. ELI cannot confirm the signature is theirs.")}

    if not signing_available():
        return {"ok": False, "status": UNVERIFIED,
                "reason": ("This build cannot check signatures (the 'cryptography' package "
                           "is not installed), so the signature is being ignored rather "
                           "than trusted.")}

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(entry["public_key"]))
        key.verify(base64.b64decode(signature_b64), data)
    except Exception as exc:
        return {"ok": False, "status": FAILED,
                "reason": (f"The signature does not match publisher '{publisher_id}'. "
                           f"The file may have been altered ({type(exc).__name__}). "
                           f"Installation refused.")}

    return {"ok": True, "status": VERIFIED_SIGNED,
            "reason": (f"Signed by '{entry.get('label') or publisher_id}' "
                       f"(fingerprint {entry.get('fingerprint')}), a publisher you trust.")}


def assess(data: bytes, listing: Dict[str, Any]) -> Dict[str, Any]:
    """Full integrity verdict for one download.

    Returns {ok, status, hash, signature, warnings}. `ok` False means REFUSE —
    reserved for active evidence of tampering (a hash or signature mismatch), never
    for the ordinary case of an unsigned community plugin.
    """
    h = verify_hash(data, listing.get("sha256"))
    s = verify_signature(data, listing.get("signature"), listing.get("publisher_id"))

    warnings = []
    if not h["ok"]:
        return {"ok": False, "status": FAILED, "hash": h, "signature": s,
                "warnings": [h["reason"]]}
    if s["status"] == FAILED:
        return {"ok": False, "status": FAILED, "hash": h, "signature": s,
                "warnings": [s["reason"]]}

    if not h.get("pinned"):
        warnings.append(h["reason"])
    if s["status"] == UNVERIFIED:
        warnings.append(s["reason"])

    status = VERIFIED_SIGNED if s["ok"] else (
        VERIFIED_HASH_ONLY if h.get("pinned") else UNVERIFIED)
    return {"ok": True, "status": status, "hash": h, "signature": s, "warnings": warnings}


def status_summary(status: str) -> str:
    """One line for the operator. Never overstates what was actually checked."""
    return {
        VERIFIED_SIGNED: "Signed by a publisher you trust, and the file matches the listing.",
        VERIFIED_HASH_ONLY: ("The file matches the checksum in the listing, but nothing "
                             "proves who wrote it."),
        UNVERIFIED: ("Unverified. Nothing proves who wrote this or that it is unchanged. "
                     "Install only if you trust the source."),
        FAILED: "Verification FAILED — do not install.",
    }.get(status, "Unknown verification state.")


__all__ = [
    "sha256_of", "verify_hash", "verify_signature", "assess", "status_summary",
    "trust_publisher", "untrust_publisher", "trusted_publishers", "signing_available",
    "VERIFIED_SIGNED", "VERIFIED_HASH_ONLY", "UNVERIFIED", "FAILED",
]
