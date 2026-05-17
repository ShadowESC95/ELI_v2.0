#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase39b_router_prune_eligibility_proof_${STAMP}"
ROUTER="eli/execution/router_enhanced.py"
MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if ! grep -q "$MARKER" "$ROUTER"; then
  echo "Phase 38 marker missing: $MARKER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 39B — Router Prune Eligibility Proof

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Why this exists

Phase 39 correctly identified wrapper/rebinding debt, but its delete-candidate
classifier was too broad. In particular, it marked the large pre-Phase38
route() body as a delete candidate, which is not deletion-safe without a
dependency proof.

Phase 39B separates:

1. the legacy/core route body;
2. late wrapper/rebinding surfaces;
3. pre-marker helpers Phase 38 still depends on;
4. direct and string-based Phase 38 references into pre-marker symbols;
5. the actual runtime relationship between Phase 38 and legacy dispatch symbols.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/00_compile.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

router_path = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

MARKER = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

marker_line = None
for i, line in enumerate(lines, start=1):
    if MARKER in line:
        marker_line = i
        break

if marker_line is None:
    raise SystemExit("Phase 38 marker line not found")

pre_src = "\n".join(lines[: marker_line - 1])
post_src = "\n".join(lines[marker_line - 1 :])

# ---------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------

def node_end(node: ast.AST) -> int:
    return getattr(node, "end_lineno", getattr(node, "lineno", -1))

def slice_lines(start: int, end: int, *, pad: int = 0) -> str:
    lo = max(1, start - pad)
    hi = min(len(lines), end + pad)
    return "\n".join(f"{n:6d}: {lines[n - 1]}" for n in range(lo, hi + 1))

