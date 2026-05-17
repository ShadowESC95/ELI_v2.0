#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase44_router_cascading_dead_shell_cluster_prune_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE43_SCRIPT="ops/patches/phase43_router_residual_shell_liveness_split_eligibility_audit_v1.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT/backups"

for f in "$ROUTER" "$PHASE36_SCRIPT"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Missing Phase 38 marker: $PHASE38_MARKER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase44.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 44 — Router Cascading Dead-Shell Cluster Prune

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase 43 proved:

- 9 residual shell statements are pure dead shell / rebinding residue.
- 6 earlier capture assignments feed only those dead shells.
- Once the shell statements are removed, those 6 capture assignments become dead too.

Phase 44 removes that entire 15-statement cascading dead cluster, while preserving:

- Phase 38 flattened canonical dispatch;
- all Phase 36 semantic baseline behaviour;
- all public router-surface parity;
- all still-live mixed helper blocks reserved for later split-preserve cleanup.
EOF

echo "=== PRE-PATCH PY_COMPILE ===" | tee "$OUT/00_pre_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_pre_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_pre_compile.txt"

echo "=== PRE-PATCH PHASE 36 BASELINE ===" | tee "$OUT/01_pre_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/01_pre_phase36_console.txt"

PRE_PHASE36_OUT="$(
  grep -oE 'PHASE36_V2_OUT=.*' "$OUT/01_pre_phase36_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PRE_PHASE36_OUT:-}" || ! -d "$PRE_PHASE36_OUT" ]]; then
  echo "Could not resolve PRE_PHASE36_OUT" >&2
  exit 1
fi

PRE_JSON="$PRE_PHASE36_OUT/05_router_flattening_semantic_baseline.json"

if [[ ! -f "$PRE_JSON" ]]; then
  echo "Missing pre-patch Phase 36 semantic JSON: $PRE_JSON" >&2
  exit 1
fi

cp "$PRE_JSON" "$OUT/02_pre_phase36_semantic_baseline.json"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()

DELETE_CAPTURE_ASSIGN_NAMES = {
    "_ELI_OPEN_TYPO_ORIG_ROUTE",
    "_ELI_MQC_ORIG_ROUTE",
    "_ELI_ID_ORIG_ROUTE",
    "_ELI_TINY_ORIG_ROUTE",
    "_ELI_FOLLOWUP_ORIG_ROUTE",
    "_ELI_PR_ORIG_ROUTE",
}

DELETE_TRY_CAPTURE_NAMES = {
    "_ELI_FINAL_RUNTIME_STATUS_ROUTE_PREV",
    "_ELI_FINAL_MEMORY_ROUTE_PREV",
    "_ELI_PERSONAL_MEMORY_SUMMARY_COMPAT_PREV",
}

EARLY_ALIAS_TARGETS = {
    "route_command",
    "parse_command",
    "classify",
}

def line_span(node: ast.AST) -> tuple[int, int]:
    return (
        getattr(node, "lineno", -1),
        getattr(node, "end_lineno", getattr(node, "lineno", -1)),
    )

def source_window(start: int, end: int) -> str:
    return "\n".join(lines[start - 1:end])

def target_names(target: ast.AST) -> set[str]:
    found: set[str] = set()
    if isinstance(target, ast.Name):
        found.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            found |= target_names(elt)
    return found

def module_scope_bindings(node: ast.AST) -> set[str]:
    found: set[str] = set()

    if isinstance(node, ast.FunctionDef):
        found.add(node.name)
        return found

    if isinstance(node, ast.AsyncFunctionDef):
        found.add(node.name)
        return found

    if isinstance(node, ast.ClassDef):
        found.add(node.name)
        return found

    if isinstance(node, ast.Assign):
        for target in node.targets:
            found |= target_names(target)
        return found

    if isinstance(node, ast.AnnAssign):
        found |= target_names(node.target)
        return found

    if isinstance(node, ast.AugAssign):
        found |= target_names(node.target)
        return found

    if isinstance(node, ast.If):
        for stmt in node.body:
            found |= module_scope_bindings(stmt)
        for stmt in node.orelse:
            found |= module_scope_bindings(stmt)
        return found

    if isinstance(node, ast.Try):
        for stmt in node.body:
            found |= module_scope_bindings(stmt)
        for handler in node.handlers:
            for stmt in handler.body:
                found |= module_scope_bindings(stmt)
        for stmt in node.orelse:
            found |= module_scope_bindings(stmt)
        for stmt in node.finalbody:
            found |= module_scope_bindings(stmt)
        return found

    return found

