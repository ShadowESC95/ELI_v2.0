#!/usr/bin/env python3
"""
capability_updater.py
Regenerates capability_manifest.json. (The inventory is written by capability_sync.CapabilitySync, invoked from tools/bootstrap_claims_artifacts.py at build time.)

The canonical discovery implementation lives in eli.runtime.capability_sync.
This module is kept as the stable GUI/self-upgrade entry point.
"""

import json
import time
from pathlib import Path

def _eli_root() -> Path:
    # Canonical env-honoring root — __file__ resolves into the read-only
    # bundle in frozen builds and manifest/inventory writes then fail.
    try:
        from eli.core.paths import project_root
        return Path(project_root())
    except Exception:
        return Path(__file__).resolve().parents[3]


ELI_ROOT = _eli_root()


def _plugin_permission_rollup(plugin_id: str) -> str:
    """permission_state for a plugin-sourced action.

    PermissionStore is keyed by (plugin_id, capability-CLASS) — one of 14
    generic classes (network, filesystem_write, ...) a plugin declares in
    its manifest — not by individual action name, and there is no existing
    mapping from "this action" to "which of those 14 classes it needs" (a
    plugin can expose several actions under one set of capability grants).
    So this is a plugin-level rollup, not a per-action lookup: "denied" if
    the plugin has any deny_always on record (the more cautious signal when
    grants are mixed), "granted" if it has at least one allow_always and no
    deny_always, "undetermined" if nothing persistent has been decided yet.
    Coarser than per-action, but every value here is grounded in a real
    stored decision — nothing invented to fill in a mapping that doesn't
    exist.
    """
    try:
        from eli.plugins.permissions import DENY_ALWAYS, ALLOW_ALWAYS, store
        grants = store().grants_for(plugin_id)
    except Exception:
        return "undetermined"
    decisions = {g.get("decision") for g in grants.values()}
    if DENY_ALWAYS in decisions:
        return "denied"
    if ALLOW_ALWAYS in decisions:
        return "granted"
    return "undetermined"


def _manifest_matches(path, manifest) -> bool:
    """True when the manifest on disk differs from `manifest` only by generated_at."""
    try:
        if not path.exists():
            return False
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(existing, dict):
        return False
    return {k: v for k, v in existing.items() if k != "generated_at"} == \
           {k: v for k, v in manifest.items() if k != "generated_at"}


def _missing_modules(needs) -> list:
    import importlib.util
    out = []
    for name in needs or ():
        try:
            if importlib.util.find_spec(name) is None:
                out.append(name)
        except (ImportError, ValueError):
            out.append(name)
    return out


def manifest_entry(action: str, meta: dict) -> dict:
    """What the code says about one action, for the shipped manifest: where it lives, how it is reached,
    the third-party modules its own branch imports. Whether it has worked here, and whether what it needs
    is present, belong to this machine and are kept in its capability state (capability_status). The
    manifest used to carry both: every action read "active", and a test run's results were written into
    the tracked file as verified successes."""
    return {
        "action": action,
        "source": meta.get("source", "unknown"),
        "plugin": meta.get("plugin"),
        "routable": bool(meta.get("routable")),
        "in_dispatch": bool(meta.get("in_dispatch")),
        "in_supported_list": bool(meta.get("in_supported_list")),
        "needs": sorted(meta.get("needs") or []),
    }


def _build_capability_entry(action: str, meta: dict) -> dict:
    """The manifest entry, and this machine's state for the action brought up to date."""
    from eli.runtime import capability_state as _cs

    entry = manifest_entry(action, meta)
    _cs.touch_discovered(action)
    # Permission decisions can change between runs and are cheap to recompute: refreshed every call.
    fields = {"permission_state": _plugin_permission_rollup(entry["plugin"]) if entry["plugin"] else "not_applicable"}
    if entry["needs"]:
        # measured here: a module the branch imports is installed or it is not
        fields["dependency_ready"] = not _missing_modules(entry["needs"])
    _cs.upsert_state(action, **fields)
    return entry


def capability_status(actions=None) -> dict:
    """This install's view of its capabilities. "verified": it has worked here (a real success in the
    evidence ledger); "unavailable": something it needs is missing here, it was found unreachable, or
    its plugin is denied; "untested": neither yet. The manifest only says what the code can do."""
    from eli.runtime import capability_state as _cs
    from eli.runtime.evidence_ledger import verified_actions
    if actions is None:
        try:
            actions = [c["action"] for c in json.loads((ELI_ROOT / "capability_manifest.json").read_text(
                encoding="utf-8")).get("capabilities", [])]
        except Exception:
            actions = []
    worked = verified_actions()
    states = _cs.all_states()
    view = {}
    for action in actions:
        st = states.get(str(action).upper()) or {}
        blocked = (any(st.get(k) is False for k in ("dependency_ready", "reachable", "device_available"))
                   or st.get("permission_state") == "denied")
        view[action] = {
            "status": "unavailable" if blocked else ("verified" if action in worked else "untested"),
            "verified_at": worked.get(action),
            **{k: st.get(k) for k in ("dependency_ready", "permission_state", "reachable", "device_available",
                                      "evidence_state", "discovered_at", "last_probe_at")},
        }
    counts = {k: sum(1 for v in view.values() if v["status"] == k) for k in ("verified", "unavailable", "untested")}
    return {"discovered": len(view), **counts, "actions": view}


def update_capability_manifest():
    from eli.runtime.capability_sync import CapabilitySync

    sync = CapabilitySync(repo_root=ELI_ROOT)
    capabilities_map = sync.discover()
    delta = sync.run()

    manifest_path = ELI_ROOT / "capability_manifest.json"

    capabilities = [
        _build_capability_entry(action, meta)
        for action, meta in sorted(capabilities_map.items())
    ]

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(capabilities),
        "capabilities": capabilities,
    }

    # Only write when the capabilities themselves changed. A fresh timestamp over
    # an identical manifest is not an update: this file is tracked, so rewriting
    # it on every start left it permanently modified in git, and a real
    # capability change would have been indistinguishable from that noise.
    if not _manifest_matches(manifest_path, manifest):
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Keep the human-readable reference table in sync with the manifest. Best-effort:
    # any newly-discovered routable action without a curated activation phrase is
    # still emitted (flagged) so the doc never goes stale.
    doc_needs_phrase = []
    try:
        from eli.tools.registry.capabilities_doc import generate_capabilities_doc
        _doc = generate_capabilities_doc()
        doc_needs_phrase = _doc.get("needs_phrase", [])
    except Exception:
        pass

    return {
        "ok": True,
        "total": len(capabilities),
        "executor_actions": sum(1 for c in capabilities if c["in_dispatch"] or c["in_supported_list"]),
        "plugin_actions": sum(1 for c in capabilities if c.get("plugin")),
        "routable_actions": sum(1 for c in capabilities if c["routable"]),
        "changed": delta.has_changes,
        "summary": delta.summary(),
        "doc_needs_phrase": doc_needs_phrase,
    }


if __name__ == "__main__":
    result = update_capability_manifest()
    if result["ok"]:
        print(f"Capability manifest updated: {result['total']} capabilities")
        print(f"  Executor actions: {result['executor_actions']}")
        print(f"  Plugin actions:   {result['plugin_actions']}")
    else:
        print(f"Error: {result['error']}")
