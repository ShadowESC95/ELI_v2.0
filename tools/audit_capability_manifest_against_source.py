#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import importlib
from pathlib import Path

ROOT = Path.cwd()
MANIFEST = ROOT / "capability_manifest.json"
EXECUTOR = ROOT / "eli/execution/executor_enhanced.py"
ROUTER = ROOT / "eli/execution/router_enhanced.py"
PLUGIN_REGISTRY = ROOT / "eli/plugins/registry/index.json"

failures = []
warnings = []

# These are low-level primitives/aliases seen in routing/input logic.
# They are not public manifest capabilities unless explicitly declared.
SOURCE_ONLY_INTERNAL_LITERALS = {
    "CLICK",
    "MOVE",
    "SCROLL",
    "START",
    "STOP",
}

# These may be dispatched indirectly through diagnostics/helper layers rather
# than plain `if a == "ACTION"` AST patterns.
SAFE_INDIRECT_DISPATCH_CHECKS = {
    "STT_DIAGNOSTICS",
    "VOICE_DIAGNOSTICS",
}


def _is_action_like(value: str, known_actions: set[str]) -> bool:
    original = str(value or "").strip()
    v = original.upper()

    if not v:
        return False

    if v in known_actions:
        return True

    if v.startswith("__") or v.startswith("ELI_"):
        return False

    return v.replace("_", "").isalnum() and v == original.upper()


def extract_if_actions(path: Path, known_actions: set[str]) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    actions = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue

        test = node.test

        if isinstance(test, ast.Compare):
            for comp in test.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    val = comp.value.strip().upper()
                    if _is_action_like(comp.value, known_actions):
                        actions.add(val)

            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                    for elt in comp.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            val = elt.value.strip().upper()
                            if _is_action_like(elt.value, known_actions):
                                actions.add(val)

    return actions


def extract_supported(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    supported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SUPPORTED_ACTIONS":
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                supported.add(elt.value.strip().upper())

    return supported


def extract_router_actions(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    actions = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "_mk":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    actions.add(node.args[0].value.strip().upper())

        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "action"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                ):
                    actions.add(v.value.strip().upper())

    return actions


def extract_plugin_actions(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    plugins = data.get("plugins", []) if isinstance(data, dict) else []
    out = {}

    for plugin in plugins:
        pid = plugin.get("id")
        acts = [str(a).strip().upper() for a in plugin.get("actions", [])]
        if pid:
            out[pid] = acts

    return out


def indirect_executor_handles(action: str) -> bool:
    if action not in SAFE_INDIRECT_DISPATCH_CHECKS:
        return False

    try:
        ex = importlib.import_module("eli.execution.executor_enhanced")
        fn = getattr(ex, "execute")
        result = fn(action, {})
    except Exception:
        return False

    if not isinstance(result, dict):
        return False

    text = " ".join(
        str(result.get(k, ""))
        for k in ("error", "content", "response")
    ).lower()

    if "unsupported action" in text or "unknown action" in text:
        return False

    return True


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    caps = manifest.get("capabilities", [])
    by_action = {str(c.get("action", "")).strip().upper(): c for c in caps}
    manifest_actions = set(by_action)

    supported = extract_supported(EXECUTOR)
    routable_raw = extract_router_actions(ROUTER)
    plugin_map = extract_plugin_actions(PLUGIN_REGISTRY)
    plugin_actions = {a for acts in plugin_map.values() for a in acts}

    # Do not treat low-level source-only verbs as public routable actions.
    routable = {
        a for a in routable_raw
        if a in manifest_actions or a not in SOURCE_ONLY_INTERNAL_LITERALS
    }

    known_actions = manifest_actions | supported | routable | plugin_actions
    dispatch = extract_if_actions(EXECUTOR, known_actions)

    for action in SAFE_INDIRECT_DISPATCH_CHECKS:
        if indirect_executor_handles(action):
            dispatch.add(action)

    print("=== Capability Manifest Against Source Audit v3 ===")
    print(f"manifest_generated_at: {manifest.get('generated_at')}")
    print(f"manifest_entries: {len(caps)}")
    print(f"source_dispatch_actions: {len(dispatch)}")
    print(f"source_supported_actions: {len(supported)}")
    print(f"source_router_actions_raw: {len(routable_raw)}")
    print(f"source_router_actions_public: {len(routable)}")
    print(f"registry_plugin_actions: {len(plugin_actions)}")
    print()

    for action, cap in sorted(by_action.items()):
        expected_dispatch = action in dispatch
        expected_supported = action in supported
        expected_routable = action in routable

        if bool(cap.get("in_dispatch")) != expected_dispatch:
            failures.append(
                f"{action}: manifest in_dispatch={cap.get('in_dispatch')} but source says {expected_dispatch}"
            )

        if bool(cap.get("in_supported_list")) != expected_supported:
            failures.append(
                f"{action}: manifest in_supported_list={cap.get('in_supported_list')} but source says {expected_supported}"
            )

        if bool(cap.get("routable")) != expected_routable:
            failures.append(
                f"{action}: manifest routable={cap.get('routable')} but source says {expected_routable}"
            )

    public_source_actions = (supported | routable | plugin_actions) - SOURCE_ONLY_INTERNAL_LITERALS
    for action in sorted(public_source_actions - manifest_actions):
        warnings.append(f"{action}: present in public source surface but missing from manifest")

    print("=== Summary ===")
    print(f"failures: {len(failures)}")
    print(f"warnings: {len(warnings)}")

    if failures:
        print()
        print("=== FAILURES ===")
        for item in failures:
            print("FAIL:", item)

    if warnings:
        print()
        print("=== WARNINGS ===")
        for item in warnings:
            print("WARN:", item)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
