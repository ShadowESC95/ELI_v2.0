#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase40_router_obsolete_public_wrapper_function_prune_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT/backups"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if [[ ! -f "$PHASE36_SCRIPT" ]]; then
  echo "Missing Phase 36 baseline script: $PHASE36_SCRIPT" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Phase 38 marker missing: $PHASE38_MARKER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase40.bak"

PATCH_APPLIED=0

restore_router() {
  if [[ "$PATCH_APPLIED" -eq 1 ]]; then
    cp "$OUT/backups/router_enhanced.py.before_phase40.bak" "$ROUTER"
    echo "[PHASE40] Router restored from backup after failure." >&2
  fi
}

fail_and_restore() {
  echo "[PHASE40] FAILURE: $*" >&2
  restore_router
  exit 1
}

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 40 — Router Obsolete Public Wrapper Function Prune

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair scope

This phase removes obsolete **pre-Phase38 public wrapper function definitions**
while preserving:

- the original core route() body;
- _ROUTE_CORE;
- Phase 38 flattened canonical dispatch;
- helper predicates/functions Phase 38 still relies on;
- all final public routing semantics.

## Non-goals

This phase does **not** yet remove every stale capture variable, alias assignment,
or helper-hosting try/except shell. That is reserved for the next cleanup pass
after this source-function prune is proven semantically lossless.
EOF

echo "=== PRE-PATCH PY_COMPILE ===" | tee "$OUT/00_pre_compile.txt"
if ! python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_pre_compile.txt"; then
  fail_and_restore "pre-patch py_compile failed"
fi
echo "PY_COMPILE_OK" | tee -a "$OUT/00_pre_compile.txt"

echo "=== PRE-PATCH PHASE 36 BASELINE ===" | tee "$OUT/01_pre_phase36_run.txt"
if ! bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/01_pre_phase36_run.txt"; then
  fail_and_restore "pre-patch Phase 36 baseline failed"
fi

PRE_PHASE36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"
PRE_JSON="$PRE_PHASE36_OUT/05_router_flattening_semantic_baseline.json"

if [[ ! -f "$PRE_JSON" ]]; then
  fail_and_restore "pre-patch Phase 36 JSON missing: $PRE_JSON"
fi

cp "$PRE_JSON" "$OUT/02_pre_phase36_semantic_baseline.json"
cp "$PRE_PHASE36_OUT/08_console_digest.txt" "$OUT/03_pre_phase36_digest.txt" 2>/dev/null || true

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

router = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router.read_text(encoding="utf-8")
lines = src.splitlines()

PHASE38_MARKER = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

marker_line = None
for i, line in enumerate(lines, start=1):
    if PHASE38_MARKER in line:
        marker_line = i
        break

if marker_line is None:
    raise RuntimeError("Phase 38 marker not found")

tree = ast.parse(src)

def end_lineno(node: ast.AST) -> int:
    return getattr(node, "end_lineno", getattr(node, "lineno", -1))

surface_defs: list[dict[str, int | str]] = []

for node in ast.walk(tree):
    if not isinstance(node, ast.FunctionDef):
        continue

    start = getattr(node, "lineno", -1)
    if start < 1 or start >= marker_line:
        continue

    if node.name not in {"route", "route_intent", "route_command", "parse_command", "classify"}:
        continue

    surface_defs.append({
        "name": node.name,
        "start": start,
        "end": end_lineno(node),
    })

surface_defs.sort(key=lambda rec: (int(rec["start"]), int(rec["end"])))

route_defs = [rec for rec in surface_defs if rec["name"] == "route"]
if not route_defs:
    raise RuntimeError("No pre-Phase38 route() definition found")

core_route = route_defs[0]

delete_defs: list[dict[str, int | str]] = []
for rec in surface_defs:
    if rec is core_route:
        continue
    delete_defs.append(rec)

delete_line_numbers: set[int] = set()
for rec in delete_defs:
    start = int(rec["start"])
    end = int(rec["end"])
    delete_line_numbers.update(range(start, end + 1))

# Remove obsolete import-time success banners tied to retired wrapper installs.
stale_install_log_fragments = (
    "single closure-safe identity/name-source route fix installed",
    "final runtime-status route contract installed",
    "final memory-question route contract installed",
    "PERSONAL_MEMORY_SUMMARY compatibility installed",
    "identity scope contract installed",
    "profile memory scope contract installed",
    "memory-count grounded synthesis route installed",
    "recent-memory-processing grounded route installed",
    "self-report recent-updates grounded route installed",
    "GUI audit actual-scan proof route v2 installed",
    "memory-runtime strict route lock installed",
    "final personal-memory precedence wrapper installed after memory-runtime lock",
    "Phase 11 multi-PDF route contract installed",
    "canonical public routing surfaces rebound to final route",
)

