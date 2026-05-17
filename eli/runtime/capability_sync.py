"""
brain.awareness.capability_sync
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Discovers all capabilities from live code via AST parsing (no import
side-effects), diffs against the last known state, writes a canonical
inventory JSON, and returns a structured delta.

Design:
  - AST-parses executor_enhanced.py for `if a == "ACTION"` patterns
  - Reads SUPPORTED_ACTIONS list from the same file
  - Reads plugin registry index.json
  - Reads router_enhanced.py for routable intents
  - Zero import side-effects — safe to call at any time
"""

from __future__ import annotations

import ast
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class SyncDelta:
    """What changed since the last sync."""

    __slots__ = ("added", "removed", "changed", "timestamp")

    def __init__(self):
        self.added: List[str] = []
        self.removed: List[str] = []
        self.changed: List[str] = []
        self.timestamp: float = 0.0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)} new ({', '.join(self.added[:5])})")
        if self.removed:
            parts.append(f"-{len(self.removed)} removed ({', '.join(self.removed[:5])})")
        if self.changed:
            parts.append(f"~{len(self.changed)} re-wired ({', '.join(self.changed[:5])})")
        return "; ".join(parts) if parts else "no capability changes"


# ---------------------------------------------------------------------------
# AST-based executor introspection (zero imports, no side-effects)
# ---------------------------------------------------------------------------

def _ast_extract_dispatch_actions(source: str) -> Set[str]:
    """
    Parse Python source and extract all string literals compared to `a`
    in patterns like:  if a == "ACTION_NAME":
                       if a in ("X", "Y", "Z"):
                       if a in {"X", "Y"}:
    """
    actions: Set[str] = set()
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return actions

    _ACTION_NAME_IDS = {"a", "action_name", "action_text"}

    for node in ast.walk(tree):
        # Pattern: if a == "ACTION"
        if isinstance(node, ast.Compare):
            if (isinstance(node.left, ast.Name) and node.left.id in _ACTION_NAME_IDS
                    and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
                    and len(node.comparators) == 1):
                comp = node.comparators[0]
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    actions.add(comp.value.upper())

        # Pattern: if a in ("X", "Y", ...)  or  if a in {"X", "Y", ...}
        if isinstance(node, ast.Compare):
            if (isinstance(node.left, ast.Name) and node.left.id in _ACTION_NAME_IDS
                    and len(node.ops) == 1 and isinstance(node.ops[0], ast.In)
                    and len(node.comparators) == 1):
                container = node.comparators[0]
                elts = []
                if isinstance(container, (ast.Tuple, ast.List, ast.Set)):
                    elts = container.elts
                for elt in elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        actions.add(elt.value.upper())

        # Pattern: if ctx["action"] == "ACTION"
        if isinstance(node, ast.Compare):
            if not (len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq) and len(node.comparators) == 1):
                continue

            left = node.left
            comp = node.comparators[0]

            if not (isinstance(comp, ast.Constant) and isinstance(comp.value, str)):
                continue

            if isinstance(left, ast.Subscript):
                key = None
                # py3.9+: Subscript.slice is expr; older ast.Index wrapper may appear.
                if isinstance(left.slice, ast.Constant):
                    key = left.slice.value
                elif hasattr(ast, "Index") and isinstance(left.slice, ast.Index):  # pragma: no cover
                    if isinstance(left.slice.value, ast.Constant):
                        key = left.slice.value.value
                if key == "action":
                    actions.add(comp.value.upper())

    # Pattern: return {"action": "ACTION", ...} in middleware paths
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (
                isinstance(k, ast.Constant)
                and k.value == "action"
                and isinstance(v, ast.Constant)
                and isinstance(v.value, str)
            ):
                actions.add(v.value.upper())

    return actions


def _ast_extract_supported_actions(source: str) -> Set[str]:
    """
    Extract the SUPPORTED_ACTIONS list literal from executor source.
    """
    actions: Set[str] = set()
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return actions

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SUPPORTED_ACTIONS":
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                actions.add(elt.value.upper())
    return actions