def extract_target_names(target: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(target, ast.Name):
        names.append(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            names.extend(extract_target_names(elt))
    return names

# ---------------------------------------------------------------------
# Pre-marker definition / assignment inventory
# ---------------------------------------------------------------------

pre_defs: dict[str, list[dict[str, Any]]] = defaultdict(list)
route_surface_defs: list[dict[str, Any]] = []

for node in ast.walk(tree):
    lineno = getattr(node, "lineno", None)
    if lineno is None or lineno >= marker_line:
        continue

    if isinstance(node, ast.FunctionDef):
        rec = {
            "kind": "function",
            "name": node.name,
            "start": node.lineno,
            "end": node_end(node),
            "span": node_end(node) - node.lineno + 1,
        }
        pre_defs[node.name].append(rec)

        if node.name in {"route", "route_intent", "route_command", "parse_command", "classify"}:
            route_surface_defs.append(rec)

    elif isinstance(node, ast.ClassDef):
        pre_defs[node.name].append({
            "kind": "class",
            "name": node.name,
            "start": node.lineno,
            "end": node_end(node),
            "span": node_end(node) - node.lineno + 1,
        })

    elif isinstance(node, ast.Assign):
        for target in node.targets:
            for name in extract_target_names(target):
                pre_defs[name].append({
                    "kind": "assign",
                    "name": name,
                    "start": node.lineno,
                    "end": node_end(node),
                    "span": node_end(node) - node.lineno + 1,
                })

    elif isinstance(node, ast.AnnAssign):
        for name in extract_target_names(node.target):
            pre_defs[name].append({
                "kind": "annassign",
                "name": name,
                "start": node.lineno,
                "end": node_end(node),
                "span": node_end(node) - node.lineno + 1,
            })

route_surface_defs.sort(key=lambda r: (r["start"], r["end"]))

route_defs = [r for r in route_surface_defs if r["name"] == "route"]
first_route = route_defs[0] if route_defs else None

# ---------------------------------------------------------------------
# Corrected route-surface classification
# ---------------------------------------------------------------------

classification_lines = [
    "=== PHASE 39B ROUTE-SURFACE PRUNE CLASSIFICATION ===",
    "name | lines | span | corrected_classification",
    "-" * 140,
]

for rec in route_surface_defs:
    name = rec["name"]
    start = rec["start"]
    end = rec["end"]
    span = rec["span"]

    if first_route and rec is first_route:
        cls = "CORE_OR_LEGACY_DISPATCH_BODY__RETAIN_PENDING_DEPENDENCY_PROOF"
    elif name == "route":
        cls = "LATE_ROUTE_WRAPPER__PHASE40_PRUNE_REVIEW"
    elif name == "route_intent":
        cls = "LATE_ROUTE_INTENT_WRAPPER__PHASE40_PRUNE_REVIEW"
    else:
        cls = "LATE_PUBLIC_SURFACE_WRAPPER__PHASE40_PRUNE_REVIEW"

    classification_lines.append(f"{name} | {start}-{end} | {span} | {cls}")

(out / "01_corrected_route_surface_prune_classification.txt").write_text(
    "\n".join(classification_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Phase 38 direct dependency symbols
# ---------------------------------------------------------------------

post_tree = ast.parse(post_src)

name_load_refs: set[str] = set()
for node in ast.walk(post_tree):
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        name_load_refs.add(node.id)

string_global_refs = set(
    re.findall(r'globals\(\)\.get\(\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]', post_src)
)

string_subscript_refs = set(
    re.findall(r'globals\(\)\[\s*[\'"]([A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]', post_src)
)

phase38_all_symbol_refs = sorted(name_load_refs | string_global_refs | string_subscript_refs)

dep_lines = [
    "=== PHASE 38 COMPLETE SYMBOL REFERENCE CAPTURE ===",
    f"Direct ast.Name Load refs: {len(name_load_refs)}",
    f'String globals().get("...") refs: {len(string_global_refs)}',
    f'globals()["..."] refs: {len(string_subscript_refs)}',
    "",
    "ALL_SYMBOL_REFS:",
]
dep_lines.extend(phase38_all_symbol_refs)

(out / "02_phase38_complete_symbol_reference_capture.txt").write_text(
    "\n".join(dep_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Resolve Phase 38 refs against pre-marker definitions/assignments
# ---------------------------------------------------------------------

resolved_pre_marker = []
for name in phase38_all_symbol_refs:
    if name in pre_defs:
        defs = pre_defs[name]
        for rec in defs:
            resolved_pre_marker.append({
                "symbol": name,
                **rec,
            })

resolved_pre_marker.sort(key=lambda r: (r["symbol"], r["start"], r["kind"]))

resolution_lines = [
    "=== PHASE 38 REFERENCES THAT RESOLVE TO PRE-MARKER SYMBOLS ===",
    "symbol | kind | lines | span",
    "-" * 140,
]
for rec in resolved_pre_marker:
    resolution_lines.append(
        f"{rec['symbol']} | {rec['kind']} | {rec['start']}-{rec['end']} | {rec['span']}"
    )

(out / "03_phase38_pre_marker_dependency_resolution.txt").write_text(
    "\n".join(resolution_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Extract specific Phase 38 dispatch helper windows
# ---------------------------------------------------------------------

post_offset = marker_line - 1
post_named_defs: dict[str, dict[str, int]] = {}

for node in ast.walk(post_tree):
    if isinstance(node, ast.FunctionDef):
        absolute_start = post_offset + node.lineno
        absolute_end = post_offset + node_end(node)
        post_named_defs[node.name] = {
            "start": absolute_start,
            "end": absolute_end,
        }

focus_names = [
    "_eli_phase38_bottom_core_dispatch",
    "_eli_phase38_flattened_route",
    "_eli_phase38_voice_portable_persona_lower_dispatch",
]

focus_chunks = []
for name in focus_names:
    rec = post_named_defs.get(name)
    focus_chunks.append("=" * 160)
    focus_chunks.append(name)
    focus_chunks.append("=" * 160)
    if rec is None:
        focus_chunks.append("NOT_FOUND")
    else:
        focus_chunks.append(slice_lines(rec["start"], rec["end"], pad=5))
    focus_chunks.append("")

(out / "04_phase38_focus_dispatch_source_windows.txt").write_text(
    "\n".join(focus_chunks) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Runtime import probe
# ---------------------------------------------------------------------

runtime_stdout = io.StringIO()
runtime_stderr = io.StringIO()

mod = None
import_error = None

with contextlib.redirect_stdout(runtime_stdout), contextlib.redirect_stderr(runtime_stderr):
    try:
        spec = importlib.util.spec_from_file_location("phase39b_router_probe", router_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("importlib could not build router spec")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        import_error = f"{type(exc).__name__}: {exc}"

runtime_lines = [
    "=== PHASE 39B ROUTER RUNTIME IMPORT PROBE ===",
    f"IMPORT_ERROR={import_error!r}",
    "",
    "--- captured stdout ---",
    runtime_stdout.getvalue().rstrip(),
    "",
    "--- captured stderr ---",
    runtime_stderr.getvalue().rstrip(),
    "",
]

if mod is not None:
    surfaces = ["route", "route_intent", "route_command", "parse_command", "classify"]
    objs = {name: getattr(mod, name, None) for name in surfaces}

    runtime_lines.append("--- public surface identity ---")
    base = objs["route"]
    for name in surfaces:
        obj = objs[name]
        if callable(obj):
            runtime_lines.append(
                f"{name}: callable=True same_as_route={obj is base} "
                f"name={getattr(obj, '__name__', None)!r} "
                f"firstlineno={getattr(getattr(obj, '__code__', None), 'co_firstlineno', None)}"
            )
        else:
            runtime_lines.append(f"{name}: callable=False repr={obj!r}")

    runtime_lines.append("")
    runtime_lines.append(f"ALL_PUBLIC_SURFACES_SAME_OBJECT={all(objs[n] is base for n in surfaces)}")

    runtime_lines.append("")
    runtime_lines.append("--- legacy/core symbol runtime state ---")
    for name in [
        "_ROUTE_CORE",
        "_eli_phase38_bottom_core_dispatch",
        "_eli_phase38_flattened_route",
    ]:
        obj = getattr(mod, name, None)
        runtime_lines.append(
            f"{name}: present={obj is not None} callable={callable(obj)} "
            f"name={getattr(obj, '__name__', None)!r} "
            f"firstlineno={getattr(getattr(obj, '__code__', None), 'co_firstlineno', None)}"
        )

    runtime_lines.append("")
    runtime_lines.append("--- code-name references ---")
    for name in [
        "route",
        "_eli_phase38_bottom_core_dispatch",
        "_eli_phase38_flattened_route",
    ]:
        obj = getattr(mod, name, None)
        if callable(obj) and hasattr(obj, "__code__"):
            runtime_lines.append(f"{name}.co_names={list(obj.__code__.co_names)!r}")

(out / "05_runtime_import_and_surface_identity_probe.txt").write_text(
    "\n".join(runtime_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Focused dependency conclusions
# ---------------------------------------------------------------------

phase38_ref_set = set(phase38_all_symbol_refs)
resolved_names = {rec["symbol"] for rec in resolved_pre_marker}

core_route_dependency_signals = []

if "_ROUTE_CORE" in phase38_ref_set:
    core_route_dependency_signals.append("Phase38 directly references _ROUTE_CORE")

if "_ROUTE_CORE" in string_global_refs or "_ROUTE_CORE" in string_subscript_refs:
    core_route_dependency_signals.append("Phase38 string-global lookup references _ROUTE_CORE")

if "route" in resolved_names:
    core_route_dependency_signals.append("Phase38 resolves a pre-marker symbol named route")

if first_route is not None:
    core_route_dependency_signals.append(
        f"Primary pre-Phase38 route body exists at {first_route['start']}-{first_route['end']} "
        f"with span {first_route['span']}"
    )

# This is intentionally conservative.
core_delete_gate = "BLOCKED"
late_wrapper_prune_gate = "READY_FOR_SURGICAL_PLAN"

conclusion = [
    "=== PHASE 39B PRUNE ELIGIBILITY CONCLUSION ===",
    f"PHASE38_MARKER_LINE={marker_line}",
    f"PRIMARY_PRE_PHASE38_ROUTE={first_route}",
    f"PHASE38_SYMBOL_REFS_TOTAL={len(phase38_all_symbol_refs)}",
    f"PHASE38_REFS_RESOLVING_TO_PRE_MARKER_SYMBOLS={len(resolved_pre_marker)}",
    "",
    "CORE_ROUTE_DELETE_GATE=" + core_delete_gate,
    "LATE_WRAPPER_PRUNE_GATE=" + late_wrapper_prune_gate,
    "",
    "Why:",
    "- The primary pre-Phase38 route body is not to be treated as wrapper-only debt.",
    "- Phase 40 must prune only late wrapper/rebinding surfaces unless an explicit later phase migrates/removes the legacy core body.",
    "- Phase 39B intentionally blocks deletion of the large route body regardless of whether Phase 38 shadows it at runtime.",
    "",
    "Core dependency / retention signals:",
]
conclusion.extend(f"- {item}" for item in core_route_dependency_signals)

conclusion.extend([
    "",
    "Required Phase 40 behaviour:",
    "1. Preserve the primary pre-Phase38 route body.",
    "2. Preserve any pre-marker helper symbol resolved in 03_phase38_pre_marker_dependency_resolution.txt.",
    "3. Remove only late route()/route_intent()/route_command()/surface wrapper definitions and stale rebindings proven superseded by Phase 38.",
    "4. Re-run py_compile, Phase 36 v2 baseline, and exact JSON comparison against the Phase 38 semantic baseline.",
])

(out / "06_prune_eligibility_conclusion.txt").write_text(
    "\n".join(conclusion) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------

digest = f"""=== PHASE 39B DIGEST ===
Phase 38 marker line: {marker_line}

Primary pre-Phase38 route body:
- lines {first_route['start']}-{first_route['end']} if first_route else NOT_FOUND
- span {first_route['span']} if first_route else NOT_FOUND

Pre-Phase38 route surface definitions:
- total: {len(route_surface_defs)}
- route(): {sum(1 for r in route_surface_defs if r['name'] == 'route')}
- route_intent(): {sum(1 for r in route_surface_defs if r['name'] == 'route_intent')}
- route_command()/parse_command()/classify(): {sum(1 for r in route_surface_defs if r['name'] in {'route_command', 'parse_command', 'classify'})}

Dependency capture:
- Phase 38 total direct/string symbol refs: {len(phase38_all_symbol_refs)}
- Phase 38 refs resolving to pre-marker symbols: {len(resolved_pre_marker)}

Prune gates:
- CORE_ROUTE_DELETE_GATE={core_delete_gate}
- LATE_WRAPPER_PRUNE_GATE={late_wrapper_prune_gate}

Phase 39B completed.

Review next:
- 01_corrected_route_surface_prune_classification.txt
- 03_phase38_pre_marker_dependency_resolution.txt
- 04_phase38_focus_dispatch_source_windows.txt
- 05_runtime_import_and_surface_identity_probe.txt
- 06_prune_eligibility_conclusion.txt
"""
(out / "07_console_digest.txt").write_text(digest, encoding="utf-8")
print(digest)
PY

cat "$OUT/07_console_digest.txt"

{
  echo
  echo "## Phase 39B artifacts"
  echo "- \`00_compile.txt\`"
  echo "- \`01_corrected_route_surface_prune_classification.txt\`"
  echo "- \`02_phase38_complete_symbol_reference_capture.txt\`"
  echo "- \`03_phase38_pre_marker_dependency_resolution.txt\`"
  echo "- \`04_phase38_focus_dispatch_source_windows.txt\`"
  echo "- \`05_runtime_import_and_surface_identity_probe.txt\`"
  echo "- \`06_prune_eligibility_conclusion.txt\`"
  echo "- \`07_console_digest.txt\`"
  echo
  echo "PHASE39B_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE39B_OUT=$OUT"
