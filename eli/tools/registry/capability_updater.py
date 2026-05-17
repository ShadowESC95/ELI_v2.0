#!/usr/bin/env python3
"""
capability_updater.py
Regenerates capability_manifest.json and capability_inventory.generated.json.

The canonical discovery implementation lives in eli.runtime.capability_sync.
This module is kept as the stable GUI/self-upgrade entry point.
"""

import json
import re
import time
from pathlib import Path

ELI_ROOT = Path(__file__).resolve().parents[3]


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


def update_capability_manifest():
    from eli.runtime.capability_sync import CapabilitySync

    sync = CapabilitySync(repo_root=ELI_ROOT)
    capabilities_map = sync.discover()
    delta = sync.run()

    manifest_path = ELI_ROOT / "capability_manifest.json"

    capabilities = [
        {
            "action": action,
            "source": meta.get("source", "unknown"),
            "active": True,
            "plugin": meta.get("plugin"),
            "routable": bool(meta.get("routable")),
            "in_dispatch": bool(meta.get("in_dispatch")),
            "in_supported_list": bool(meta.get("in_supported_list")),
        }
        for action, meta in sorted(capabilities_map.items())
    ]

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(capabilities),
        "capabilities": capabilities,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "total": len(capabilities),
        "executor_actions": sum(1 for c in capabilities if c["in_dispatch"] or c["in_supported_list"]),
        "plugin_actions": sum(1 for c in capabilities if c.get("plugin")),
        "routable_actions": sum(1 for c in capabilities if c["routable"]),
        "changed": delta.has_changes,
        "summary": delta.summary(),
    }


if __name__ == "__main__":
    result = update_capability_manifest()
    if result["ok"]:
        print(f"Capability manifest updated: {result['total']} capabilities")
        print(f"  Executor actions: {result['executor_actions']}")
        print(f"  Plugin actions:   {result['plugin_actions']}")
    else:
        print(f"Error: {result['error']}")