removed_log_lines: list[tuple[int, str]] = []
for i, line in enumerate(lines, start=1):
    if i >= marker_line:
        continue
    if any(fragment in line for fragment in stale_install_log_fragments):
        delete_line_numbers.add(i)
        removed_log_lines.append((i, line))

new_lines = [
    line
    for i, line in enumerate(lines, start=1)
    if i not in delete_line_numbers
]

new_src = "\n".join(new_lines) + ("\n" if src.endswith("\n") else "")
router.write_text(new_src, encoding="utf-8")

inventory_lines = [
    "=== PHASE 40 DELETED PRE-PHASE38 PUBLIC WRAPPER FUNCTION DEFINITIONS ===",
    f"Phase 38 marker line before patch: {marker_line}",
    "",
    "Retained core route():",
    f"- route | {core_route['start']}-{core_route['end']}",
    "",
    "Deleted obsolete public wrapper defs:",
    "name | lines",
    "-" * 80,
]

for rec in delete_defs:
    inventory_lines.append(f"{rec['name']} | {rec['start']}-{rec['end']}")

inventory_lines.extend([
    "",
    f"TOTAL_DELETED_FUNCTION_DEFS={len(delete_defs)}",
    f"TOTAL_DELETED_ROUTE_DEFS={sum(1 for rec in delete_defs if rec['name'] == 'route')}",
    f"TOTAL_DELETED_ROUTE_INTENT_DEFS={sum(1 for rec in delete_defs if rec['name'] == 'route_intent')}",
    f"TOTAL_DELETED_ROUTE_COMMAND_DEFS={sum(1 for rec in delete_defs if rec['name'] == 'route_command')}",
    f"TOTAL_DELETED_PARSE_COMMAND_DEFS={sum(1 for rec in delete_defs if rec['name'] == 'parse_command')}",
    f"TOTAL_DELETED_CLASSIFY_DEFS={sum(1 for rec in delete_defs if rec['name'] == 'classify')}",
])

(out / "04_deleted_wrapper_function_inventory.txt").write_text(
    "\n".join(inventory_lines) + "\n",
    encoding="utf-8",
)

log_lines = [
    "=== PHASE 40 REMOVED STALE IMPORT-TIME SUCCESS LOG LINES ===",
]
for lineno, line in removed_log_lines:
    log_lines.append(f"{lineno}: {line}")

log_lines.append("")
log_lines.append(f"TOTAL_REMOVED_STALE_INSTALL_LOG_LINES={len(removed_log_lines)}")

(out / "05_removed_stale_import_success_logs.txt").write_text(
    "\n".join(log_lines) + "\n",
    encoding="utf-8",
)
PY

PATCH_APPLIED=1

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/06_post_compile.txt"
if ! python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/06_post_compile.txt"; then
  fail_and_restore "post-patch py_compile failed"
fi
echo "PY_COMPILE_OK" | tee -a "$OUT/06_post_compile.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

router = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router.read_text(encoding="utf-8")
lines = src.splitlines()

marker = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"
marker_line = next(
    (i for i, line in enumerate(lines, start=1) if marker in line),
    None,
)
if marker_line is None:
    raise RuntimeError("Phase 38 marker missing after patch")

tree = ast.parse(src)

counts = {
    "route": 0,
    "route_intent": 0,
    "route_command": 0,
    "parse_command": 0,
    "classify": 0,
}

defs = []

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        lineno = getattr(node, "lineno", -1)
        if 0 < lineno < marker_line and node.name in counts:
            counts[node.name] += 1
            defs.append((node.name, lineno, getattr(node, "end_lineno", lineno)))

report = [
    "=== PHASE 40 POST-PATCH PRE-PHASE38 PUBLIC SURFACE FUNCTION DEF SNAPSHOT ===",
    f"Phase 38 marker line after patch: {marker_line}",
    "",
    "name | count",
    "-" * 40,
]
for name in ["route", "route_intent", "route_command", "parse_command", "classify"]:
    report.append(f"{name} | {counts[name]}")

report.extend([
    "",
    "Remaining pre-Phase38 public-surface function defs:",
])
for name, start, end in defs:
    report.append(f"- {name} | {start}-{end}")

expected = {
    "route": 1,
    "route_intent": 0,
    "route_command": 0,
    "parse_command": 0,
    "classify": 0,
}
ok = counts == expected

report.extend([
    "",
    f"EXPECTED_COUNTS={expected}",
    f"ACTUAL_COUNTS={counts}",
    f"PUBLIC_WRAPPER_FUNCTION_PRUNE_ASSERTION_OK={ok}",
])