def direct_assign_single_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Assign):
        return None
    names: set[str] = set()
    for target in node.targets:
        names |= target_names(target)
    if len(names) != 1:
        return None
    return next(iter(names))

tree = ast.parse(src)

delete_records: list[dict[str, Any]] = []
assign_hits: list[dict[str, Any]] = []
if_hits: list[dict[str, Any]] = []
try_hits: list[dict[str, Any]] = []

# ------------------------------------------------------------------
# 1. Delete the 6 capture assignments that only served the dead early shells
# ------------------------------------------------------------------
for node in tree.body:
    start, end = line_span(node)
    name = direct_assign_single_name(node)
    if name in DELETE_CAPTURE_ASSIGN_NAMES:
        rec = {
            "kind": type(node).__name__,
            "category": "dead_capture_assignment",
            "symbol": name,
            "start": start,
            "end": end,
            "span": end - start + 1,
            "text": source_window(start, end),
        }
        assign_hits.append(rec)
        delete_records.append(rec)

# ------------------------------------------------------------------
# 2. Delete the 6 dead early alias-rebinding If shells
# ------------------------------------------------------------------
for node in tree.body:
    if not isinstance(node, ast.If):
        continue

    start, end = line_span(node)
    text = source_window(start, end)
    binds = module_scope_bindings(node)

    capture_refs = sorted(
        name for name in DELETE_CAPTURE_ASSIGN_NAMES
        if name in text
    )

    if len(capture_refs) == 1 and EARLY_ALIAS_TARGETS.issubset(binds):
        rec = {
            "kind": type(node).__name__,
            "category": "dead_early_alias_rebinding_if_shell",
            "symbol": capture_refs[0],
            "start": start,
            "end": end,
            "span": end - start + 1,
            "text": text,
        }
        if_hits.append(rec)
        delete_records.append(rec)

# ------------------------------------------------------------------
# 3. Delete the 3 late pure-dead Try wrapper shells
# ------------------------------------------------------------------
for node in tree.body:
    if not isinstance(node, ast.Try):
        continue

    start, end = line_span(node)
    binds = module_scope_bindings(node)
    hit = sorted(DELETE_TRY_CAPTURE_NAMES & binds)

    if len(hit) == 1:
        rec = {
            "kind": type(node).__name__,
            "category": "dead_late_try_wrapper_shell",
            "symbol": hit[0],
            "start": start,
            "end": end,
            "span": end - start + 1,
            "text": source_window(start, end),
        }
        try_hits.append(rec)
        delete_records.append(rec)

# ------------------------------------------------------------------
# Hard safety assertions: this patch is intentionally narrow.
# ------------------------------------------------------------------
if len(assign_hits) != 6:
    raise RuntimeError(f"Expected 6 dead capture assignments, found {len(assign_hits)}")

if len(if_hits) != 6:
    raise RuntimeError(f"Expected 6 dead early alias-rebinding If shells, found {len(if_hits)}")

if len(try_hits) != 3:
    raise RuntimeError(f"Expected 3 dead late Try wrapper shells, found {len(try_hits)}")

if len(delete_records) != 15:
    raise RuntimeError(f"Expected 15 total deletion records, found {len(delete_records)}")

# No overlapping deletion spans.
occupied: set[int] = set()
for rec in delete_records:
    for line_no in range(rec["start"], rec["end"] + 1):
        if line_no in occupied:
            raise RuntimeError(f"Overlapping deletion span detected at line {line_no}")
        occupied.add(line_no)

deleted_line_count = len(occupied)

# ------------------------------------------------------------------
# Write manifest / source windows
# ------------------------------------------------------------------
manifest_lines = [
    "=== PHASE 44 DELETION MANIFEST ===",
    f"TOTAL_DELETED_TOP_LEVEL_STATEMENTS={len(delete_records)}",
    f"TOTAL_DELETED_SOURCE_LINES={deleted_line_count}",
    "",
    "category | symbol | kind | lines | span",
    "-" * 180,
]