def _extract_router_intents(router_source: str) -> Set[str]:
    """
    Extract action names from router_enhanced.py by finding all
    _mk("ACTION", ...) calls and {"action": "ACTION", ...} dicts.
    """
    intents: Set[str] = set()
    # _mk("ACTION_NAME", ...) and helper mk wrappers such as _eli_lrf_mk(...)
    for m in re.finditer(r'(?:^|[^A-Za-z0-9_])[A-Za-z0-9_]*_mk\(\s*"([A-Z_]+)"', router_source):
        intents.add(m.group(1))
    # {"action": "ACTION_NAME", ...}  (legacy compat returns)
    for m in re.finditer(r'"action"\s*:\s*"([A-Z_]+)"', router_source):
        intents.add(m.group(1))
    return intents


def _read_plugin_actions(repo_root: Path) -> Dict[str, List[str]]:
    """Read plugin registry index.json → {plugin_name: [ACTION, ...]}."""
    _idx_candidates = [
        repo_root / "eli" / "plugins" / "registry" / "index.json",
        repo_root / "plugins" / "registry" / "index.json",
    ]
    idx = next((p for p in _idx_candidates if p.exists()), _idx_candidates[-1])
    result: Dict[str, List[str]] = {}
    if not idx.exists():
        return result
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
        # Format 1: {"plugins": [{id, actions}, ...]}
        if isinstance(data, dict) and "plugins" in data:
            for plugin in data["plugins"]:
                if not isinstance(plugin, dict):
                    continue
                name = plugin.get("id") or plugin.get("name", "unknown")
                acts = plugin.get("actions", [])
                if isinstance(acts, list) and acts:
                    result[str(name)] = [a.upper() for a in acts if isinstance(a, str)]
        # Format 2: flat {name: {actions: [...]}}
        elif isinstance(data, dict):
            for name, info in data.items():
                if not isinstance(info, dict):
                    continue
                acts = info.get("actions", info.get("capabilities", []))
                if isinstance(acts, list):
                    result[name] = [a.upper() for a in acts if isinstance(a, str)]
    except Exception as exc:
        log.warning("capability_sync: plugin registry read failed: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Main sync class
# ---------------------------------------------------------------------------

class CapabilitySync:
    """
    Discovers all capabilities from source files (no imports),
    diffs against last known state, writes canonical inventory JSON.

    Usage:
        sync = CapabilitySync(repo_root=Path(__file__).resolve().parents[2])
        delta = sync.run()
        if delta.has_changes:
            print(delta.summary())
    """

    INVENTORY_FILE = "capability_inventory.generated.json"
    SNAPSHOT_FILE = ".capability_snapshot.json"

    def __init__(self, repo_root: Optional[Path] = None):
        if repo_root is None:
            try:
                from eli.core.paths import get_paths
                repo_root = get_paths().project_root
            except Exception:
                repo_root = Path(__file__).resolve().parents[3]
        self.repo_root = Path(repo_root)
        self.inventory_path = self.repo_root / self.INVENTORY_FILE
        self.snapshot_path = self.repo_root / self.SNAPSHOT_FILE

    # ---- public ----------------------------------------------------------

    def run(self) -> SyncDelta:
        """Full sync: discover → diff → write → return delta."""
        current = self.discover()
        previous = self._load_snapshot()
        delta = self._diff(previous, current)
        delta.timestamp = time.time()
        self._write_inventory(current)
        if delta.has_changes:
            self._write_snapshot(current)
            log.info("capability_sync: %s", delta.summary())
        return delta

    def discover(self) -> Dict[str, Dict[str, Any]]:
        """Return {ACTION_NAME: {source: ..., routable: bool, plugin: str|None}}."""
        caps: Dict[str, Dict[str, Any]] = {}

        # 1. Executor: AST-parse for dispatch actions + SUPPORTED_ACTIONS.
        # Keep legacy candidates, but prefer the current canonical layout.
        _exec_candidates = [
            self.repo_root / "eli" / "execution" / "executor_enhanced.py",
            self.repo_root / "eli" / "tools" / "automation" / "executor_enhanced.py",
            self.repo_root / "execution" / "executor_enhanced.py",
            self.repo_root / "tools" / "automation" / "executor_enhanced.py",
        ]
        executor_path = next((p for p in _exec_candidates if p.exists()), None)
        if executor_path:
            src = executor_path.read_text(encoding="utf-8", errors="replace")
            dispatch = _ast_extract_dispatch_actions(src)
            supported = _ast_extract_supported_actions(src)
            all_executor = dispatch | supported
            for action in all_executor:
                caps[action] = {
                    "source": "executor",
                    "in_supported_list": action in supported,
                    "in_dispatch": action in dispatch,
                    "routable": False,
                    "plugin": None,
                }

        # 2. Router: regex-extract intent names.
        # Keep legacy candidates, but prefer the current canonical layout.
        _router_candidates = [
            self.repo_root / "eli" / "execution" / "router_enhanced.py",
            self.repo_root / "eli" / "tools" / "automation" / "router_enhanced.py",
            self.repo_root / "execution" / "router_enhanced.py",
            self.repo_root / "tools" / "automation" / "router_enhanced.py",
        ]
        router_path = next((p for p in _router_candidates if p.exists()), None)
        if router_path and router_path.exists():
            src = router_path.read_text(encoding="utf-8", errors="replace")
            intents = _extract_router_intents(src)
            for intent in intents:
                if intent in caps:
                    caps[intent]["routable"] = True
                    caps[intent]["source"] = "executor+router"
                else:
                    caps[intent] = {
                        "source": "router_only",
                        "in_supported_list": False,
                        "in_dispatch": False,
                        "routable": True,
                        "plugin": None,
                    }

        # 3. Plugins
        plugin_map = _read_plugin_actions(self.repo_root)
        for plugin_name, actions in plugin_map.items():
            for action in actions:
                if action in caps:
                    caps[action]["plugin"] = plugin_name
                    if "+plugin" not in caps[action]["source"]:
                        caps[action]["source"] += f"+plugin:{plugin_name}"
                else:
                    caps[action] = {
                        "source": f"plugin:{plugin_name}",
                        "in_supported_list": False,
                        "in_dispatch": False,
                        "routable": False,
                        "plugin": plugin_name,
                    }

        return dict(sorted(caps.items()))

    def capability_count(self) -> int:
        return len(self.discover())

    def live_capability_names(self, include_internal: bool = True) -> List[str]:
        """Sorted list of action names — drop-in for LIST_CAPABILITIES."""
        caps = self.discover()
        if include_internal:
            return sorted(caps.keys())
        # "internal" = in dispatch but not in SUPPORTED_ACTIONS and not routable
        return sorted(
            k for k, v in caps.items()
            if v.get("in_supported_list") or v.get("routable") or v.get("plugin")
        )

    # ---- diff ------------------------------------------------------------

    def _diff(self, prev: Dict[str, Any], curr: Dict[str, Dict[str, Any]]) -> SyncDelta:
        delta = SyncDelta()
        prev_keys = set(prev.keys())
        curr_keys = set(curr.keys())
        delta.added = sorted(curr_keys - prev_keys)
        delta.removed = sorted(prev_keys - curr_keys)
        for key in sorted(curr_keys & prev_keys):
            old_src = prev.get(key, {}).get("source", "")
            new_src = curr.get(key, {}).get("source", "")
            if old_src != new_src:
                delta.changed.append(key)
        return delta

    # ---- persistence -----------------------------------------------------

    def _load_snapshot(self) -> Dict[str, Any]:
        if not self.snapshot_path.exists():
            return {}
        try:
            data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            return data.get("capabilities", {})
        except Exception:
            return {}

    def _write_snapshot(self, caps: Dict[str, Dict[str, Any]]) -> None:
        payload = {"generated_at": time.time(), "count": len(caps), "capabilities": caps}
        try:
            self.snapshot_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except Exception as exc:
            log.warning("capability_sync: snapshot write failed: %s", exc)

    def _write_inventory(self, caps: Dict[str, Dict[str, Any]]) -> None:
        payload = {
            "generated_at": time.time(),
            "generator": "brain.awareness.capability_sync",
            "count": len(caps),
            "capabilities": [
                {"action": k, **v} for k, v in caps.items()
            ],
        }
        try:
            self.inventory_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        except Exception as exc:
            log.warning("capability_sync: inventory write failed: %s", exc)
