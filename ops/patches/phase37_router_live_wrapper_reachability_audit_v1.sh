#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase37_router_live_wrapper_reachability_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 37 — Router Live Wrapper Reachability Audit

Generated: $(date -Is)  
Root: $ROOT  
Router: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase 36 v2 established a stable semantic golden baseline for router behaviour.

Phase 37 now determines which historical wrapper/capture surfaces are still
reachable from the final exported \`route()\` callable and which are dead legacy
rebinding residue.

This is required before the real wrapper-chain flattening patch.

## Audit outputs

1. Final public surface identity probe
2. Recursive closure/global callable reachability graph from final route()
3. Reachable previous-route capture names
4. Historical capture sites classified as LIVE / DEAD / UNKNOWN
5. Route-related function inventory with source lines
6. Import-time router print surface inventory
7. Flattening interpretation and Phase 38 target map
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/00_py_compile.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import inspect
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from types import FunctionType
from typing import Any

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

# ---------------------------------------------------------------------
# Import router after compile so we inspect the actual live runtime object.
# ---------------------------------------------------------------------

import eli.execution.router_enhanced as router

SURFACES = ("route", "route_intent", "route_command", "parse_command", "classify")

# ---------------------------------------------------------------------
# 1. Public surface identity probe
# ---------------------------------------------------------------------

identity_lines = [
    "=== PHASE 37 PUBLIC ROUTER SURFACE IDENTITY ==="
]

canonical = getattr(router, "route", None)
all_same = True

for name in SURFACES:
    fn = getattr(router, name, None)
    same = fn is canonical
    all_same = all_same and same
    identity_lines.append(
        f"{name}: "
        f"callable={callable(fn)} "
        f"same_as_route={same} "
        f"id={id(fn)} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"qualname={getattr(fn, '__qualname__', None)!r} "
        f"module={getattr(fn, '__module__', None)!r} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else '-'}"
    )

identity_lines.append("")
identity_lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "01_public_surface_identity.txt").write_text(
    "\n".join(identity_lines) + "\n",
    encoding="utf-8",
)

if not all_same:
    raise RuntimeError("Phase 37 precondition failed: public routing surfaces are no longer canonical")

# ---------------------------------------------------------------------
# 2. Source-side function inventory — route-related functions anywhere in AST
# ---------------------------------------------------------------------

route_related_functions: list[dict[str, Any]] = []

class FunctionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        scope = ".".join(self.scope_stack) if self.scope_stack else "<module-or-block>"
        name = node.name

        if (
            "route" in name.lower()
            or name in {"classify", "parse_command", "route_command", "route_intent"}
            or any(tok in name.lower() for tok in ("guard", "compat", "scope", "contract", "intent"))
        ):
            route_related_functions.append({
                "name": name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", node.lineno),
                "scope": scope,
                "args": [
                    *(a.arg for a in getattr(node.args, "posonlyargs", [])),
                    *(a.arg for a in node.args.args),
                    *(["*" + node.args.vararg.arg] if node.args.vararg else []),
                    *(a.arg for a in node.args.kwonlyargs),
                    *(["**" + node.args.kwarg.arg] if node.args.kwarg else []),
                ],
            })

        self.scope_stack.append(name)
        self.generic_visit(node)
        self.scope_stack.pop()

FunctionVisitor().visit(tree)

func_lines = [
    "=== PHASE 37 ROUTE-RELATED FUNCTION INVENTORY ===",
    "name | lines | scope | args",
    "-" * 200,
]
for item in sorted(route_related_functions, key=lambda x: (x["lineno"], x["name"])):
    func_lines.append(
        f"{item['name']} | {item['lineno']}-{item['end_lineno']} | "
        f"{item['scope']} | {item['args']}"
    )

func_lines.append("")
func_lines.append(f"TOTAL_ROUTE_RELATED_FUNCTIONS={len(route_related_functions)}")

(out / "02_route_related_function_inventory.txt").write_text(
    "\n".join(func_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 3. Historical previous-symbol capture site inventory
# ---------------------------------------------------------------------

capture_patterns = [
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*route\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*route_intent\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*route_command\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*globals\(\)\.get\("route"\)\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*globals\(\)\.get\("route_intent"\)\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*globals\(\)\.get\("route_command"\)\s*(?:#.*)?$'),
]

capture_sites: list[dict[str, Any]] = []

for lineno, line in enumerate(lines, start=1):
    for pat in capture_patterns:
        m = pat.match(line)
        if m:
            capture_sites.append({
                "lineno": lineno,
                "symbol": m.group(1),
                "line": line.strip(),
            })
            break

capture_inventory = [
    "=== PHASE 37 HISTORICAL PREVIOUS-SYMBOL CAPTURE SITES ===",
]
for item in capture_sites:
    capture_inventory.append(
        f"{item['lineno']}: {item['symbol']} <- {item['line']}"
    )
capture_inventory.append("")
capture_inventory.append(f"TOTAL_CAPTURE_SITES={len(capture_sites)}")

(out / "03_historical_capture_sites.txt").write_text(
    "\n".join(capture_inventory) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 4. Recursive runtime callable reachability graph from final route()
# ---------------------------------------------------------------------

def callable_label(obj: Any) -> str:
    if isinstance(obj, FunctionType):
        code = getattr(obj, "__code__", None)
        return (
            f"{getattr(obj, '__module__', '?')}."
            f"{getattr(obj, '__qualname__', getattr(obj, '__name__', '?'))}"
            f"@{getattr(code, 'co_firstlineno', '?')}"
            f"#id={id(obj)}"
        )
    return f"{type(obj).__name__}#id={id(obj)}"

def function_globals_callable_edges(fn: FunctionType) -> list[tuple[str, FunctionType]]:
    edges: list[tuple[str, FunctionType]] = []
    code = getattr(fn, "__code__", None)
    names = set(getattr(code, "co_names", ())) if code else set()
    glb = getattr(fn, "__globals__", {}) or {}

    for name in sorted(names):
        val = glb.get(name)
        if isinstance(val, FunctionType):
            edges.append((f"global:{name}", val))
    return edges

def function_closure_callable_edges(fn: FunctionType) -> list[tuple[str, FunctionType]]:
    edges: list[tuple[str, FunctionType]] = []
    closure = getattr(fn, "__closure__", None) or ()
    freevars = getattr(getattr(fn, "__code__", None), "co_freevars", ()) or ()

    for idx, cell in enumerate(closure):
        name = freevars[idx] if idx < len(freevars) else f"<cell_{idx}>"
        try:
            val = cell.cell_contents
        except ValueError:
            continue
        if isinstance(val, FunctionType):
            edges.append((f"closure:{name}", val))
    return edges

def function_default_callable_edges(fn: FunctionType) -> list[tuple[str, FunctionType]]:
    edges: list[tuple[str, FunctionType]] = []

    defaults = getattr(fn, "__defaults__", None) or ()
    for idx, val in enumerate(defaults):
        if isinstance(val, FunctionType):
            edges.append((f"default:{idx}", val))

    kwdefaults = getattr(fn, "__kwdefaults__", None) or {}
    for name, val in kwdefaults.items():
        if isinstance(val, FunctionType):
            edges.append((f"kwdefault:{name}", val))

    return edges

root_fn = canonical
queue: deque[FunctionType] = deque()
visited_ids: set[int] = set()
node_by_id: dict[int, dict[str, Any]] = {}
edges: list[dict[str, Any]] = []

if isinstance(root_fn, FunctionType):
    queue.append(root_fn)

while queue:
    fn = queue.popleft()
    fn_id = id(fn)
    if fn_id in visited_ids:
        continue
    visited_ids.add(fn_id)

    node_by_id[fn_id] = {
        "label": callable_label(fn),
        "name": getattr(fn, "__name__", None),
        "qualname": getattr(fn, "__qualname__", None),
        "module": getattr(fn, "__module__", None),
        "firstlineno": getattr(getattr(fn, "__code__", None), "co_firstlineno", None),
    }

    all_edges = (
        function_closure_callable_edges(fn)
        + function_default_callable_edges(fn)
        + function_globals_callable_edges(fn)
    )

    for relation, target in all_edges:
        target_id = id(target)
        edges.append({
            "from_id": fn_id,
            "from": callable_label(fn),
            "relation": relation,
            "to_id": target_id,
            "to": callable_label(target),
        })
        if target_id not in visited_ids:
            queue.append(target)

graph_json = {
    "root": callable_label(root_fn),
    "node_count": len(node_by_id),
    "edge_count": len(edges),
    "nodes": list(node_by_id.values()),
    "edges": edges,
}

(out / "04_live_callable_reachability_graph.json").write_text(
    json.dumps(graph_json, indent=2, ensure_ascii=False, sort_keys=True),
    encoding="utf-8",
)

graph_lines = [
    "=== PHASE 37 LIVE CALLABLE REACHABILITY GRAPH FROM FINAL route() ===",
    f"root={graph_json['root']}",
    f"reachable_function_nodes={graph_json['node_count']}",
    f"reachable_callable_edges={graph_json['edge_count']}",
    "",
    "--- NODES ---",
]

for node in sorted(node_by_id.values(), key=lambda n: (n["firstlineno"] or 10**9, n["label"])):
    graph_lines.append(node["label"])

graph_lines.append("")
graph_lines.append("--- EDGES ---")
for edge in edges:
    graph_lines.append(
        f"{edge['from']} --[{edge['relation']}]--> {edge['to']}"
    )

(out / "05_live_callable_reachability_graph.txt").write_text(
    "\n".join(graph_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 5. Which named capture symbols are actually referenced by reachable callables?
# ---------------------------------------------------------------------

reachable_global_names: set[str] = set()

for fn_id in visited_ids:
    node = next((obj for obj in [root_fn] if id(obj) == fn_id), None)

# Build function objects by walking reachable ids from actual edge/node traversal.
reachable_functions: list[FunctionType] = []
seen_reachable_fn_ids: set[int] = set()

queue2: deque[FunctionType] = deque()
if isinstance(root_fn, FunctionType):
    queue2.append(root_fn)

while queue2:
    fn = queue2.popleft()
    if id(fn) in seen_reachable_fn_ids:
        continue
    seen_reachable_fn_ids.add(id(fn))
    reachable_functions.append(fn)

    for _, target in (
        function_closure_callable_edges(fn)
        + function_default_callable_edges(fn)
        + function_globals_callable_edges(fn)
    ):
        if id(target) not in seen_reachable_fn_ids:
            queue2.append(target)

for fn in reachable_functions:
    code = getattr(fn, "__code__", None)
    glb = getattr(fn, "__globals__", {}) or {}
    for name in getattr(code, "co_names", ()) if code else ():
        if name in glb:
            reachable_global_names.add(name)

capture_status_rows = [
    "=== PHASE 37 CAPTURE-SITE LIVE / DEAD CLASSIFICATION ===",
    "line | symbol | status | rationale",
    "-" * 220,
]

capture_status_json: list[dict[str, Any]] = []
live_count = 0
dead_count = 0
unknown_count = 0

router_globals = vars(router)

for item in capture_sites:
    symbol = item["symbol"]
    runtime_obj = router_globals.get(symbol, None)
    symbol_is_referenced = symbol in reachable_global_names
    runtime_is_callable = isinstance(runtime_obj, FunctionType)

    if symbol_is_referenced:
        status = "LIVE"
        rationale = "symbol name appears in a reachable callable's global lookups"
        live_count += 1
    elif runtime_is_callable:
        status = "DEAD_OR_INDIRECT"
        rationale = "symbol exists as callable but is not directly referenced by reachable callable globals"
        unknown_count += 1
    else:
        status = "DEAD"
        rationale = "symbol not directly reachable and runtime global is absent/non-callable"
        dead_count += 1

    capture_status_rows.append(
        f"{item['lineno']} | {symbol} | {status} | {rationale}"
    )
    capture_status_json.append({
        **item,
        "status": status,
        "rationale": rationale,
        "symbol_is_referenced_by_reachable_global_lookup": symbol_is_referenced,
        "runtime_global_type": type(runtime_obj).__name__ if runtime_obj is not None else None,
        "runtime_global_callable_function": runtime_is_callable,
    })

capture_status_rows.append("")
capture_status_rows.append(f"LIVE_CAPTURE_SITE_COUNT={live_count}")
capture_status_rows.append(f"DEAD_CAPTURE_SITE_COUNT={dead_count}")
capture_status_rows.append(f"DEAD_OR_INDIRECT_CAPTURE_SITE_COUNT={unknown_count}")
capture_status_rows.append(f"TOTAL_CAPTURE_SITE_COUNT={len(capture_sites)}")

(out / "06_capture_site_live_dead_classification.txt").write_text(
    "\n".join(capture_status_rows) + "\n",
    encoding="utf-8",
)

(out / "07_capture_site_live_dead_classification.json").write_text(
    json.dumps(capture_status_json, indent=2, ensure_ascii=False, sort_keys=True),
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 6. Named wrapper / helper line-range source windows for flattening
# ---------------------------------------------------------------------

window_targets = [
    "_eli_open_typo_norm",
    "_eli_mqc_clean_query",
    "_eli_voice_contract_route",
    "_eli_voice_contract_wrap_callable",
    "_eli_lrf_pre_route",
    "_eli_lrf_route",
    "_eli_lrf_route_intent",
    "_eli_pm_pre_route",
    "_eli_pm_route",
    "_eli_pm_route_intent",
    "_eli_self_improvement_phrase_guard",
    "_eli_runtime_cognition_failure_guard",
    "_eli_final_personal_memory_precedence_route",
    "_eli_final_personal_memory_precedence_route_intent",
]

func_defs_by_name: dict[str, list[ast.FunctionDef]] = defaultdict(list)

class CollectFunctions(ast.NodeVisitor):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        func_defs_by_name[node.name].append(node)
        self.generic_visit(node)

CollectFunctions().visit(tree)

windows: list[str] = [
    "=== PHASE 37 NAMED WRAPPER / HELPER SOURCE WINDOWS ==="
]

for target in window_targets:
    defs = func_defs_by_name.get(target, [])
    if not defs:
        windows.append("")
        windows.append("=" * 120)
        windows.append(f"{target}: NOT FOUND")
        windows.append("=" * 120)
        continue

    for node in defs:
        start = max(1, node.lineno - 4)
        end = min(len(lines), getattr(node, "end_lineno", node.lineno) + 4)
        windows.append("")
        windows.append("=" * 120)
        windows.append(f"{target}: lines={node.lineno}-{getattr(node, 'end_lineno', node.lineno)}")
        windows.append("=" * 120)
        for lineno in range(start, end + 1):
            windows.append(f"{lineno:>6}: {lines[lineno - 1]}")

(out / "08_named_wrapper_helper_source_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 7. Router import-time print surface inventory
# ---------------------------------------------------------------------

print_rows = [
    "=== PHASE 37 ROUTER IMPORT-TIME PRINT SURFACE INVENTORY ==="
]
print_count = 0

for lineno, line in enumerate(lines, start=1):
    if "print(" in line:
        print_count += 1
        print_rows.append(f"{lineno}: {line.rstrip()}")

print_rows.append("")
print_rows.append(f"TOTAL_PRINT_SURFACES={print_count}")

(out / "09_router_print_surface_inventory.txt").write_text(
    "\n".join(print_rows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 8. Interpret flattening posture
# ---------------------------------------------------------------------

interpretation = [
    "=== PHASE 37 FLATTENING INTERPRETATION ===",
    "",
    f"Public surfaces canonical: {all_same}",
    f"Reachable function nodes from final route(): {graph_json['node_count']}",
    f"Reachable callable edges from final route(): {graph_json['edge_count']}",
    f"Historical capture sites scanned: {len(capture_sites)}",
    f"Capture sites classified LIVE: {live_count}",
    f"Capture sites classified DEAD: {dead_count}",
    f"Capture sites classified DEAD_OR_INDIRECT: {unknown_count}",
    "",
    "Phase 38 flattening rule:",
    "1. Preserve every behaviour represented in the Phase 36 v2 golden baseline.",
    "2. Preserve only genuinely reachable live semantic stages in the final route chain.",
    "3. Do not mechanically carry forward dead previous-symbol capture scaffolding.",
    "4. Replace nested import-time route rebinding with one explicit canonical dispatch pipeline.",
    "5. Rebind route_intent / route_command / parse_command / classify exactly once.",
    "",
    "Primary files to read before Phase 38:",
    "- 05_live_callable_reachability_graph.txt",
    "- 06_capture_site_live_dead_classification.txt",
    "- 08_named_wrapper_helper_source_windows.txt",
    "- Phase 36 v2 golden semantic baseline JSON",
]

(out / "10_flattening_interpretation.txt").write_text(
    "\n".join(interpretation) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 9. Console digest
# ---------------------------------------------------------------------

digest = [
    "=== PHASE 37 DIGEST ===",
    f"Public surfaces canonical: {all_same}",
    f"Reachable route-chain function nodes: {graph_json['node_count']}",
    f"Reachable callable edges: {graph_json['edge_count']}",
    f"Historical capture sites scanned: {len(capture_sites)}",
    f"LIVE capture sites: {live_count}",
    f"DEAD capture sites: {dead_count}",
    f"DEAD_OR_INDIRECT capture sites: {unknown_count}",
    "",
    "Phase 37 complete. This is the final reachability map required before the actual router wrapper-chain flattening rewrite.",
    "",
    "Review next:",
    "- 05_live_callable_reachability_graph.txt",
    "- 06_capture_site_live_dead_classification.txt",
    "- 08_named_wrapper_helper_source_windows.txt",
    "- 10_flattening_interpretation.txt",
]

(out / "11_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
PY

{
  echo
  echo "## Verification artifacts"
  echo "- \`00_py_compile.txt\`"
  echo "- \`01_public_surface_identity.txt\`"
  echo "- \`02_route_related_function_inventory.txt\`"
  echo "- \`03_historical_capture_sites.txt\`"
  echo "- \`04_live_callable_reachability_graph.json\`"
  echo "- \`05_live_callable_reachability_graph.txt\`"
  echo "- \`06_capture_site_live_dead_classification.txt\`"
  echo "- \`07_capture_site_live_dead_classification.json\`"
  echo "- \`08_named_wrapper_helper_source_windows.txt\`"
  echo "- \`09_router_print_surface_inventory.txt\`"
  echo "- \`10_flattening_interpretation.txt\`"
  echo "- \`11_console_digest.txt\`"
  echo
  echo "PHASE37_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE37_OUT=$OUT"