for rec in sorted(delete_records, key=lambda r: r["start"]):
    manifest_lines.append(
        f"{rec['category']} | {rec['symbol']} | {rec['kind']} | "
        f"{rec['start']}-{rec['end']} | {rec['span']}"
    )

(out / "03_deletion_manifest.txt").write_text(
    "\n".join(manifest_lines) + "\n",
    encoding="utf-8",
)

windows: list[str] = []
for rec in sorted(delete_records, key=lambda r: r["start"]):
    windows.append("=" * 120)
    windows.append(
        f"{rec['category']} | symbol={rec['symbol']} | "
        f"{rec['kind']} | lines={rec['start']}-{rec['end']}"
    )
    windows.append("=" * 120)
    windows.append(rec["text"])
    windows.append("")

(out / "04_deleted_source_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------------
# Apply deletion
# ------------------------------------------------------------------
new_lines = [
    line for line_no, line in enumerate(lines, start=1)
    if line_no not in occupied
]

new_src = "\n".join(new_lines)
if src.endswith("\n"):
    new_src += "\n"

router_path.write_text(new_src, encoding="utf-8")

(out / "05_patch_application_summary.txt").write_text(
    "\n".join([
        "=== PHASE 44 PATCH APPLICATION SUMMARY ===",
        f"Deleted top-level statements: {len(delete_records)}",
        f"Deleted source lines: {deleted_line_count}",
        "Deleted cluster type: cascading dead-shell cluster",
        "",
        "Deleted categories:",
        f"- dead capture assignments: {len(assign_hits)}",
        f"- dead early alias-rebinding If shells: {len(if_hits)}",
        f"- dead late Try wrapper shells: {len(try_hits)}",
    ]) + "\n",
    encoding="utf-8",
)

print("=== PHASE 44 PATCH APPLICATION SUMMARY ===")
print(f"Deleted top-level statements: {len(delete_records)}")
print(f"Deleted source lines: {deleted_line_count}")
print(f"Deleted dead capture assignments: {len(assign_hits)}")
print(f"Deleted dead early alias-rebinding If shells: {len(if_hits)}")
print(f"Deleted dead late Try wrapper shells: {len(try_hits)}")
PY

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/06_post_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/06_post_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/06_post_compile.txt"

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/07_post_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/07_post_phase36_console.txt"

POST_PHASE36_OUT="$(
  grep -oE 'PHASE36_V2_OUT=.*' "$OUT/07_post_phase36_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${POST_PHASE36_OUT:-}" || ! -d "$POST_PHASE36_OUT" ]]; then
  echo "Could not resolve POST_PHASE36_OUT" >&2
  exit 1
fi

POST_JSON="$POST_PHASE36_OUT/05_router_flattening_semantic_baseline.json"

if [[ ! -f "$POST_JSON" ]]; then
  echo "Missing post-patch Phase 36 semantic JSON: $POST_JSON" >&2
  exit 1
fi

cp "$POST_JSON" "$OUT/08_post_phase36_semantic_baseline.json"

python3 - "$OUT/02_pre_phase36_semantic_baseline.json" "$OUT/08_post_phase36_semantic_baseline.json" "$OUT" <<'PY'
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

pre_path = Path(sys.argv[1])
post_path = Path(sys.argv[2])
out = Path(sys.argv[3])

pre_raw = pre_path.read_text(encoding="utf-8")
post_raw = post_path.read_text(encoding="utf-8")

raw_equal = pre_raw == post_raw
parsed_equal = json.loads(pre_raw) == json.loads(post_raw)

diff_text = "".join(
    difflib.unified_diff(
        pre_raw.splitlines(keepends=True),
        post_raw.splitlines(keepends=True),
        fromfile=str(pre_path),
        tofile=str(post_path),
    )
)

if not diff_text:
    diff_text = "NO_DIFF\n"

(out / "09_phase36_semantic_baseline_exact_diff.txt").write_text(
    diff_text,
    encoding="utf-8",
)

compare_text = "\n".join([
    "=== PHASE 44 EXACT SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
    "DIFF_WRITTEN=09_phase36_semantic_baseline_exact_diff.txt",
])