(out / "07_post_patch_public_surface_function_def_snapshot.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

if not ok:
    raise SystemExit(2)
PY

if [[ "$?" -ne 0 ]]; then
  fail_and_restore "post-patch public wrapper function-count assertion failed"
fi

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/08_post_phase36_run.txt"
if ! bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/08_post_phase36_run.txt"; then
  fail_and_restore "post-patch Phase 36 baseline failed"
fi

POST_PHASE36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"
POST_JSON="$POST_PHASE36_OUT/05_router_flattening_semantic_baseline.json"

if [[ ! -f "$POST_JSON" ]]; then
  fail_and_restore "post-patch Phase 36 JSON missing: $POST_JSON"
fi

cp "$POST_JSON" "$OUT/09_post_phase36_semantic_baseline.json"
cp "$POST_PHASE36_OUT/08_console_digest.txt" "$OUT/10_post_phase36_digest.txt" 2>/dev/null || true

python3 - "$OUT/02_pre_phase36_semantic_baseline.json" "$OUT/09_post_phase36_semantic_baseline.json" "$OUT" <<'PY'
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

pre_obj = json.loads(pre_raw)
post_obj = json.loads(post_raw)

raw_equal = pre_raw == post_raw
json_equal = pre_obj == post_obj

diff = list(
    difflib.unified_diff(
        pre_raw.splitlines(),
        post_raw.splitlines(),
        fromfile=str(pre_path),
        tofile=str(post_path),
        lineterm="",
    )
)

(out / "11_phase36_semantic_baseline_exact_diff.txt").write_text(
    "\n".join(diff) + ("\n" if diff else "NO_DIFF\n"),
    encoding="utf-8",
)

compare = f"""=== PHASE 40 EXACT SEMANTIC BASELINE COMPARISON ===
PRE_JSON={pre_path}
POST_JSON={post_path}
RAW_JSON_EQUAL={raw_equal}
PARSED_JSON_EQUAL={json_equal}
DIFF_WRITTEN=11_phase36_semantic_baseline_exact_diff.txt
"""

(out / "12_phase36_semantic_baseline_exact_compare.txt").write_text(compare, encoding="utf-8")
print(compare)

if not raw_equal or not json_equal:
    raise SystemExit(2)
PY

if [[ "$?" -ne 0 ]]; then
  fail_and_restore "Phase 36 semantic JSON changed after wrapper-function prune"
fi

{
  diff -u \
    "$OUT/backups/router_enhanced.py.before_phase40.bak" \
    "$ROUTER" \
    || true
} > "$OUT/13_router_source_diff.patch"

POST_DIGEST="$(cat "$OUT/10_post_phase36_digest.txt" 2>/dev/null || true)"

cat > "$OUT/14_console_digest.txt" <<EOF
=== PHASE 40 DIGEST ===
Router compile: PASS
Obsolete pre-Phase38 public wrapper function prune: PASS
Retained original core route() body: PASS
Post-patch pre-Phase38 public surface function counts: PASS
Phase 36 pre/post raw semantic JSON exact equality: PASS
Phase 36 pre/post parsed semantic JSON equality: PASS

What changed:
- Removed obsolete late public wrapper FunctionDef source before Phase 38.
- Preserved the original core route body and all Phase 38-required helpers.
- Removed stale import-time success banners tied to retired wrapper installs.

What remains intentionally:
- stale capture variables and some legacy assignment shells around retained helpers;
- those are source debt for the next pass, not required for Phase 40 correctness.

Review:
- 04_deleted_wrapper_function_inventory.txt
- 05_removed_stale_import_success_logs.txt
- 07_post_patch_public_surface_function_def_snapshot.txt
- 12_phase36_semantic_baseline_exact_compare.txt
- 11_phase36_semantic_baseline_exact_diff.txt
- 13_router_source_diff.patch

PHASE40_OUT=$OUT
EOF

cat "$OUT/14_console_digest.txt"

{
  echo
  echo "## Phase 40 artifacts"
  echo "- \`00_pre_compile.txt\`"
  echo "- \`01_pre_phase36_run.txt\`"
  echo "- \`02_pre_phase36_semantic_baseline.json\`"
  echo "- \`03_pre_phase36_digest.txt\`"
  echo "- \`04_deleted_wrapper_function_inventory.txt\`"
  echo "- \`05_removed_stale_import_success_logs.txt\`"
  echo "- \`06_post_compile.txt\`"
  echo "- \`07_post_patch_public_surface_function_def_snapshot.txt\`"
  echo "- \`08_post_phase36_run.txt\`"
  echo "- \`09_post_phase36_semantic_baseline.json\`"
  echo "- \`10_post_phase36_digest.txt\`"
  echo "- \`11_phase36_semantic_baseline_exact_diff.txt\`"
  echo "- \`12_phase36_semantic_baseline_exact_compare.txt\`"
  echo "- \`13_router_source_diff.patch\`"
  echo "- \`14_console_digest.txt\`"
  echo
  echo "PHASE40_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE40_OUT=$OUT"
