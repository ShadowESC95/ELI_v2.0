#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase36_router_flattening_semantic_baseline_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
CONTRACTS="eli/execution/route_contracts.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 36 — Router Flattening Semantic Baseline

Generated: $(date -Is)  
Root: $ROOT  
Router: $ROUTER

## Purpose

Phase 35 removed the duplicate public top-level \`route\` / \`route_intent\`
definitions while preserving live behaviour.

The remaining structural debt is the historical stacked late-wrapper chain.
Before flattening that chain, this phase records a behaviour-preservation baseline:

1. Ordered inventory of late wrapper / symbol-capture surfaces
2. Classification of wrappers by semantic role
3. Public routing surface identity confirmation
4. Broad route behaviour regression matrix
5. Machine-readable JSON baseline for post-flattening equivalence checks

This is an audit-only phase. No source files are modified.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  [[ -f "$CONTRACTS" ]] && python3 -m py_compile "$CONTRACTS"
  echo "PY_COMPILE_OK"
} | tee "$OUT/00_py_compile.txt"

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
tree = ast.parse(src)

# ------------------------------------------------------------------
# 1. Previous-symbol capture timeline
# ------------------------------------------------------------------

capture_patterns = [
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*route\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*route_intent\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*route_command\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*globals\(\)\.get\("route"\)\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*globals\(\)\.get\("route_intent"\)\s*(?:#.*)?$'),
    re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*globals\(\)\.get\("route_command"\)\s*(?:#.*)?$'),
]

capture_lines: list[str] = ["=== ROUTER PREVIOUS-SYMBOL CAPTURE TIMELINE ==="]
captures: list[tuple[int, str]] = []

for lineno, line in enumerate(src.splitlines(), start=1):
    for pat in capture_patterns:
        m = pat.match(line)
        if m:
            captures.append((lineno, line.strip()))
            capture_lines.append(f"{lineno}: {line.strip()}")
            break

capture_lines.append("")
capture_lines.append(f"TOTAL_CAPTURE_SITES={len(captures)}")

(out / "01_previous_symbol_capture_timeline.txt").write_text(
    "\n".join(capture_lines) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------------
# 2. Wrapper/helper semantic-role inventory
# ------------------------------------------------------------------

function_nodes = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
]

role_rows: list[str] = [
    "=== LATE ROUTER HELPER / WRAPPER SEMANTIC ROLE INVENTORY ===",
    "name | lines | role_guess | evidence",
    "-" * 180,
]

role_counts: dict[str, int] = defaultdict(int)

def node_text(node: ast.FunctionDef) -> str:
    lines = src.splitlines()
    return "\n".join(lines[node.lineno - 1:getattr(node, "end_lineno", node.lineno)])

def classify_role(name: str, body: str) -> tuple[str, str]:
    low_name = name.lower()
    low_body = body.lower()

    if name in {"route", "route_intent"}:
        return "public-core", "module-level canonical/public core function"

    if "enrich_pdf_route" in low_name or "multipdf" in low_body:
        return "post-route-mutator", "multi-PDF enrichment / output mutation"

    if "query_clean" in low_name:
        return "post-route-mutator", "PLAY_MEDIA query cleanup"

    if "compat" in low_name and "summary" in low_name:
        return "post-route-mutator", "metadata hygiene / compatibility mutation"

    if "scope" in low_name and "route" in low_name:
        return "post-route-mutator", "route result scope enrichment"

    if "route_lock" in low_name or "strict" in low_name:
        return "pre-route-guard", "high-priority lock / interception before prior route"

    if "guard" in low_name or "phrase" in low_name:
        return "pre-route-guard", "high-priority deterministic phrase guard"

    if "contract" in low_name and "result" not in low_name:
        return "pre-route-guard", "contract-style route interception"

    if "precedence" in low_name:
        return "pre-route-guard", "precedence contract before prior route"

    if "route" in low_name:
        return "wrapper-or-route-helper", "route-related helper requiring manual flattening review"

    return "non-wrapper-helper", "non-route helper"

for node in function_nodes:
    if node.lineno < 2770:
        continue

    body = node_text(node)
    role, evidence = classify_role(node.name, body)
    role_counts[role] += 1
    role_rows.append(
        f"{node.name} | {node.lineno}-{getattr(node, 'end_lineno', node.lineno)} | {role} | {evidence}"
    )

role_rows.append("")
role_rows.append("=== ROLE COUNTS ===")
for role in sorted(role_counts):
    role_rows.append(f"{role}={role_counts[role]}")

(out / "02_late_wrapper_semantic_role_inventory.txt").write_text(
    "\n".join(role_rows) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------------
# 3. Print surfaces inventory
# ------------------------------------------------------------------

print_hits = []
for lineno, line in enumerate(src.splitlines(), start=1):
    if "print(" in line:
        print_hits.append(f"{lineno}: {line.rstrip()}")

(out / "03_router_print_surface_inventory.txt").write_text(
    "=== ROUTER PRINT() SURFACE INVENTORY ===\n"
    + ("\n".join(print_hits) if print_hits else "(none)")
    + f"\n\nTOTAL_PRINT_SURFACES={len(print_hits)}\n",
    encoding="utf-8",
)
PY

python3 - "$OUT" <<'PY'
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

surfaces = ("route", "route_intent", "route_command", "parse_command", "classify")
canonical = router.route

# ------------------------------------------------------------------
# 4. Public surface identity probe
# ------------------------------------------------------------------

identity_lines = [
    "=== PUBLIC ROUTER SURFACE IDENTITY BASELINE ==="
]

all_same = True
for name in surfaces:
    fn = getattr(router, name, None)
    same = fn is canonical
    all_same = all_same and same
    identity_lines.append(
        f"{name}: "
        f"callable={callable(fn)} "
        f"same_as_route={same} "
        f"id={id(fn)} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else '-'}"
    )

identity_lines.append("")
identity_lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "04_public_surface_identity_baseline.txt").write_text(
    "\n".join(identity_lines) + "\n",
    encoding="utf-8",
)

if not all_same:
    raise RuntimeError("Public routing surfaces are not canonical before flattening")

# ------------------------------------------------------------------
# 5. Behavioural regression case set
# ------------------------------------------------------------------

CASES: dict[str, str] = {
    # Runtime / audit contracts
    "runtime_status_full": "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
    "name_source_audit": "How do you know my name?",
    "gui_actual_scan_proof": "Did you actually scan the GUI file in full?",
    "self_report_recent_updates": "What have you been working on recently?",
    "runtime_latency_explain": "Why did you take so long to answer that?",
    "inference_runtime_explain": "What are the current inference issues with context overflow and GPU layers?",

    # Memory contracts
    "memory_runtime_exact": "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    "personal_memory_summary": "What do you know about me from memory?",
    "personal_memory_hybrid": "Explain what your memory system knows about me internally.",
    "memory_count": "How many memories do you have?",
    "recent_memory_processing": "What memories have you been processing lately?",
    "identity_name_only": "What is my name?",
    "identity_who_am_i": "Who am I?",

    # Follow-up / persona / tiny fragment
    "short_followup_continue": "continue",
    "short_followup_elaborate": "elaborate",
    "story_status": "what's the story",
    "tiny_fragment": "resil",

    # Voice / typo / media wrappers
    "open_spotify_typo": "open potify",
    "play_media_query": "play guilty conscience by eminem on spotify",
    "pause_netflix": "pause netflix",
    "volume_up": "volume up",

    # PDF enrichment
    "pdf_single": "analyze /tmp/a.pdf",
    "pdf_multi": "analyze /tmp/a.pdf and /tmp/b.pdf",

    # Existing generic base classifier safeguards
    "screenshot_exact": "screenshot",
    "write_note_colon": "write note: buy milk",
    "time": "what time is it",
    "date": "what is the date",
    "open_browser": "open browser",
    "search_memory": "search your memory for recent project changes",
}

def compact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in ("action", "args", "confidence", "meta", "source", "reason", "query"):
            if key in value:
                out[key] = compact(value[key])
        return out
    if isinstance(value, list):
        return [compact(x) for x in value]
    return value

def route_one(surface_name: str, prompt: str) -> dict[str, Any]:
    fn = getattr(router, surface_name)
    try:
        result = fn(prompt)
        return {
            "ok": True,
            "result": compact(result),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

matrix: dict[str, dict[str, Any]] = {}
mismatches: list[str] = []
errors: list[str] = []

for case_id, prompt in CASES.items():
    matrix[case_id] = {
        "prompt": prompt,
        "surfaces": {},
    }

    reference = route_one("route", prompt)
    matrix[case_id]["surfaces"]["route"] = reference

    for surface in surfaces[1:]:
        got = route_one(surface, prompt)
        matrix[case_id]["surfaces"][surface] = got

        if not got.get("ok", False):
            errors.append(f"{case_id}:{surface}:{got.get('error_type')}:{got.get('error')}")
        elif got != reference:
            mismatches.append(f"{case_id}:{surface}")

(out / "05_router_flattening_semantic_baseline.json").write_text(
    json.dumps(
        {
            "cases": matrix,
            "mismatches": mismatches,
            "errors": errors,
            "totals": {
                "case_count": len(CASES),
                "surface_count": len(surfaces),
                "mismatch_count": len(mismatches),
                "error_count": len(errors),
            },
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ),
    encoding="utf-8",
)

# ------------------------------------------------------------------
# 6. Human-readable contract matrix
# ------------------------------------------------------------------

def summarize_result(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return f"ERROR {payload.get('error_type')}: {payload.get('error')}"

    result = payload.get("result") or {}
    action = result.get("action")
    args = result.get("args") if isinstance(result.get("args"), dict) else {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}

    key_args = {}
    for key in (
        "question",
        "memory_scope",
        "self_report_scope",
        "profile_scope",
        "identity_scope",
        "proof_requested",
        "audit_depth",
        "paths",
        "path",
        "query",
        "name",
    ):
        if key in args:
            key_args[key] = args[key]

    key_meta = {}
    for key in (
        "matched_by",
        "task_family",
        "response_contract",
        "allow_chat_without_evidence",
        "need_grounding",
        "grounded_required",
        "forbid_chat_fallback",
        "multipdf_count",
    ):
        if key in meta:
            key_meta[key] = meta[key]

    return json.dumps(
        {
            "action": action,
            "args": key_args,
            "meta": key_meta,
        },
        ensure_ascii=False,
        sort_keys=True,
    )

matrix_lines = [
    "=== ROUTER FLATTENING SEMANTIC BASELINE MATRIX ===",
    f"case_count={len(CASES)}",
    f"surface_mismatches={len(mismatches)}",
    f"surface_errors={len(errors)}",
    "",
]

for case_id, prompt in CASES.items():
    matrix_lines.append("=" * 120)
    matrix_lines.append(f"{case_id}: {prompt}")
    matrix_lines.append("=" * 120)

    route_summary = summarize_result(matrix[case_id]["surfaces"]["route"])
    matrix_lines.append(f"route: {route_summary}")

    for surface in surfaces[1:]:
        summary = summarize_result(matrix[case_id]["surfaces"][surface])
        verdict = "MATCH" if matrix[case_id]["surfaces"][surface] == matrix[case_id]["surfaces"]["route"] else "MISMATCH"
        matrix_lines.append(f"{surface}: {verdict} {summary}")

    matrix_lines.append("")

matrix_lines.append("=" * 120)
matrix_lines.append(f"TOTAL_SURFACE_MISMATCHES={len(mismatches)}")
matrix_lines.append(f"TOTAL_SURFACE_ERRORS={len(errors)}")
matrix_lines.append("=" * 120)

(out / "06_router_flattening_semantic_baseline_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

if mismatches or errors:
    raise RuntimeError(
        f"Baseline public-surface drift detected before flattening: mismatches={len(mismatches)} errors={len(errors)}"
    )

# ------------------------------------------------------------------
# 7. Targeted baseline assertions
# ------------------------------------------------------------------

def route_result(case: str) -> dict[str, Any]:
    return matrix[case]["surfaces"]["route"]["result"]

assertions: list[str] = []
failures: list[str] = []

def check(label: str, condition: bool, detail: str) -> None:
    if condition:
        assertions.append(f"PASS: {label} — {detail}")
    else:
        failures.append(f"FAIL: {label} — {detail}")

check(
    "memory count grounded synthesis baseline",
    route_result("memory_count").get("action") == "MEMORY_STATUS"
    and route_result("memory_count").get("args", {}).get("memory_scope") == "count_only",
    json.dumps(route_result("memory_count"), ensure_ascii=False, sort_keys=True),
)

check(
    "recent memory processing grounding baseline",
    route_result("recent_memory_processing").get("action") == "MEMORY_STATUS"
    and route_result("recent_memory_processing").get("args", {}).get("memory_scope") == "recent_processing",
    json.dumps(route_result("recent_memory_processing"), ensure_ascii=False, sort_keys=True),
)

check(
    "memory runtime strict lock baseline",
    route_result("memory_runtime_exact").get("action") == "EXPLAIN_MEMORY_RUNTIME"
    and route_result("memory_runtime_exact").get("meta", {}).get("matched_by") == "eli.memory_runtime_route_lock_v1",
    json.dumps(route_result("memory_runtime_exact"), ensure_ascii=False, sort_keys=True),
)

check(
    "GUI scan-proof route baseline",
    route_result("gui_actual_scan_proof").get("action") == "GUI_RUNTIME_AUDIT"
    and route_result("gui_actual_scan_proof").get("args", {}).get("proof_requested") is True,
    json.dumps(route_result("gui_actual_scan_proof"), ensure_ascii=False, sort_keys=True),
)

check(
    "multi-PDF baseline",
    route_result("pdf_multi").get("action") == "ANALYZE_PDF"
    and route_result("pdf_multi").get("args", {}).get("paths") == ["/tmp/a.pdf", "/tmp/b.pdf"],
    json.dumps(route_result("pdf_multi"), ensure_ascii=False, sort_keys=True),
)

assertion_lines = [
    "=== PHASE 36 TARGETED BASELINE ASSERTIONS ===",
    *assertions,
    *failures,
    "",
    f"TOTAL_ASSERTION_FAILURES={len(failures)}",
]

(out / "07_targeted_baseline_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

if failures:
    raise RuntimeError("Phase 36 targeted baseline assertions failed:\n" + "\n".join(failures))
PY

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

baseline = json.loads((out / "05_router_flattening_semantic_baseline.json").read_text(encoding="utf-8"))
totals = baseline["totals"]

digest = [
    "=== PHASE 36 DIGEST ===",
    f"Semantic baseline cases recorded: {totals['case_count']}",
    f"Public routing surfaces compared per case: {totals['surface_count']}",
    f"Public surface mismatches: {totals['mismatch_count']}",
    f"Public surface errors: {totals['error_count']}",
    "",
    "Flattening baseline is now safe to use as the golden comparator for the real consolidation patch.",
    "",
    "Review next:",
    "- 01_previous_symbol_capture_timeline.txt",
    "- 02_late_wrapper_semantic_role_inventory.txt",
    "- 05_router_flattening_semantic_baseline.json",
    "- 06_router_flattening_semantic_baseline_matrix.txt",
    "- 07_targeted_baseline_assertions.txt",
]

(out / "08_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
PY

{
  echo
  echo "## Verification artifacts"
  echo "- \`00_py_compile.txt\`"
  echo "- \`01_previous_symbol_capture_timeline.txt\`"
  echo "- \`02_late_wrapper_semantic_role_inventory.txt\`"
  echo "- \`03_router_print_surface_inventory.txt\`"
  echo "- \`04_public_surface_identity_baseline.txt\`"
  echo "- \`05_router_flattening_semantic_baseline.json\`"
  echo "- \`06_router_flattening_semantic_baseline_matrix.txt\`"
  echo "- \`07_targeted_baseline_assertions.txt\`"
  echo "- \`08_console_digest.txt\`"
  echo
  echo "PHASE36_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE36_OUT=$OUT"