(out / "10_phase36_semantic_baseline_exact_compare.txt").write_text(
    compare_text + "\n",
    encoding="utf-8",
)

print(compare_text)

if not raw_equal or not parsed_equal:
    raise SystemExit("Phase 36 semantic baseline changed after Phase 44 prune")
PY

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import inspect
import sys
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

import eli.execution.router_enhanced as router

names = ["route", "route_intent", "route_command", "parse_command", "classify"]
base = router.route

lines = [
    "=== PHASE 44 RUNTIME PUBLIC SURFACE IDENTITY PROBE ===",
]

for name in names:
    fn = getattr(router, name, None)
    lines.append(
        f"{name}: callable={callable(fn)} "
        f"same_as_route={fn is base} "
        f"id={id(fn) if callable(fn) else None} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else None}"
    )

all_same = all(getattr(router, name, None) is base for name in names)

lines.append("")
lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "11_runtime_public_surface_identity_probe.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print("\n".join(lines))

if not all_same:
    raise SystemExit("Public router surfaces drifted after Phase 44 prune")
PY

{
  echo "=== PHASE 44 TARGET SYMBOL RESIDUE CHECK ==="
  for sym in \
    "_ELI_OPEN_TYPO_ORIG_ROUTE" \
    "_ELI_MQC_ORIG_ROUTE" \
    "_ELI_ID_ORIG_ROUTE" \
    "_ELI_TINY_ORIG_ROUTE" \
    "_ELI_FOLLOWUP_ORIG_ROUTE" \
    "_ELI_PR_ORIG_ROUTE" \
    "_ELI_FINAL_RUNTIME_STATUS_ROUTE_PREV" \
    "_ELI_FINAL_MEMORY_ROUTE_PREV" \
    "_ELI_PERSONAL_MEMORY_SUMMARY_COMPAT_PREV"
  do
    echo
    echo "--- $sym ---"
    grep -n "$sym" "$ROUTER" || true
  done
} > "$OUT/12_target_symbol_residue_check.txt"

MARKER_LINE="$(grep -n "$PHASE38_MARKER" "$ROUTER" | head -1 | cut -d: -f1)"

if [[ -z "${MARKER_LINE:-}" ]]; then
  echo "Could not resolve Phase 38 marker line after patch" >&2
  exit 1
fi

PRE_MARKER_TMP="$OUT/.pre_phase38_router_slice.tmp"
sed -n "1,$((MARKER_LINE - 1))p" "$ROUTER" > "$PRE_MARKER_TMP"

grep -nE \
  '_ELI_[A-Z0-9_]*(PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)|_eli_[a-z0-9_]*(previous_route|prev_route|prev_route_intent)' \
  "$PRE_MARKER_TMP" \
  > "$OUT/13_post_patch_residual_route_capture_symbol_hits.txt" || true

grep -nE \
  '^[[:space:]]*(route_intent|route_command|parse_command|classify)[[:space:]]*=[[:space:]]*route\b' \
  "$PRE_MARKER_TMP" \
  > "$OUT/14_post_patch_residual_public_surface_alias_rebindings.txt" || true

rm -f "$PRE_MARKER_TMP"

CAPTURE_REMAINING="$(wc -l < "$OUT/13_post_patch_residual_route_capture_symbol_hits.txt" | tr -d ' ')"
ALIAS_REMAINING="$(wc -l < "$OUT/14_post_patch_residual_public_surface_alias_rebindings.txt" | tr -d ' ')"

POST_PHASE43_OUT=""
if [[ -f "$PHASE43_SCRIPT" ]]; then
  echo "=== POST-PATCH PHASE 43 RESIDUAL SHELL AUDIT ===" | tee "$OUT/15_post_phase43_console.txt"
  bash "$PHASE43_SCRIPT" 2>&1 | tee -a "$OUT/15_post_phase43_console.txt"

  POST_PHASE43_OUT="$(
    grep -oE 'PHASE43_OUT=.*' "$OUT/15_post_phase43_console.txt" \
      | tail -1 \
      | cut -d= -f2-
  )"
else
  echo "Phase 43 script not present; residual-shell re-audit skipped." \
    | tee "$OUT/15_post_phase43_console.txt"
fi

