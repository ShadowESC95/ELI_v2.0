#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase34_router_flattening_readiness_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
CONTRACTS="eli/execution/route_contracts.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 34 — Router Flattening Readiness Audit

Generated: $(date -Is)  
Root: $ROOT  
Primary target: $ROUTER  
Contracts target: $CONTRACTS  
Mode: audit only — no source files modified

## Purpose

Phase 33 repaired runtime public-surface drift by rebinding all exported router
surfaces to the final canonical route() object.

Phase 34 now inspects the remaining structural debt:

- duplicate module-level route()/route_intent() definitions;
- wrapper-chain install order;
- symbol rebinding timeline;
- final exported public-surface authority;
- import-time router install print noise;
- route-contract overlap with route_contracts.py;
- external call-site dependence on route_command / parse_command / classify;
- flattening risk classification.

This audit is designed to support one measured structural consolidation pass,
not another incremental hotfix.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  if [[ -f "$CONTRACTS" ]]; then
    python3 -m py_compile "$CONTRACTS"
  fi
  echo "PY_COMPILE_OK"
} | tee "$OUT/00_compile.txt"

python3 - "$OUT" "$ROUTER" "$CONTRACTS" <<'PY'
from __future__ import annotations

import ast
import inspect
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])
router_path = Path(sys.argv[2])
contracts_path = Path(sys.argv[3])

router_text = router_path.read_text(encoding="utf-8")
router_lines = router_text.splitlines()

contracts_text = ""
if contracts_path.exists():
    contracts_text = contracts_path.read_text(encoding="utf-8")

# ----------------------------------------------------------------------
# 1. AST duplicate inventory
# ----------------------------------------------------------------------

tree = ast.parse(router_text)

module_functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
]

module_function_counts = Counter(node.name for node in module_functions)
module_duplicates = sorted(
    name for name, count in module_function_counts.items()
    if count > 1
)

duplicate_lines = []
duplicate_lines.append("=== MODULE-LEVEL FUNCTION DUPLICATE INVENTORY ===")
duplicate_lines.append("Duplicates: " + (", ".join(module_duplicates) if module_duplicates else "none"))
duplicate_lines.append("")

for name in module_duplicates:
    duplicate_lines.append(f"--- {name} ---")
    for node in module_functions:
        if node.name == name:
            end = getattr(node, "end_lineno", node.lineno)
            args = []
            for arg in node.args.args:
                args.append(arg.arg)
            if node.args.vararg:
                args.append("*" + node.args.vararg.arg)
            if node.args.kwarg:
                args.append("**" + node.args.kwarg.arg)
            duplicate_lines.append(
                f"lines={node.lineno}-{end} args={args}"
            )
    duplicate_lines.append("")

