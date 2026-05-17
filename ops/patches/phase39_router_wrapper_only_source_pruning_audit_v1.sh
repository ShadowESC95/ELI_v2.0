#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase39_router_wrapper_only_source_pruning_audit_${STAMP}"
ROUTER="eli/execution/router_enhanced.py"
MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if ! grep -q "$MARKER" "$ROUTER"; then
  echo "Phase 38 canonical flattened dispatcher marker not found. Refusing Phase 39 prune audit." >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 39 — Router Wrapper-Only Source Pruning Audit v1

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase 38 proved that the flattened canonical public router surface preserves
the full Phase 36 semantic baseline exactly.

Phase 39 now audits the historical wrapper/rebinding blocks that remain in
source but are no longer the final active public router.

This audit distinguishes:

- DELETE CANDIDATES:
  route()/route_intent() wrapper definitions, public-surface rebinding lines,
  install-print statements, and stale wrapper capture variables.

- RETAIN REQUIRED:
  helper functions, predicates, normalisers, enrichment functions, and result
  constructors still referenced by the Phase 38 flattened dispatch pipeline.

No code is modified in this phase.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/00_compile.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from collections import defaultdict

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

# ---------------------------------------------------------------------
# Phase 38 dependency roots: helper/global names still required
# ---------------------------------------------------------------------

phase38_start = None
for i, line in enumerate(lines, start=1):
    if "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1" in line:
        phase38_start = i
        break

if phase38_start is None:
    raise SystemExit("Phase 38 marker not found")

phase38_src = "\n".join(lines[phase38_start - 1 :])
phase38_tree = ast.parse(phase38_src)

phase38_global_refs: set[str] = set()
for node in ast.walk(phase38_tree):
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        phase38_global_refs.add(node.id)

required_historical_helpers = sorted(
    name for name in phase38_global_refs
    if name.startswith("_eli_")
    or name in {
        "_ROUTE_CORE",
        "_mk",
    }
)

(out / "01_phase38_required_historical_symbol_refs.txt").write_text(
    "=== PHASE 38 REQUIRED HISTORICAL SYMBOL REFERENCES ===\n"
    + "\n".join(required_historical_helpers)
    + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Function inventory prior to Phase 38 marker
# ---------------------------------------------------------------------

functions = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if getattr(node, "lineno", 10**9) < phase38_start:
            functions.append(
                {
                    "name": node.name,
                    "start": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno),
                    "args": [a.arg for a in node.args.args],
                }
            )

functions.sort(key=lambda x: x["start"])

wrapper_name_targets = {
    "route",
    "route_intent",
    "route_command",
    "parse_command",
    "classify",
}

wrapper_defs = [f for f in functions if f["name"] in wrapper_name_targets]
helper_defs = [f for f in functions if f["name"] not in wrapper_name_targets]

# ---------------------------------------------------------------------
# Wrapper definition classification
# ---------------------------------------------------------------------

wrapper_report = []
wrapper_report.append("=== PRE-PHASE38 ROUTER WRAPPER DEFINITION INVENTORY ===")
wrapper_report.append("name | lines | classification | notes")
wrapper_report.append("-" * 150)

for f in wrapper_defs:
    body = "\n".join(lines[f["start"] - 1 : f["end"]])
    if f["name"] in {"route", "route_intent"}:
        classification = "DELETE_CANDIDATE_WRAPPER"
    else:
        classification = "DELETE_CANDIDATE_PUBLIC_SURFACE_WRAPPER"
    notes = []
    if "_prev" in body or "_ORIG_ROUTE" in body or "_PREV_ROUTE" in body:
        notes.append("previous-route chaining")
    if "return route(" in body:
        notes.append("route forwarding")
    if "ANALYZE_PDF" in body and "paths" in body:
        notes.append("PDF enrichment wrapper")
    if not notes:
        notes.append("wrapper/rebinding surface")

    wrapper_report.append(
        f"{f['name']} | {f['start']}-{f['end']} | {classification} | {', '.join(notes)}"
    )

