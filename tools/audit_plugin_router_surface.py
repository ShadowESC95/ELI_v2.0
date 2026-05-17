#!/usr/bin/env python3
import ast
import json
from pathlib import Path

ROOT = Path.cwd()
MANIFEST = ROOT / "capability_manifest.json"
ROUTER = ROOT / "eli/execution/router_enhanced.py"

data = json.loads(MANIFEST.read_text(encoding="utf-8"))
router_src = ROUTER.read_text(encoding="utf-8")
tree = ast.parse(router_src)

plugin_actions = sorted({
    str(c["action"]).upper()
    for c in data.get("capabilities", [])
    if c.get("plugin") and c.get("active")
})

router_mk_actions = set()
router_literal_actions = set()

for node in ast.walk(tree):
    # _mk("ACTION", ...)
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "_mk":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                router_mk_actions.add(node.args[0].value.upper())

    # {"action": "ACTION"}
    if isinstance(node, ast.Dict):
        keys = node.keys
        vals = node.values
        for k, v in zip(keys, vals):
            if (
                isinstance(k, ast.Constant)
                and k.value == "action"
                and isinstance(v, ast.Constant)
                and isinstance(v.value, str)
            ):
                router_literal_actions.add(v.value.upper())

router_actions = router_mk_actions | router_literal_actions

missing = [a for a in plugin_actions if a not in router_actions]
present = [a for a in plugin_actions if a in router_actions]

print("=== Plugin Router Surface Audit ===")
print(f"plugin_actions: {len(plugin_actions)}")
print(f"router_actions_detected: {len(router_actions)}")
print()

print("=== Present plugin actions in router ===")
for a in present:
    print(f"OK: {a}")

print()
print("=== Missing plugin actions from router ===")
for a in missing:
    print(f"MISSING: {a}")

print()
print("=== Suggested next target ===")
if missing:
    print("Add natural-language router rules for missing plugin actions.")
else:
    print("Clean: all active plugin actions are visible in router source.")
