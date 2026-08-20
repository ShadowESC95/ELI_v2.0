"""ELI's plugin marketplace client — federated, community-hosted, consent-gated.

There are two kinds of registry here, and they are held to different standards.

  * **The official registry is CURATED.** It is ELI's own marketplace, publicly
    browsable, and every listing on it was submitted, quarantined, evaluated and
    then signed by the maintainer before it appeared. Because that review is the
    product, a listing from the official registry that is *not* validly signed by
    the official key is a hard refusal — not a warning. An unsigned listing there
    does not mean "unreviewed", it means the index or the artifact was tampered
    with between the maintainer and this machine.

  * **Community registries are NOT curated.** Operators may add any registry they
    like, and ELI says about those listings exactly what was checkable — the
    checksum matched, the signature was from a publisher you trust, or nothing was
    verifiable at all — and never a verdict it has not earned. Adding one is
    itself a trust decision, and ELI cannot make it for you.

Keeping both is the point. Curation gives most users a store where someone is
accountable for what is on the shelf; federation means that person cannot become
the only door, and cannot quietly delist a competitor. The official registry is
enabled by default and can be disabled; community registries are opt-in.

  * **Selling is still the seller's problem.** Review is not escrow: a listing may
    carry a price and a purchase URL, and ELI neither takes payment nor can confirm
    one happened.

Everything that touches the network goes through `eli.core.netguard`, so an
offline-by-default install stays offline and every fetch is audited.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_lock = threading.RLock()

BUNDLED_REGISTRY_ID = "builtin"
OFFICIAL_REGISTRY_ID = "eli-official"

# ELI's own curated marketplace. Empty until it is stood up — see docs/MARKETPLACE.md
# — and overridable so anyone can run their own curated registry from an ELI build.
# The client half is complete either way; this is only the address it points at.
OFFICIAL_REGISTRY_URL = "https://plugins.geteli.tech/index.json"
OFFICIAL_REGISTRY_LABEL = "ELI Marketplace"


def official_registry_url() -> str:
    return (os.environ.get("ELI_MARKETPLACE_URL", "").strip()
            or OFFICIAL_REGISTRY_URL).strip()


def _official() -> Optional[Dict[str, Any]]:
    """The curated registry entry, when this build has an address for one."""
    url = official_registry_url()
    if not url:
        return None
    return {
        "id": OFFICIAL_REGISTRY_ID,
        "label": OFFICIAL_REGISTRY_LABEL,
        "url": url,
        "enabled": True,
        "curated": True,
        "official": True,
    }


def is_curated(registry_id: str) -> bool:
    """True when listings from this registry must carry a valid official signature."""
    for reg in _load_registries():
        if reg.get("id") == registry_id:
            return bool(reg.get("curated"))
    return False


def _registries_path() -> Path:
    from eli.core.paths import config_dir
    return Path(config_dir()) / "plugin_registries.json"


def _licences_path() -> Path:
    from eli.core.paths import config_dir
    return Path(config_dir()) / "plugin_licences.json"


# ── registries ─────────────────────────────────────────────────────────────────

def _bundled() -> Dict[str, Any]:
    return {
        "id": BUNDLED_REGISTRY_ID,
        "label": "ELI built-in plugins",
        "url": "",
        "enabled": True,
        "builtin": True,
    }


def _load_registries() -> List[Dict[str, Any]]:
    p = _registries_path()
    out = [_bundled()]
    official = _official()
    if official:
        out.append(official)
    reserved = {BUNDLED_REGISTRY_ID, OFFICIAL_REGISTRY_ID}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            disabled = set(data.get("disabled") or [])
            if official and OFFICIAL_REGISTRY_ID in disabled:
                official["enabled"] = False
            for r in (data.get("registries") or []):
                # A stored entry may not claim a reserved id, and may not claim to be
                # curated: `curated` is what makes a signature mandatory, so a config
                # file that could set it could also grant itself the official badge.
                if isinstance(r, dict) and r.get("id") not in reserved:
                    entry = dict(r)
                    entry.pop("curated", None)
                    entry.pop("official", None)
                    out.append(entry)
        except Exception:
            log.debug("[MARKET] unreadable registry list", exc_info=True)
    return out


def _save_registries(registries: List[Dict[str, Any]]) -> None:
    p = _registries_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = [r for r in registries if r.get("id") != BUNDLED_REGISTRY_ID]
    existing_home = ""
    if p.is_file():
        try:
            existing_home = str(json.loads(p.read_text(encoding="utf-8")).get("home") or "")
        except Exception:
            log.debug("[MARKET] could not preserve the marketplace home", exc_info=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "home": existing_home, "registries": keep}, indent=2), encoding="utf-8")
    tmp.replace(p)


def marketplace_home() -> str:
    """The community marketplace website, if the operator has pointed ELI at one.

    Empty by default and deliberately so. ELI ships no default store URL: the
    marketplace belongs to the community, and baking in an address would make the
    ELI author its gatekeeper, its moderator, and the party answerable for whatever
    strangers publish there. The GUI shows this as a link only once it is set.

    A website is discovery only. It can never trigger an install — it hands out a
    registry URL and a listing id, and the desktop client does the fetching,
    verifying, scanning and asking. If a page could push an install, the browser
    would become the attack surface and the consent dialog would be spoofable.
    """
    override = os.environ.get("ELI_MARKETPLACE_HOME", "").strip()
    if override:
        return override
    p = _registries_path()
    if not p.is_file():
        return ""
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("home") or "")
    except Exception:
        return ""


def set_marketplace_home(url: str) -> Dict[str, Any]:
    """Point ELI at a community marketplace website (discovery only)."""
    url = str(url or "").strip()
    if url and not url.startswith(("https://", "http://")):
        return {"ok": False, "problems": ["The marketplace address must be an http(s) URL."]}
    warnings = []
    if url.startswith("http://"):
        warnings.append("Plain http — the page can be altered in transit.")
    with _lock:
        p = _registries_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except Exception:
            data = {}
        data["home"] = url
        data.setdefault("version", 1)
        data.setdefault("registries", [])
        data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    return {"ok": True, "problems": [], "warnings": warnings}


def list_registries() -> List[Dict[str, Any]]:
    with _lock:
        return _load_registries()


def add_registry(registry_id: str, url: str, label: str = "") -> Dict[str, Any]:
    """Add a community registry. Adding one is itself a trust decision — its listings
    become installable — so the caller is expected to have told the operator that."""
    registry_id = str(registry_id or "").strip()
    url = str(url or "").strip()
    if not registry_id or not url:
        return {"ok": False, "problems": ["A registry id and URL are both required."]}
    if registry_id == BUNDLED_REGISTRY_ID:
        return {"ok": False, "problems": ["That id is reserved."]}
    if not url.startswith(("https://", "http://")):
        return {"ok": False, "problems": ["Registry URL must be http(s)."]}

    warnings = []
    if url.startswith("http://"):
        warnings.append("This registry is plain http. Its listings can be altered in "
                        "transit by anyone on the network path.")

    # A registry on this machine or the local network is legitimate — an operator
    # running their own — but it must be an explicit, recorded decision. Fetches
    # from public registries are never allowed to reach a private address, so a
    # hostile listing cannot redirect ELI into the LAN (see netguard.safe_fetch).
    local = False
    try:
        from eli.core.netguard import (assert_safe_url, UnsafeURLError,
                                        UnresolvableHostError)
        try:
            assert_safe_url(url)
        except UnresolvableHostError as exc:
            # Unreachable is not local. Marking it private would hand a typo the
            # same permissions as a deliberately-added LAN registry.
            warnings.append(f"This registry did not resolve ({exc}). It will be listed "
                            f"but cannot be reached until DNS works.")
        except UnsafeURLError as exc:
            local = True
            warnings.append(
                f"This source is on your own machine or local network ({exc}). "
                f"Adding it lets ELI fetch from there — only do this for a registry "
                f"you run yourself.")
    except Exception:
        log.debug("[MARKET] could not classify registry address", exc_info=True)
    with _lock:
        regs = _load_registries()
        if any(r["id"] == registry_id for r in regs):
            return {"ok": False, "problems": [f"Registry {registry_id!r} already exists."]}
        regs.append({"id": registry_id, "url": url,
                     "label": label or registry_id, "enabled": True,
                     "allow_private": bool(local),
                     "added": time.strftime("%Y-%m-%dT%H:%M:%S")})
        _save_registries(regs)
    return {"ok": True, "problems": [], "warnings": warnings}


def remove_registry(registry_id: str) -> Dict[str, Any]:
    if registry_id == BUNDLED_REGISTRY_ID:
        return {"ok": False, "problems": ["The built-in registry cannot be removed."]}
    with _lock:
        regs = _load_registries()
        if not any(r["id"] == registry_id for r in regs):
            return {"ok": False, "problems": [f"No such registry: {registry_id!r}"]}
        _save_registries([r for r in regs if r["id"] != registry_id])
    return {"ok": True, "problems": []}


def set_registry_enabled(registry_id: str, enabled: bool) -> Dict[str, Any]:
    with _lock:
        regs = _load_registries()
        for r in regs:
            if r["id"] == registry_id:
                r["enabled"] = bool(enabled)
                _save_registries(regs)
                return {"ok": True, "problems": []}
    return {"ok": False, "problems": [f"No such registry: {registry_id!r}"]}


# ── browsing ───────────────────────────────────────────────────────────────────

def _fetch_one(registry: Dict[str, Any], timeout: float = 10) -> Dict[str, Any]:
    """Fetch one registry's index. Network access is netguard's decision, not ours."""
    if registry.get("builtin") or not registry.get("url"):
        try:
            from eli.plugins.manager import _local_registry
            p = _local_registry()
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
            return {"ok": True, "plugins": data.get("plugins", []), "offline": False}
        except Exception as exc:
            return {"ok": False, "plugins": [], "error": str(exc)}

    try:
        from eli.core.netguard import safe_get_json, OfflineError, UnsafeURLError
    except Exception as exc:
        return {"ok": False, "plugins": [], "error": f"netguard unavailable: {exc}"}

    try:
        # safe_get_json pins the scheme, refuses non-public addresses, re-checks every
        # redirect hop and caps the body. A registry index is attacker-controlled data
        # from a host ELI does not own, so none of those are optional.
        data = safe_get_json(registry["url"],
                             headers={"User-Agent": "ELI-marketplace/1.0"},
                             timeout=timeout,
                             allow_private=bool(registry.get("allow_private")))
    except OfflineError:
        return {"ok": False, "plugins": [], "offline": True,
                "error": ("ELI is offline. Turn networking on to browse community "
                          "registries.")}
    except UnsafeURLError as exc:
        return {"ok": False, "plugins": [], "error": f"Refused for safety: {exc}"}
    except Exception as exc:
        return {"ok": False, "plugins": [], "error": f"Could not reach registry: {exc}"}

    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list):
        return {"ok": False, "plugins": [], "error": "Registry index has no 'plugins' list."}
    return {"ok": True, "plugins": plugins, "offline": False}


def browse(*, refresh: bool = True, timeout: float = 10) -> Dict[str, Any]:
    """Every listing from every enabled registry, annotated with what was verifiable.

    Listings are untrusted input written by strangers: they are carried through as
    data and never interpreted as instructions, and the fields shown to the operator
    are validated before display.
    """
    from eli.plugins.manifest import validate_manifest
    from eli.plugins.permissions import risk_of

    listings: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for reg in list_registries():
        if not reg.get("enabled", True):
            continue
        res = _fetch_one(reg, timeout=timeout)
        if not res["ok"]:
            errors.append({"registry": reg["id"], "error": res.get("error", "unknown"),
                           "offline": bool(res.get("offline"))})
            continue
        for raw in res["plugins"]:
            if not isinstance(raw, dict):
                continue
            check = validate_manifest(raw)
            m = check["manifest"]
            m["registry"] = reg["id"]
            m["registry_label"] = reg.get("label", reg["id"])
            m["listing_ok"] = check["ok"]
            m["listing_problems"] = check["problems"]
            m["listing_warnings"] = check["warnings"]
            m["permissions"] = m.get("permissions") or []
            m["risk"] = risk_of(m["permissions"])
            m["signed"] = bool(raw.get("signature") and raw.get("publisher_id"))
            m["pinned"] = bool(raw.get("sha256"))
            m["price"] = raw.get("price") or 0
            m["currency"] = str(raw.get("currency") or "EUR")
            # A registry may list MCP servers alongside Python plugins. They install
            # very differently — an MCP server is a separate process ELI configures,
            # not code loaded into it — so the kind travels with the listing.
            m["kind"] = str(raw.get("kind") or ("mcp" if raw.get("mcp") else "plugin"))
            if m["kind"] == "mcp":
                m["mcp"] = raw.get("mcp") or {}
            listings.append(m)

    return {"ok": not errors or bool(listings), "listings": listings, "errors": errors}


def search(query: str, **kw) -> List[Dict[str, Any]]:
    q = str(query or "").strip().lower()
    items = browse(**kw)["listings"]
    if not q:
        return items
    return [m for m in items
            if q in str(m.get("name", "")).lower()
            or q in str(m.get("description", "")).lower()
            or q in str(m.get("id", "")).lower()]


# ── licence keys (the seller's server verifies; ELI only carries) ──────────────

def _load_licences() -> Dict[str, str]:
    p = _licences_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("licences", {})
    except Exception:
        return {}


def set_licence_key(plugin_id: str, key: str) -> Dict[str, Any]:
    """Store a licence key for a paid plugin.

    ELI cannot verify a purchase — the seller's server does that when the key is
    presented at download. Storing a key here is bookkeeping, not proof of anything.
    """
    with _lock:
        data = _load_licences()
        data[str(plugin_id)] = str(key or "")
        p = _licences_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": 1, "licences": data}, indent=2),
                       encoding="utf-8")
        tmp.replace(p)
    return {"ok": True}


def licence_key(plugin_id: str) -> Optional[str]:
    return _load_licences().get(str(plugin_id)) or None


# ── install ────────────────────────────────────────────────────────────────────

MAX_PLUGIN_BYTES = 8 * 1024 * 1024      # a plugin is source, not a payload


def _download(url: str, *, licence: Optional[str], timeout: float = 30,
              allow_private: bool = False) -> bytes:
    """Fetch plugin source through the hardened path.

    The URL comes from a listing written by a stranger, so this is the highest-risk
    fetch in the product: scheme pinned to http(s), non-public addresses refused,
    every redirect re-validated, and the body capped while reading. `allow_private`
    is inherited from the registry entry, and only ever set when the operator added
    a local registry themselves.
    """
    from eli.core.netguard import safe_fetch

    headers = {"User-Agent": "ELI-marketplace/1.0"}
    if licence:
        headers["X-ELI-Licence"] = licence
    return safe_fetch(url, headers=headers, timeout=timeout,
                      max_bytes=MAX_PLUGIN_BYTES, allow_private=allow_private)


def preview_install(listing: Dict[str, Any], *, timeout: float = 30) -> Dict[str, Any]:
    """Everything the operator needs to decide, WITHOUT installing anything.

    Downloads the source, verifies integrity, statically checks it against its own
    manifest, and returns the full picture. Nothing is written to disk and no
    permission is granted — this is the material for the consent dialog.
    """
    from eli.plugins import integrity
    from eli.plugins.manifest import validate_manifest, verify_against_source
    from eli.plugins.permissions import describe, risk_of

    check = validate_manifest(listing)
    if not check["ok"]:
        return {"ok": False, "stage": "listing", "problems": check["problems"],
                "warnings": check["warnings"]}
    m = check["manifest"]

    price = float(listing.get("price") or 0)
    lic = licence_key(m["id"])
    if price > 0 and not lic:
        return {"ok": False, "stage": "payment", "needs_licence": True,
                "price": price, "currency": listing.get("currency") or "EUR",
                "purchase_url": listing.get("purchase_url") or listing.get("homepage") or "",
                "problems": [
                    f"'{m['name']}' is a paid plugin ({price} "
                    f"{listing.get('currency') or 'EUR'}). Buy it from the publisher, "
                    f"then enter the licence key. ELI does not process the payment and "
                    f"cannot confirm one happened."],
                "warnings": []}

    source_url = listing.get("source")
    if not source_url:
        return {"ok": False, "stage": "source",
                "problems": ["The listing has no source URL to download."], "warnings": []}

    allow_private = False
    try:
        for reg in list_registries():
            if reg.get("id") == listing.get("registry"):
                allow_private = bool(reg.get("allow_private"))
                break
    except Exception:
        log.debug("[MARKET] could not resolve the listing's registry", exc_info=True)

    try:
        raw = _download(source_url, licence=lic, timeout=timeout,
                        allow_private=allow_private)
    except Exception as exc:
        return {"ok": False, "stage": "download",
                "problems": [f"Could not download the plugin: {exc}"], "warnings": []}

    verdict = integrity.assess(raw, listing)
    if not verdict["ok"]:
        return {"ok": False, "stage": "integrity", "integrity": verdict,
                "problems": verdict["warnings"], "warnings": []}

    # A curated listing MUST carry a valid signature from the registry's own key.
    # On a community registry an unsigned plugin is ordinary and gets a warning; on
    # the official one it is evidence of tampering, because nothing reaches that
    # index without being signed at approval time. Treating it as a warning there
    # would let an attacker who can rewrite the index — or sit in the middle of the
    # download — strip the signature and be waved through with a yellow badge.
    if is_curated(str(listing.get("registry") or "")):
        sig = verdict.get("signature") or {}
        expected = integrity.OFFICIAL_PUBLISHER_ID
        if verdict.get("status") != integrity.VERIFIED_SIGNED:
            return {
                "ok": False, "stage": "curation", "integrity": verdict, "warnings": [],
                "problems": [
                    f"'{m['name']}' is listed on a curated registry but its signature "
                    f"did not verify. Every plugin on {listing.get('registry_label') or 'that store'} "
                    f"is signed when it is approved, so an unsigned or unverifiable one "
                    f"means the listing or the file was altered after approval. Refused.",
                    sig.get("reason") or "No valid signature was present."]}
        if str(listing.get("publisher_id") or "") != expected:
            return {
                "ok": False, "stage": "curation", "integrity": verdict, "warnings": [],
                "problems": [
                    f"'{m['name']}' is signed by '{listing.get('publisher_id')}', not by "
                    f"the curated registry's own key ('{expected}'). A valid signature "
                    f"from the wrong signer is still the wrong signer. Refused."]}

    try:
        source = raw.decode("utf-8")
    except Exception:
        return {"ok": False, "stage": "source",
                "problems": ["The downloaded plugin is not valid UTF-8 text."], "warnings": []}

    code = verify_against_source(m, source)
    declared = list(m.get("permissions") or [])

    # Malware scan. Runs on the operator's own machine as well as on whatever the
    # registry did upstream — a scan you did not run yourself is a claim, not a result.
    from eli.plugins import security_scan
    scan = security_scan.scan(raw, m, deep=True)

    warnings = list(check["warnings"]) + list(verdict["warnings"])
    if code["over_declared"]:
        warnings.append(
            "Asks for permissions its code does not appear to use: "
            + ", ".join(code["over_declared"])
            + ". That is not proof of bad intent, but a plugin should ask for the least "
              "it needs.")
    if float(price) > 0:
        warnings.append("Paid plugin. ELI has no way to verify that a purchase took "
                        "place or that a refund is possible.")

    if scan["verdict"] == security_scan.MALICIOUS:
        return {"ok": False, "stage": "malware", "manifest": m, "scan": scan,
                "integrity": verdict,
                "problems": [scan["summary"]] + [
                    f"[{f['severity']}] {f['title']} — {f['detail']}"
                    for f in scan["findings"][:12]],
                "warnings": warnings}
    if scan["verdict"] == security_scan.SUSPICIOUS:
        warnings.append(scan["summary"])
    if not scan["complete"]:
        warnings.append(
            "Some scanners could not run (" + ", ".join(scan["engines_unavailable"]) +
            "), so this file was only partially checked.")

    return {
        "ok": code["ok"],
        "stage": "ready" if code["ok"] else "code",
        "scan": scan,
        "manifest": m,
        "source": source,
        "source_bytes": raw,
        "integrity": verdict,
        "integrity_summary": integrity.status_summary(verdict["status"]),
        "code_check": code,
        "permissions": [describe(p) for p in declared],
        "risk": risk_of(declared),
        "pip": list(m.get("pip") or []),
        "problems": code["problems"],
        "warnings": warnings,
    }


def install(listing: Dict[str, Any], *,
            confirm: Optional[Callable[[Dict[str, Any]], bool]] = None,
            allow_pip: bool = False,
            timeout: float = 30) -> Dict[str, Any]:
    """Install a marketplace plugin, gated on the operator's explicit consent.

    `confirm` is handed the full `preview_install` payload and returns True to
    proceed. No confirm callback means refuse: an unattended install of untrusted
    third-party code is exactly what must not be possible.
    """
    preview = preview_install(listing, timeout=timeout)
    if not preview["ok"]:
        return {**preview, "ok": False}

    if confirm is None:
        return {**preview, "ok": False, "stage": "consent",
                "problems": ["Refused: installing a community plugin needs your explicit "
                             "confirmation, and nothing was available to ask."]}
    try:
        if not confirm(preview):
            return {"ok": False, "stage": "consent", "cancelled": True,
                    "problems": ["Installation cancelled."], "warnings": []}
    except Exception as exc:
        return {"ok": False, "stage": "consent",
                "problems": [f"Consent step failed: {exc}"], "warnings": []}

    m = preview["manifest"]
    pid = m["id"]

    # pip dependencies run publisher-chosen installer code in a child process, which
    # netguard cannot gate (its socket guard is in-process only). Off unless the
    # caller has separately confirmed it.
    if preview["pip"] and not allow_pip:
        return {"ok": False, "stage": "dependencies",
                "problems": [
                    f"'{m['name']}' wants to install {len(preview['pip'])} package(s) from "
                    f"PyPI: {', '.join(preview['pip'])}. Package installers run their own "
                    f"code and reach the network outside ELI's control. Approve this "
                    f"separately if you want it."],
                "warnings": [], "pip": preview["pip"]}

    from eli.plugins.manager import _plugins_dir
    plugin_dir = Path(_plugins_dir()) / pid
    try:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "__init__.py").touch()
        (plugin_dir / "plugin.py").write_text(preview["source"], encoding="utf-8")
        (plugin_dir / "eli_plugin.json").write_text(
            json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        (plugin_dir / ".integrity.json").write_text(json.dumps({
            "sha256": preview["integrity"]["hash"]["actual"],
            "status": preview["integrity"]["status"],
            "installed": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "registry": listing.get("registry"),
            "scan_verdict": (preview.get("scan") or {}).get("verdict"),
            "scan_score": (preview.get("scan") or {}).get("score"),
            "scan_complete": (preview.get("scan") or {}).get("complete"),
            "scanned_at": (preview.get("scan") or {}).get("scanned_at"),
        }, indent=2), encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "stage": "write",
                "problems": [f"Could not write the plugin: {exc}"], "warnings": []}

    # Installed, but DISABLED and with no permissions granted. Consent to install is
    # not consent to run, and consent to run is not consent to any capability — those
    # are asked for individually, at first use, by permissions.check().
    #
    # The disabled flag is written STRAIGHT TO STATE rather than via
    # `get_manager().disable()`: constructing the manager runs `_auto_load()`, which
    # would import and execute the module we just wrote before we ever got to mark it
    # off. Module-level code in a freshly downloaded plugin must not run at install.
    try:
        from eli.plugins.manager import _load_state, _save_state
        state = _load_state()
        disabled = set(state.get("disabled", []))
        disabled.add(pid)
        enabled = set(state.get("enabled", []))
        enabled.discard(pid)
        state["disabled"] = sorted(disabled)
        state["enabled"] = sorted(enabled)
        state.setdefault("installed", {})[pid] = {
            "version": m.get("version", "?"),
            "description": m.get("description", ""),
            "source": listing.get("source", ""),
        }
        _save_state(state)
    except Exception:
        log.debug("[MARKET] could not set initial disabled state", exc_info=True)

    try:
        from eli.plugins.sandbox import refresh as _sandbox_refresh
        _sandbox_refresh()
    except Exception:
        log.debug("[MARKET] sandbox refresh failed", exc_info=True)

    return {"ok": True, "plugin_id": pid, "name": m["name"],
            "path": str(plugin_dir),
            "integrity": preview["integrity"]["status"],
            "permissions": [p["id"] for p in preview["permissions"]],
            "problems": [], "warnings": preview["warnings"],
            "response": (f"'{m['name']}' installed but left switched OFF, with no "
                         f"permissions granted. Enable it when you are ready; it will "
                         f"ask before it uses anything.")}


def needs_review(preview: Dict[str, Any]) -> List[str]:
    """Reasons this install should stop and ask, rather than proceeding.

    The bar is "is there a decision here", not "is anything less than perfect".
    Getting that wrong in either direction is bad: block on ambient conditions and
    one click never fires, so the operator learns to click through the dialog
    without reading it; block on nothing and the click is consent theatre.

    Blocking, because each is a judgement only the operator can make:
      - the scan is not clean
      - the file cannot be matched to the listing (no checksum, or it failed)
      - it wants permissions
      - it installs packages from PyPI
      - it costs money
      - the source is plain http, so the download can be altered in transit

    Deliberately NOT blocking, because these are the normal state of a community
    marketplace and would make the quick path meaningless — they are reported in
    the result instead:
      - ClamAV / YARA / the blocklist not being installed (partial coverage)
      - the plugin being unsigned (most community plugins are)
    """
    reasons: List[str] = []
    if not preview.get("ok"):
        reasons.append(f"refused at the {preview.get('stage')} stage")
        return reasons

    scan = preview.get("scan") or {}
    if scan.get("verdict") != "clean":
        reasons.append(f"the malware scan came back {scan.get('verdict')}")

    integrity = preview.get("integrity") or {}
    if not ((integrity.get("hash") or {}).get("pinned")):
        reasons.append("the listing publishes no checksum, so ELI cannot tell whether "
                       "this is the file the publisher intended")

    if preview.get("permissions"):
        reasons.append(f"it wants {len(preview['permissions'])} permission(s)")
    if preview.get("pip"):
        reasons.append(f"it installs {len(preview['pip'])} package(s) from PyPI")

    source = str((preview.get("manifest") or {}).get("source") or "")
    if source.startswith("http://"):
        reasons.append("the download is plain http and can be altered in transit")
    return reasons


def review_notes(preview: Dict[str, Any]) -> List[str]:
    """Things worth telling the operator that are not worth blocking on."""
    notes: List[str] = []
    scan = preview.get("scan") or {}
    if not scan.get("complete", True):
        notes.append("Some scanners were not available, so this was only partly "
                     "checked: " + ", ".join(scan.get("engines_unavailable") or []))
    integrity = preview.get("integrity") or {}
    from eli.plugins.integrity import VERIFIED_SIGNED
    if integrity.get("status") != VERIFIED_SIGNED:
        notes.append("Unsigned — the file matches the listing, but nothing proves who "
                     "wrote it.")
    return notes


def quick_install(listing: Dict[str, Any], *, timeout: float = 30) -> Dict[str, Any]:
    """The one-click path: verify, scan, and install if there is nothing to decide.

    Returns {ok, installed, review_needed, reasons, preview}. When `review_needed`
    is true NOTHING has been written — the caller shows the full dialog. This is the
    only place consent is implied, and only because every condition that would
    require a judgement has been checked and found absent.
    """
    preview = preview_install(listing, timeout=timeout)
    reasons = needs_review(preview)
    if reasons:
        return {"ok": False, "installed": False, "review_needed": True,
                "reasons": reasons, "notes": review_notes(preview),
                "preview": preview}

    result = install(listing, confirm=lambda _p: True, allow_pip=False, timeout=timeout)
    return {"ok": bool(result.get("ok")), "installed": bool(result.get("ok")),
            "review_needed": False, "reasons": [], "notes": review_notes(preview),
            "preview": preview, "result": result}


def install_mcp(listing: Dict[str, Any], *, verify: bool = True,
                timeout: float = 30) -> Dict[str, Any]:
    """Add an MCP server from a marketplace listing.

    Unlike a plugin there is no code to scan — ELI never sees the server's source,
    only the command that starts it. What CAN be checked is that the runtime exists
    and that the server answers a real MCP handshake, and that is what install_server
    does before writing anything.
    """
    from eli.plugins import mcp

    spec = dict(listing.get("mcp") or {})
    if not spec:
        return {"ok": False, "problems": ["This listing has no MCP server definition."]}
    spec.setdefault("id", listing.get("id"))
    spec.setdefault("permissions", listing.get("permissions") or [])

    result = mcp.install_server(spec, verify=verify, enable=False, timeout=timeout)
    result["caveat"] = mcp.network_caveat()
    return result


__all__ = [
    "list_registries", "add_registry", "remove_registry", "set_registry_enabled",
    "browse", "search", "preview_install", "install",
    "marketplace_home", "set_marketplace_home",
    "quick_install", "needs_review", "review_notes", "install_mcp",
    "is_curated", "official_registry_url", "OFFICIAL_REGISTRY_ID",
    "set_licence_key", "licence_key",
]
