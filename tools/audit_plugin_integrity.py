#!/usr/bin/env python3
import ast
import json
from pathlib import Path

ROOT = Path.cwd()
REGISTRY = ROOT / "eli/plugins/registry/index.json"
PLUGINS = ROOT / "eli/plugins"

CANONICAL_ALIASES = {
    "GET_WEATHER": {"GET_WEATHER", "WEATHER"},
    "WEB_SEARCH": {"WEB_SEARCH", "SEARCH", "WEB", "WEB_SEARCH_PLUGIN"},
    "SPEAK": {"SPEAK", "SAY", "TTS"},
    "SMART_HOME": {"SMART_HOME", "ON", "OFF", "TURN_ON", "TURN_OFF", "STATE", "LIST"},
    "POMODORO_START": {"POMODORO_START", "START"},
    "POMODORO_STOP": {"POMODORO_STOP", "STOP"},
    "POMODORO_STATUS": {"POMODORO_STATUS", "STATUS"},
    "SYSTEM_STATS": {"SYSTEM_STATS"},
    "CPU_USAGE": {"CPU_USAGE"},
    "RAM_USAGE": {"RAM_USAGE"},
    "NEW_NOTE": {"NEW_NOTE"},
    "SEARCH_NOTES": {"SEARCH_NOTES"},
    "LIST_NOTES": {"LIST_NOTES"},
}

failures = []
warnings = []
info = []


def load_registry():
    if not REGISTRY.exists():
        failures.append(f"Missing plugin registry: {REGISTRY}")
        return []

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))

    if isinstance(data, dict) and isinstance(data.get("plugins"), list):
        return data["plugins"]

    if isinstance(data, dict):
        out = []
        for pid, meta in data.items():
            if isinstance(meta, dict):
                m = dict(meta)
                m.setdefault("id", pid)
                out.append(m)
        return out

    failures.append("Unsupported plugin registry JSON shape")
    return []


def ast_extract(path: Path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    all_strings = set()
    action_dict_keys = set()
    actions_list_values = set()
    function_names = set()
    class_names = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            all_strings.add(node.value.upper())

        if isinstance(node, ast.FunctionDef):
            function_names.add(node.name.upper())

        if isinstance(node, ast.ClassDef):
            class_names.add(node.name.upper())

        if isinstance(node, ast.Assign):
            for target in node.targets:
                # self.actions = {...} or actions = {...}
                is_actions_target = False
                is_actions_list_target = False

                if isinstance(target, ast.Name) and target.id.lower() in {"actions", "action"}:
                    is_actions_target = True
                    is_actions_list_target = True

                if isinstance(target, ast.Attribute) and target.attr.lower() in {"actions", "action"}:
                    is_actions_target = True
                    is_actions_list_target = True

                if is_actions_target and isinstance(node.value, ast.Dict):
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            action_dict_keys.add(k.value.upper())

                if is_actions_list_target and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            actions_list_values.add(elt.value.upper())

    return {
        "all_strings": all_strings,
        "action_dict_keys": action_dict_keys,
        "actions_list_values": actions_list_values,
        "function_names": function_names,
        "class_names": class_names,
    }


def main():
    plugins = load_registry()

    print("=== Plugin Integrity Audit v2 ===")
    print(f"registry: {REGISTRY}")
    print(f"registered_plugins: {len(plugins)}")
    print()

    for meta in plugins:
        pid = meta.get("id") or meta.get("name")
        actions = [str(a).upper() for a in meta.get("actions", [])]

        if not pid:
            failures.append(f"Registry entry missing id/name: {meta}")
            continue

        plugin_py = PLUGINS / pid / "plugin.py"

        print(f"PLUGIN: {pid}")
        print(f"  registry_actions: {actions}")

        if not plugin_py.exists():
            failures.append(f"{pid}: missing plugin.py at {plugin_py}")
            print()
            continue

        try:
            extracted = ast_extract(plugin_py)
        except Exception as exc:
            failures.append(f"{pid}: failed to AST-parse plugin.py: {exc!r}")
            print()
            continue

        action_dict_keys = extracted["action_dict_keys"]
        actions_list_values = extracted["actions_list_values"]
        all_strings = extracted["all_strings"]
        function_names = extracted["function_names"]

        print(f"  action_dict_keys: {sorted(action_dict_keys)}")
        print(f"  actions_list_values: {sorted(actions_list_values)}")
        print(f"  relevant_functions: {sorted([f for f in function_names if any(k in f for k in ['HANDLE','SEARCH','WEATHER','POMODORO','START','STOP','STATUS','SPEAK','NOTE','STATS'])])}")

        for action in actions:
            aliases = CANONICAL_ALIASES.get(action, {action})
            found_in_mapping = bool(action_dict_keys & aliases)
            found_in_actions_list = bool(actions_list_values & aliases)
            found_in_strings = bool(all_strings & aliases)
            found_in_functions = any(alias in function_names for alias in aliases)

            if found_in_mapping:
                info.append(f"{pid}:{action}: canonical action or alias is mapped in plugin actions dict")
            elif found_in_actions_list:
                info.append(f"{pid}:{action}: canonical action appears in ACTIONS/actions list")
            elif found_in_strings or found_in_functions:
                warnings.append(f"{pid}:{action}: canonical action/alias appears in code but not direct actions mapping")
            else:
                failures.append(f"{pid}:{action}: no canonical action or known alias found in plugin.py")

        print()

    print("=== Summary ===")
    print(f"failures: {len(failures)}")
    print(f"warnings: {len(warnings)}")
    print(f"info: {len(info)}")

    if failures:
        print()
        print("=== FAILURES ===")
        for x in failures:
            print("FAIL:", x)

    if warnings:
        print()
        print("=== WARNINGS ===")
        for x in warnings:
            print("WARN:", x)

    if info:
        print()
        print("=== INFO ===")
        for x in info:
            print("INFO:", x)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
