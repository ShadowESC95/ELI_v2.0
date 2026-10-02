#!/usr/bin/env python3
"""
capability_updater.py
Regenerates capability_manifest.json. (The inventory is written by capability_sync.CapabilitySync, invoked from tools/bootstrap_claims_artifacts.py at build time.)

The canonical discovery implementation lives in eli.runtime.capability_sync.
This module is kept as the stable GUI/self-upgrade entry point.
"""

import json
import re
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


def extract_executor_actions(executor_path: Path) -> list:
    """Extract all action names handled by the executor."""
    src = executor_path.read_text(encoding="utf-8", errors="replace")
    # Match: if a == "ACTION_NAME":  or  if a in ("A", "B"):
    single = re.findall(r'if a == ["\'](\w+)["\']', src)
    multi  = re.findall(r'if a in \(([^)]+)\)', src)
    actions = set(single)
    for group in multi:
        for name in re.findall(r'["\'](\w+)["\']', group):
            actions.add(name)
    return sorted(actions)


def extract_plugin_actions(plugins_dir: Path) -> dict:
    """Extract actions from each plugin's plugin.py."""
    plugin_actions = {}
    if not plugins_dir.exists():
        return plugin_actions
    for plugin_dir in plugins_dir.iterdir():
        plugin_py = plugin_dir / "plugin.py"
        if not plugin_py.exists():
            continue
        try:
            src = plugin_py.read_text(encoding="utf-8", errors="replace")
            actions = re.findall(r'["\'](\w+)["\']', src)
            # Filter to uppercase action-like names
            plugin_actions[plugin_dir.name] = [
                a for a in actions
                if a.isupper() and len(a) > 3 and "_" in a or a.isupper()
            ][:20]
        except Exception:
            pass
    return plugin_actions


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


def _build_capability_entry(action: str, meta: dict) -> dict:
    from eli.runtime.evidence_ledger import predict_success, last_verified_success
    from eli.runtime import capability_state as _cs

    # Discovery is re-run fresh every call (AST scan), but the state dimensions
    # below are incremental — never wiped, only ever added to as real evidence
    # comes in. touch_discovered is a no-op after the first time this action
    # was ever seen.
    _cs.touch_discovered(action)

    plugin = meta.get("plugin")
    permission_state = _plugin_permission_rollup(plugin) if plugin else "not_applicable"
    # Permission decisions can change between runs (the operator can grant or
    # revoke at any time) and are cheap to recompute, unlike probe-sourced
    # dimensions which need an actual probe to run — so this one is refreshed
    # unconditionally every call, not left to go stale.
    _cs.upsert_state(action, permission_state=permission_state)

    state = _cs.get_state(action) or {}
    # Not proven broken along any dimension capability_state actually tracks —
    # "missing evidence" (None) counts as not-proven-broken, same as today's
    # unconditional True, but for a real reason instead of a hardcoded literal.
    # Already-collected evidence that DOES say broken can flip this to False;
    # nothing currently probes these dimensions for a real action yet (see
    # capability_state.py's probe-adapter notes), so in practice this stays
    # True until something does — the mechanism is real even though nothing
    # feeds it negative evidence yet.
    active = not any(state.get(k) is False for k in
                     ("reachable", "device_available", "dependency_ready"))

    return {
        "action": action,
        "source": meta.get("source", "unknown"),
        "active": active,
        "health": predict_success(action),
        "last_verified_success": last_verified_success(action),
        "plugin": plugin,
        "routable": bool(meta.get("routable")),
        "in_dispatch": bool(meta.get("in_dispatch")),
        "in_supported_list": bool(meta.get("in_supported_list")),
        "discovered_at": state.get("discovered_at"),
        "dependency_ready": state.get("dependency_ready"),
        "permission_state": permission_state,
        "reachable": state.get("reachable"),
        "device_available": state.get("device_available"),
        "last_probe_at": state.get("last_probe_at"),
        "evidence_state": state.get("evidence_state"),
    }


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