diff -u \
  "$OUT/backups/router_enhanced.py.before_phase44.bak" \
  "$ROUTER" \
  > "$OUT/16_router_source_diff.patch" || true

DELETED_STATEMENTS="$(
  grep -oE 'Deleted top-level statements: [0-9]+' "$OUT/05_patch_application_summary.txt" \
    | awk '{print $4}'
)"

DELETED_LINES="$(
  grep -oE 'Deleted source lines: [0-9]+' "$OUT/05_patch_application_summary.txt" \
    | awk '{print $4}'
)"

RAW_EQUAL="$(
  grep -oE 'RAW_JSON_EQUAL=(True|False)' "$OUT/10_phase36_semantic_baseline_exact_compare.txt" \
    | cut -d= -f2
)"

PARSED_EQUAL="$(
  grep -oE 'PARSED_JSON_EQUAL=(True|False)' "$OUT/10_phase36_semantic_baseline_exact_compare.txt" \
    | cut -d= -f2
)"

cat > "$OUT/17_console_digest.txt" <<EOF
=== PHASE 44 DIGEST ===
Router compile: PASS
Cascading dead-shell cluster prune: PASS
Deleted top-level statements: ${DELETED_STATEMENTS:-UNKNOWN}
Deleted source lines: ${DELETED_LINES:-UNKNOWN}

Phase 36 pre/post raw semantic JSON exact equality: ${RAW_EQUAL:-UNKNOWN}
Phase 36 pre/post parsed semantic JSON equality: ${PARSED_EQUAL:-UNKNOWN}
Runtime public routing surfaces remain canonical: PASS

Post-patch pre-Phase38 residual debt:
- route-capture symbol hit lines remaining: ${CAPTURE_REMAINING}
- public-surface alias rebinding lines remaining: ${ALIAS_REMAINING}

Interpretation:
- Phase 44 removed the full dead cluster exposed by Phase 43:
  six dead capture assignments, six dead early alias shells, and three dead late Try shells.
- The remaining residue should now be dominated by mixed live helper-hosting blocks and
  narrower retained adapter chains.
- A future Phase 45 should split the remaining mixed helper+shell blocks, preserving the
  Phase 38-required helper functions while deleting their inert wrapper-capture scaffolding.

Review:
- 03_deletion_manifest.txt
- 04_deleted_source_windows.txt
- 09_phase36_semantic_baseline_exact_diff.txt
- 10_phase36_semantic_baseline_exact_compare.txt
- 11_runtime_public_surface_identity_probe.txt
- 12_target_symbol_residue_check.txt
- 13_post_patch_residual_route_capture_symbol_hits.txt
- 14_post_patch_residual_public_surface_alias_rebindings.txt
- 15_post_phase43_console.txt
- 16_router_source_diff.patch

PHASE44_OUT=$OUT
POST_PHASE43_OUT=${POST_PHASE43_OUT:-SKIPPED}
EOF

cat "$OUT/17_console_digest.txt"

{
  echo
  echo "## Phase 44 artifacts"
  echo "- \`00_pre_compile.txt\`"
  echo "- \`01_pre_phase36_console.txt\`"
  echo "- \`02_pre_phase36_semantic_baseline.json\`"
  echo "- \`03_deletion_manifest.txt\`"
  echo "- \`04_deleted_source_windows.txt\`"
  echo "- \`05_patch_application_summary.txt\`"
  echo "- \`06_post_compile.txt\`"
  echo "- \`07_post_phase36_console.txt\`"
  echo "- \`08_post_phase36_semantic_baseline.json\`"
  echo "- \`09_phase36_semantic_baseline_exact_diff.txt\`"
  echo "- \`10_phase36_semantic_baseline_exact_compare.txt\`"
  echo "- \`11_runtime_public_surface_identity_probe.txt\`"
  echo "- \`12_target_symbol_residue_check.txt\`"
  echo "- \`13_post_patch_residual_route_capture_symbol_hits.txt\`"
  echo "- \`14_post_patch_residual_public_surface_alias_rebindings.txt\`"
  echo "- \`15_post_phase43_console.txt\`"
  echo "- \`16_router_source_diff.patch\`"
  echo "- \`17_console_digest.txt\`"
  echo
  echo "PHASE44_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE44_OUT=$OUT"