(out / "01_module_level_duplicate_inventory.txt").write_text(
    "\n".join(duplicate_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 2. Route-definition timeline
# ----------------------------------------------------------------------

timeline = []
timeline.append("=== ROUTE / ROUTE_INTENT / ALIAS DEFINITION TIMELINE ===")

for idx, line in enumerate(router_lines, 1):
    if re.search(r"^\s*def\s+(route|route_intent|route_command|parse_command|classify)\b", line):
        timeline.append(f"{idx}: {line.strip()}")
    elif re.search(r"^\s*(route|route_intent|route_command|parse_command|classify)\s*=", line):
        timeline.append(f"{idx}: {line.strip()}")
    elif re.search(r"_PREV_ROUTE|_ORIG_ROUTE|_previous_route|_prev_route", line):
        timeline.append(f"{idx}: {line.strip()}")

(out / "02_route_symbol_timeline.txt").write_text(
    "\n".join(timeline) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 3. Wrapper block inventory
# ----------------------------------------------------------------------

wrapper_markers = []
for idx, line in enumerate(router_lines, 1):
    s = line.strip()
    if (
        s.startswith("# ELI ")
        or s.startswith("# --- ELI")
        or s.startswith("# =============================================================================")
        or "wrapper installed" in s.lower()
        or "route contract installed" in s.lower()
        or "contract installed" in s.lower()
        or "Phase 11" in s
        or "PHASE33" in s
    ):
        wrapper_markers.append((idx, s))

wrapper_lines = ["=== ROUTER WRAPPER / CONTRACT MARKER INVENTORY ==="]
for lineno, marker in wrapper_markers:
    wrapper_lines.append(f"{lineno}: {marker}")

(out / "03_wrapper_marker_inventory.txt").write_text(
    "\n".join(wrapper_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 4. Wrapper dependency graph heuristic
# ----------------------------------------------------------------------

capture_pattern = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s*=\s*(?:globals\(\)\.get\(\"route(?:_intent)?\"\)|route(?:_intent)?)"
)

captures = []
for idx, line in enumerate(router_lines, 1):
    m = capture_pattern.search(line)
    if m:
        captures.append((idx, m.group(1), line.strip()))

graph_lines = []
graph_lines.append("=== ROUTER PREVIOUS-SYMBOL CAPTURE INVENTORY ===")
for lineno, symbol, raw in captures:
    graph_lines.append(f"{lineno}: {symbol} <- {raw}")

(out / "04_previous_symbol_capture_inventory.txt").write_text(
    "\n".join(graph_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 5. Import-time print noise
# ----------------------------------------------------------------------

print_hits = []
for idx, line in enumerate(router_lines, 1):
    if "print(" in line or "print (" in line:
        window = "\n".join(
            f"{j}: {router_lines[j-1]}"
            for j in range(max(1, idx - 1), min(len(router_lines), idx + 2) + 1)
        )
        print_hits.append(window)

(out / "05_router_import_print_hits.txt").write_text(
    "=== ROUTER PRINT SURFACES ===\n\n" + "\n\n".join(print_hits) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 6. Runtime public-surface identity and route source lines
# ----------------------------------------------------------------------

import eli.execution.router_enhanced as router

surfaces = ("route", "route_intent", "route_command", "parse_command", "classify")
runtime_lines = []
runtime_lines.append("=== RUNTIME PUBLIC ROUTER SURFACE IDENTITY ===")

canonical = getattr(router, "route", None)
same_identity = True

for name in surfaces:
    fn = getattr(router, name, None)
    same = fn is canonical
    if not same:
        same_identity = False
    runtime_lines.append(
        f"{name}: "
        f"callable={callable(fn)} "
        f"same_as_route={same} "
        f"id={id(fn)} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else '-'}"
    )

runtime_lines.append("")
runtime_lines.append(f"ALL_PUBLIC_SURFACES_CANONICAL={same_identity}")

(out / "06_runtime_public_surface_identity.txt").write_text(
    "\n".join(runtime_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 7. Contract regression matrix, kept compact
# ----------------------------------------------------------------------

PROMPTS = [
    ("runtime_status_full", "Who are you and what are you actually running on right now — model, context size, GPU layers, everything."),
    ("memory_runtime_exact", "Explain exactly how your memory system works internally — which files, which DB tables, which functions."),
    ("personal_memory_summary", "What do you know about me from memory?"),
    ("name_source_audit", "How do you know my name?"),
    ("memory_count", "How many memories do you have?"),
    ("recent_memory_processing", "What memories have you been processing lately?"),
    ("self_report_recent_updates", "What have you been working on recently?"),
    ("gui_actual_scan_proof", "Did you actually scan the GUI file in full?"),
    ("pdf_multi", "analyze /tmp/a.pdf and /tmp/b.pdf"),
    ("followup_continue", "continue"),
    ("play_media_query", "play guilty conscience by eminem on spotify"),
    ("tiny_fragment", "resil"),
]

def summarize(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"kind": type(result).__name__, "repr": repr(result)}
    args = result.get("args") if isinstance(result.get("args"), dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    return {
        "action": result.get("action"),
        "args": {
            k: args[k]
            for k in (
                "question", "message", "query", "path", "paths",
                "memory_scope", "profile_scope", "identity_scope",
                "self_report_scope", "proof_requested", "audit_depth",
            )
            if k in args
        },
        "meta": {
            k: meta[k]
            for k in (
                "matched_by", "task_family", "need_grounding",
                "grounded_required", "allow_chat_without_evidence",
                "response_contract", "forbid_chat_fallback",
                "multipdf_count",
            )
            if k in meta
        },
    }

contract_lines = []
contract_lines.append("=== COMPACT ROUTER CONTRACT BASELINE ===")

contract_json = []

for pid, prompt in PROMPTS:
    result = router.route(prompt)
    summary = summarize(result)
    contract_json.append({
        "id": pid,
        "prompt": prompt,
        "summary": summary,
    })
    contract_lines.append(
        f"{pid} | "
        f"action={summary.get('action')} | "
        f"args={json.dumps(summary.get('args', {}), ensure_ascii=False, sort_keys=True)} | "
        f"meta={json.dumps(summary.get('meta', {}), ensure_ascii=False, sort_keys=True)}"
    )

(out / "07_compact_contract_baseline.txt").write_text(
    "\n".join(contract_lines) + "\n",
    encoding="utf-8",
)

(out / "08_compact_contract_baseline.json").write_text(
    json.dumps(contract_json, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 8. External references to public surfaces
# ----------------------------------------------------------------------

search_root = Path("eli")
reference_hits: dict[str, list[str]] = defaultdict(list)

for path in search_root.rglob("*.py"):
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        continue

    if path == router_path:
        continue

    for idx, line in enumerate(txt.splitlines(), 1):
        if any(
            re.search(rf"\b{name}\b", line)
            for name in ("route_command", "parse_command", "classify", "route_intent")
        ):
            reference_hits[str(path)].append(f"{idx}: {line.rstrip()}")

ref_lines = []
ref_lines.append("=== EXTERNAL REFERENCES TO ROUTER PUBLIC SURFACES ===")
if not reference_hits:
    ref_lines.append("none")
else:
    for path, hits in sorted(reference_hits.items()):
        ref_lines.append("")
        ref_lines.append(f"--- {path} ---")
        ref_lines.extend(hits)

(out / "09_external_public_surface_reference_hits.txt").write_text(
    "\n".join(ref_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 9. route_contracts overlap review
# ----------------------------------------------------------------------

overlap_terms = [
    "classify_precedence_route",
    "PERSONAL_MEMORY",
    "EXPLAIN_MEMORY_RUNTIME",
    "NAME_SOURCE_AUDIT",
    "RUNTIME_STATUS",
    "MEMORY_STATUS",
    "GUI_RUNTIME_AUDIT",
]

overlap_lines = []
overlap_lines.append("=== ROUTE_CONTRACTS OVERLAP REVIEW ===")

for term in overlap_terms:
    overlap_lines.append("")
    overlap_lines.append(f"--- TERM: {term} ---")
    found = False
    for idx, line in enumerate(contracts_text.splitlines(), 1):
        if term in line:
            found = True
            overlap_lines.append(f"{idx}: {line.rstrip()}")
    if not found:
        overlap_lines.append("(no hits)")

(out / "10_route_contracts_overlap_review.txt").write_text(
    "\n".join(overlap_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 10. Structural risk interpretation
# ----------------------------------------------------------------------

risk_lines = []
risk_lines.append("=== ROUTER STRUCTURAL RISK INTERPRETATION ===")
risk_lines.append("")
risk_lines.append("Confirmed stable after Phase 33:")
risk_lines.append(f"- public routing surfaces canonical: {same_identity}")
risk_lines.append("- Phase 32 semantic drift repaired")
risk_lines.append("- multi-PDF final enrichment is idempotent")
risk_lines.append("")
risk_lines.append("Remaining structural debt:")
risk_lines.append(f"- duplicate module-level functions: {', '.join(module_duplicates) if module_duplicates else 'none'}")
risk_lines.append(f"- previous-symbol capture sites: {len(captures)}")
risk_lines.append(f"- wrapper/contract marker sites: {len(wrapper_markers)}")
risk_lines.append(f"- router print() surfaces: {len(print_hits)}")
risk_lines.append("")
risk_lines.append("Flattening strategy indicated by this audit:")
risk_lines.append("1. Preserve the current primary route() body as the base classifier.")
risk_lines.append("2. Extract genuinely necessary late wrapper behaviour into named helper functions.")
risk_lines.append("3. Apply those helpers in one deterministic post-primary route pipeline.")
risk_lines.append("4. Retain route_contracts.py only for precedence contracts that are intentionally externalised.")
risk_lines.append("5. Remove historical wrapper redefinitions after regression parity is proven against this audit baseline.")
risk_lines.append("6. Retain exported aliases, but bind them once at the end to the canonical route() function.")
risk_lines.append("")
risk_lines.append("Do not attempt mechanical deletion of duplicate def route() blocks without semantic migration.")

(out / "11_structural_risk_interpretation.txt").write_text(
    "\n".join(risk_lines) + "\n",
    encoding="utf-8",
)

# ----------------------------------------------------------------------
# 11. Console digest
# ----------------------------------------------------------------------

digest = []
digest.append("=== PHASE 34 DIGEST ===")
digest.append(f"Module-level duplicate functions: {', '.join(module_duplicates) if module_duplicates else 'none'}")
digest.append(f"Previous-symbol capture sites: {len(captures)}")
digest.append(f"Wrapper/contract marker sites: {len(wrapper_markers)}")
digest.append(f"Router print() surfaces: {len(print_hits)}")
digest.append(f"Public surfaces remain canonical: {same_identity}")
digest.append("")
digest.append("Review next:")
digest.append("- 01_module_level_duplicate_inventory.txt")
digest.append("- 02_route_symbol_timeline.txt")
digest.append("- 04_previous_symbol_capture_inventory.txt")
digest.append("- 09_external_public_surface_reference_hits.txt")
digest.append("- 10_route_contracts_overlap_review.txt")
digest.append("- 11_structural_risk_interpretation.txt")

(out / "12_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
PY

{
  echo
  echo "## Files produced"
  for f in "$OUT"/*; do
    printf -- '- `%s`\n' "$(basename "$f")"
  done
  echo
  echo "PHASE34_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE34_OUT=$OUT"