(out / "02_wrapper_definition_delete_candidate_inventory.txt").write_text(
    "\n".join(wrapper_report) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Helper retain/prune classification
# ---------------------------------------------------------------------

helper_report = []
helper_report.append("=== PRE-PHASE38 HELPER FUNCTION RETENTION CLASSIFICATION ===")
helper_report.append("name | lines | classification")
helper_report.append("-" * 120)

required_set = set(required_historical_helpers)

for f in helper_defs:
    cls = "RETAIN_PHASE38_DEPENDENCY" if f["name"] in required_set else "REVIEW_NOT_DIRECTLY_REFERENCED_BY_PHASE38"
    helper_report.append(f"{f['name']} | {f['start']}-{f['end']} | {cls}")

(out / "03_helper_function_retain_review_inventory.txt").write_text(
    "\n".join(helper_report) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Historical assignment / capture / print surfaces to inspect
# ---------------------------------------------------------------------

assign_patterns = [
    re.compile(r"^\s*_[A-Za-z0-9_]*(?:ORIG|PREV|CORE|ROUTE)[A-Za-z0-9_]*\s*="),
    re.compile(r"^\s*(route|route_intent|route_command|parse_command|classify)\s*="),
]

candidate_assignments = []
install_prints = []

for lineno, line in enumerate(lines[: phase38_start - 1], start=1):
    if any(p.search(line) for p in assign_patterns):
        candidate_assignments.append(f"{lineno}: {line}")
    if "[ROUTER]" in line and "installed" in line:
        install_prints.append(f"{lineno}: {line}")

(out / "04_assignment_and_capture_delete_review_hits.txt").write_text(
    "=== ASSIGNMENT / CAPTURE / PUBLIC REBINDING REVIEW HITS ===\n"
    + "\n".join(candidate_assignments)
    + "\n",
    encoding="utf-8",
)

(out / "05_install_print_delete_review_hits.txt").write_text(
    "=== IMPORT-TIME ROUTER INSTALL PRINT REVIEW HITS ===\n"
    + "\n".join(install_prints)
    + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Exact source windows around candidate wrapper defs
# ---------------------------------------------------------------------

windows = []
for f in wrapper_defs:
    lo = max(1, f["start"] - 6)
    hi = min(len(lines), f["end"] + 6)
    windows.append("=" * 140)
    windows.append(f"{f['name']} | candidate lines {f['start']}-{f['end']} | context {lo}-{hi}")
    windows.append("=" * 140)
    for n in range(lo, hi + 1):
        windows.append(f"{n:6d}: {lines[n - 1]}")
    windows.append("")

(out / "06_wrapper_candidate_source_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Phase 39 interpretation
# ---------------------------------------------------------------------

delete_route_count = sum(1 for f in wrapper_defs if f["name"] == "route")
delete_route_intent_count = sum(1 for f in wrapper_defs if f["name"] == "route_intent")
delete_public_other_count = sum(1 for f in wrapper_defs if f["name"] in {"route_command", "parse_command", "classify"})
retain_helpers_count = sum(1 for f in helper_defs if f["name"] in required_set)

interpretation = f"""=== PHASE 39 WRAPPER-ONLY PRUNING INTERPRETATION ===

Phase 38 marker line:
- {phase38_start}

Wrapper definitions before Phase 38:
- route(): {delete_route_count}
- route_intent(): {delete_route_intent_count}
- route_command()/parse_command()/classify() function defs: {delete_public_other_count}

Phase 38-required historical helper symbols:
- {len(required_historical_helpers)}

Pre-Phase38 helper function definitions directly required by Phase 38:
- {retain_helpers_count}

Safe conclusion:
1. The old route()/route_intent() wrapper definitions are structurally obsolete
   as public dispatch surfaces because Phase 38 is now the final authoritative
   flattened route.
2. They are not all delete-safe by contiguous block deletion, because several
   historical sections co-locate required helper functions and obsolete wrapper
   definitions.
3. Phase 40 should perform a surgical prune:
   - remove wrapper defs and public rebinding assignments;
   - remove stale capture variables used only by those wrappers;
   - remove import-time "[ROUTER] ... installed" print lines tied to deleted wrappers;
   - retain helper predicates/functions still referenced by Phase 38.
4. After pruning, rerun:
   - py_compile;
   - Phase 36 v2 semantic baseline;
   - exact JSON comparison against the Phase 38 post-patch baseline.
"""
(out / "07_pruning_interpretation.txt").write_text(interpretation, encoding="utf-8")

# ---------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------

digest = f"""=== PHASE 39 DIGEST ===
Phase 38 marker line: {phase38_start}
Wrapper route() definitions identified: {delete_route_count}
Wrapper route_intent() definitions identified: {delete_route_intent_count}
Other public wrapper function defs identified: {delete_public_other_count}
Phase 38 required historical helper symbol refs: {len(required_historical_helpers)}
Helper defs directly retained for Phase 38: {retain_helpers_count}

Phase 39 complete. This is the deletion map required before physical wrapper-source pruning.

Review next:
- 01_phase38_required_historical_symbol_refs.txt
- 02_wrapper_definition_delete_candidate_inventory.txt
- 03_helper_function_retain_review_inventory.txt
- 06_wrapper_candidate_source_windows.txt
- 07_pruning_interpretation.txt
"""
(out / "08_console_digest.txt").write_text(digest, encoding="utf-8")
print(digest)
PY

cat "$OUT/08_console_digest.txt"

{
  echo
  echo "## Phase 39 artifacts"
  echo "- \`00_compile.txt\`"
  echo "- \`01_phase38_required_historical_symbol_refs.txt\`"
  echo "- \`02_wrapper_definition_delete_candidate_inventory.txt\`"
  echo "- \`03_helper_function_retain_review_inventory.txt\`"
  echo "- \`04_assignment_and_capture_delete_review_hits.txt\`"
  echo "- \`05_install_print_delete_review_hits.txt\`"
  echo "- \`06_wrapper_candidate_source_windows.txt\`"
  echo "- \`07_pruning_interpretation.txt\`"
  echo "- \`08_console_digest.txt\`"
  echo
  echo "PHASE39_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE39_OUT=$OUT"
