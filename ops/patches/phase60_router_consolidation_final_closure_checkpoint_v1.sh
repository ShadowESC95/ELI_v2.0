#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase60_router_consolidation_final_closure_checkpoint_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"

PHASE36="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE45B="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE58="ops/patches/phase58_phase54_readiness_branch_reconciliation_audit_v1.sh"

PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

for f in "$ROUTER" "$PHASE36" "$PHASE45B" "$PHASE58"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<EOF
# Phase60 — Router Consolidation Final Closure Checkpoint

Generated: $(date -Is)  
Root: $ROOT  
Router: $ROUTER

## Closure purpose

This checkpoint determines whether the router consolidation sequence can be
declared complete.

It verifies:

1. Router Python compilation
2. Phase38 flattened canonical dispatcher marker remains present
3. Public router surfaces remain a single canonical function object:
   - route
   - route_intent
   - route_command
   - parse_command
   - classify
4. Module-level structural route/route_intent function-definition debt is absent
   or, if present, explicitly exposed as a closure failure
5. Phase36 semantic baseline remains clean:
   - no surface mismatches
   - no surface errors
   - no targeted baseline assertion failures
6. Phase45b residual router-shell debt remains closed:
   - mixed pre-Phase38 Try blocks = 0
   - residual route-capture symbol hits = 0
   - residual public alias rebinding hits = 0
   - actionable adapter candidate chains = 0
7. Phase58 reconciliation branch remains closed:
   - Phase54 stale source/runtime indicators false
   - Phase54b stale source/runtime indicators false
   - no stale recommendation loop back to Phase59
8. Final checkpoint emits a closure verdict:
   - ROUTER_CONSOLIDATION_CLOSED=TRUE
   - or ROUTER_CONSOLIDATION_CLOSED=FALSE
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

{
  echo "=== PHASE38 MARKER CHECK ==="
  if grep -nF "$PHASE38_MARKER" "$ROUTER"; then
    echo "PHASE38_MARKER_PRESENT=True"
  else
    echo "PHASE38_MARKER_PRESENT=False"
  fi
} > "$OUT/01_phase38_marker_check.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from collections import Counter
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

# ------------------------------------------------------------------
# A. Runtime public-surface identity probe
# ------------------------------------------------------------------

mod = importlib.import_module("eli.execution.router_enhanced")

surface_names = [
    "route",
    "route_intent",
    "route_command",
    "parse_command",
    "classify",
]

runtime_lines = ["=== PHASE60 PUBLIC ROUTER SURFACE IDENTITY ==="]
surface_objs = {}

for name in surface_names:
    obj = getattr(mod, name, None)
    surface_objs[name] = obj
    if callable(obj):
        try:
            sig = str(inspect.signature(obj))
        except Exception:
            sig = "<signature unavailable>"
        runtime_lines.append(
            f"{name}: callable=True "
            f"id={id(obj)} "
            f"name={getattr(obj, '__name__', '<unknown>')!r} "
            f"firstlineno={getattr(getattr(obj, '__code__', None), 'co_firstlineno', None)} "
            f"signature={sig}"
        )
    else:
        runtime_lines.append(f"{name}: callable=False repr={obj!r}")

route_obj = surface_objs.get("route")
all_same = (
    callable(route_obj)
    and all(surface_objs.get(name) is route_obj for name in surface_names)
)

runtime_lines.append("")
runtime_lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "02_public_surface_identity_probe.txt").write_text(
    "\n".join(runtime_lines) + "\n",
    encoding="utf-8",
)

# ------------------------------------------------------------------
# B. Structural AST audit for module-level route/route_intent debt
# ------------------------------------------------------------------

src = router_path.read_text(encoding="utf-8")
tree = ast.parse(src)

module_defs = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.name in {"route", "route_intent", "route_command", "parse_command", "classify"}:
            module_defs.append(
                {
                    "name": node.name,
                    "lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", None),
                    "args": [a.arg for a in node.args.args],
                }
            )

counts = Counter(item["name"] for item in module_defs)

struct_lines = ["=== PHASE60 MODULE-LEVEL PUBLIC ROUTER DEF SNAPSHOT ==="]
for item in module_defs:
    struct_lines.append(
        f"{item['name']} | lines={item['lineno']}-{item['end_lineno']} | args={item['args']}"
    )

struct_lines.append("")
struct_lines.append("=== COUNTS ===")
for name in surface_names:
    struct_lines.append(f"{name}={counts.get(name, 0)}")

route_def_count = counts.get("route", 0)
route_intent_def_count = counts.get("route_intent", 0)

# Closure expectation:
# - At most one module-level route() implementation should remain as active flattened route.
# - route_intent should not remain as an independent function body if surfaces are canonically rebound.
structural_public_def_debt_closed = (
    route_def_count <= 1
    and route_intent_def_count == 0
)

struct_lines.append("")
struct_lines.append(
    f"STRUCTURAL_PUBLIC_ROUTER_DEF_DEBT_CLOSED={structural_public_def_debt_closed}"
)

(out / "03_structural_public_router_def_snapshot.txt").write_text(
    "\n".join(struct_lines) + "\n",
    encoding="utf-8",
)

(out / "04_structural_public_router_def_snapshot.json").write_text(
    json.dumps(
        {
            "module_defs": module_defs,
            "counts": dict(counts),
            "structural_public_router_def_debt_closed": structural_public_def_debt_closed,
        },
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)
PY

echo "=== RUN PHASE36 SEMANTIC BASELINE ===" | tee "$OUT/05_phase36_rerun.txt"
bash "$PHASE36" 2>&1 | tee -a "$OUT/05_phase36_rerun.txt"

PHASE36_OUT="$(
  grep -oE 'PHASE36_V2_OUT=.*' "$OUT/05_phase36_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE36_OUT:-}" || ! -d "$PHASE36_OUT" ]]; then
  PHASE36_OUT="$(
    ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE36_OUT:-}" || ! -d "$PHASE36_OUT" ]]; then
  echo "Could not resolve fresh Phase36 output directory." >&2
  exit 1
fi

echo "PHASE36_OUT=$PHASE36_OUT" | tee "$OUT/06_phase36_out_path.txt"

for f in \
  "$PHASE36_OUT/07_targeted_baseline_assertions.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected Phase36 artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/07_phase36_targeted_baseline_assertions.txt"

grep -E \
  'Public surface mismatches:|Public surface errors:|Targeted baseline assertion failures:' \
  "$OUT/05_phase36_rerun.txt" \
  > "$OUT/08_phase36_digest_key_lines.txt" || true

echo "=== RUN PHASE45b RESIDUAL-SHELL AUDIT ===" | tee "$OUT/09_phase45b_rerun.txt"
bash "$PHASE45B" 2>&1 | tee -a "$OUT/09_phase45b_rerun.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/09_phase45b_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  PHASE45B_OUT="$(
    ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve fresh Phase45b output directory." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/10_phase45b_out_path.txt"

for f in \
  "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
  "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
  "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected Phase45b artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/11_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/12_phase45b_legacy_adapter_inventory.txt"

cp "$PHASE45B_OUT/07b_legacy_adapter_chain_source_presence_reconciliation.txt" \
   "$OUT/13_phase45b_legacy_adapter_reconciliation.txt"

grep -E \
  'Mixed pre-Phase38 Try blocks|Mechanically splittable mixed blocks|Blocks requiring manual/deeper handling|Residual route-capture symbol hit lines before Phase38|Residual public alias rebinding hit lines before Phase38|Legacy adapter actionable guarded-delete candidate chains|Legacy adapter catalogue-only already-absent chains|Legacy adapter retain/deeper-review chains' \
  "$OUT/09_phase45b_rerun.txt" \
  > "$OUT/14_phase45b_digest_key_lines.txt" || true

echo "=== RUN PHASE58 RECONCILIATION CLOSURE AUDIT ===" | tee "$OUT/15_phase58_rerun.txt"
bash "$PHASE58" 2>&1 | tee -a "$OUT/15_phase58_rerun.txt"

PHASE58_OUT="$(
  grep -oE 'PHASE58_OUT=.*' "$OUT/15_phase58_rerun.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE58_OUT:-}" || ! -d "$PHASE58_OUT" ]]; then
  PHASE58_OUT="$(
    ls -td ops/reports/phase58_phase54_readiness_branch_reconciliation_audit_* \
      2>/dev/null \
      | head -1 || true
  )"
fi

if [[ -z "${PHASE58_OUT:-}" || ! -d "$PHASE58_OUT" ]]; then
  echo "Could not resolve fresh Phase58 output directory." >&2
  exit 1
fi

echo "PHASE58_OUT=$PHASE58_OUT" | tee "$OUT/16_phase58_out_path.txt"

for f in \
  "$PHASE58_OUT/12_reconciliation_matrix.txt" \
  "$PHASE58_OUT/13_recommended_next_move.txt" \
  "$PHASE58_OUT/14_targeted_assertions.txt" \
  "$PHASE58_OUT/15_console_digest.txt"
do
  if [[ ! -f "$f" ]]; then
    echo "Expected Phase58 artifact missing: $f" >&2
    exit 1
  fi
done

cp "$PHASE58_OUT/12_reconciliation_matrix.txt" \
   "$OUT/17_phase58_reconciliation_matrix.txt"

cp "$PHASE58_OUT/13_recommended_next_move.txt" \
   "$OUT/18_phase58_recommended_next_move.txt"

cp "$PHASE58_OUT/14_targeted_assertions.txt" \
   "$OUT/19_phase58_targeted_assertions.txt"

cp "$PHASE58_OUT/15_console_digest.txt" \
   "$OUT/20_phase58_console_digest.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys

out = Path(sys.argv[1])

marker = (out / "01_phase38_marker_check.txt").read_text(encoding="utf-8")
surface = (out / "02_public_surface_identity_probe.txt").read_text(encoding="utf-8")
structural = (out / "03_structural_public_router_def_snapshot.txt").read_text(encoding="utf-8")

phase36_rerun = (out / "05_phase36_rerun.txt").read_text(encoding="utf-8")
phase36_assertions = (out / "07_phase36_targeted_baseline_assertions.txt").read_text(encoding="utf-8")

phase45b_rerun = (out / "09_phase45b_rerun.txt").read_text(encoding="utf-8")

phase58_matrix = (out / "17_phase58_reconciliation_matrix.txt").read_text(encoding="utf-8")
phase58_next = (out / "18_phase58_recommended_next_move.txt").read_text(encoding="utf-8")
phase58_assertions = (out / "19_phase58_targeted_assertions.txt").read_text(encoding="utf-8")
phase58_digest = (out / "20_phase58_console_digest.txt").read_text(encoding="utf-8")

checks: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    checks.append((label, ok, detail))

# ------------------------------------------------------------------
# Router direct closure checks
# ------------------------------------------------------------------

check(
    "Phase38 flattened canonical dispatcher marker remains present",
    "PHASE38_MARKER_PRESENT=True" in marker,
    "Phase38 marker absent",
)

check(
    "All public router surfaces still share one function object",
    "ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT=True" in surface,
    "public surface identity drift detected",
)

check(
    "Structural public router function-definition debt is closed",
    "STRUCTURAL_PUBLIC_ROUTER_DEF_DEBT_CLOSED=True" in structural,
    "module-level route/route_intent structural debt still present",
)

# ------------------------------------------------------------------
# Phase36 closure checks
# ------------------------------------------------------------------

check(
    "Phase36 reports zero public surface mismatches",
    "Public surface mismatches: 0" in phase36_rerun,
    "Phase36 surface mismatches not zero",
)

check(
    "Phase36 reports zero public surface errors",
    "Public surface errors: 0" in phase36_rerun,
    "Phase36 surface errors not zero",
)

check(
    "Phase36 reports zero targeted baseline assertion failures",
    "Targeted baseline assertion failures: 0" in phase36_rerun,
    "Phase36 targeted baseline assertion failures not zero",
)

# ------------------------------------------------------------------
# Phase45b closure checks
# ------------------------------------------------------------------

phase45b_expectations = {
    "Mixed pre-Phase38 Try blocks with post-marker live binds: 0": "mixed Try blocks remain",
    "Mechanically splittable mixed blocks: 0": "mechanically splittable blocks remain",
    "Blocks requiring manual/deeper handling: 0": "manual/deeper blocks remain",
    "Residual route-capture symbol hit lines before Phase38: 0": "route-capture residue remains",
    "Residual public alias rebinding hit lines before Phase38: 0": "public-alias rebinding residue remains",
    "Legacy adapter actionable guarded-delete candidate chains: 0": "actionable adapter chains remain",
    "Legacy adapter catalogue-only already-absent chains: 4": "catalogue-only absent adapter count drifted",
    "Legacy adapter retain/deeper-review chains: 0": "retain/deeper-review chains remain",
}

for needle, detail in phase45b_expectations.items():
    check(
        f"Phase45b confirms: {needle}",
        needle in phase45b_rerun,
        detail,
    )

# ------------------------------------------------------------------
# Phase58 closure checks
# ------------------------------------------------------------------

phase58_matrix_expectations = [
    "phase54_source_stale_hits_present=False",
    "phase54b_source_stale_hits_present=False",
    "phase54_runtime_stale_guidance_present=False",
    "phase54b_runtime_stale_guidance_present=False",
]

for needle in phase58_matrix_expectations:
    check(
        f"Phase58 reconciliation matrix confirms {needle}",
        needle in phase58_matrix,
        f"missing or false: {needle}",
    )

check(
    "Phase58 rerun targeted assertions remain zero",
    "TARGETED_ASSERTION_FAILURES=0" in phase58_assertions,
    "Phase58 targeted assertions not zero",
)

check(
    "Phase58 no longer recommends returning to Phase59 retirement work",
    "Phase59 should reconcile and retire" not in phase58_next,
    "Phase58 recommendation regressed to Phase59 loop",
)

check(
    "Phase58 digest reports Phase54 stale indicators false",
    "Phase54 stale source/runtime indicators present: False" in phase58_digest,
    "Phase58 digest still reports Phase54 stale indicators",
)

check(
    "Phase58 digest reports Phase54b stale indicators false",
    "Phase54b stale source/runtime indicators present: False" in phase58_digest,
    "Phase58 digest still reports Phase54b stale indicators",
)

# ------------------------------------------------------------------
# Emit assertion report and final closure verdict
# ------------------------------------------------------------------

failed = 0
assertion_lines = ["=== PHASE60 TARGETED CLOSURE ASSERTIONS ==="]

for label, ok, detail in checks:
    if ok:
        assertion_lines.append(f"PASS: {label}")
    else:
        failed += 1
        assertion_lines.append(f"FAIL: {label} — {detail}")

assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "21_targeted_closure_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

closed = failed == 0

verdict_lines = [
    "=== PHASE60 ROUTER CONSOLIDATION CLOSURE VERDICT ===",
    f"ROUTER_CONSOLIDATION_CLOSED={'TRUE' if closed else 'FALSE'}",
    f"TARGETED_ASSERTION_FAILURES={failed}",
    "",
]

if closed:
    verdict_lines.extend([
        "Conclusion:",
        "- The router consolidation sequence is closed.",
        "- The Phase38 flattened canonical dispatcher remains authoritative.",
        "- Public routing surfaces remain canonical and unified.",
        "- No residual pre-Phase38 wrapper-shell routing debt is exposed by Phase45b.",
        "- The Phase54 / Phase54b / Phase58 retirement branch remains cleanly closed.",
        "- No further router-consolidation repair phase is indicated by the current evidence.",
    ])
else:
    verdict_lines.extend([
        "Conclusion:",
        "- Router consolidation cannot yet be formally closed.",
        "- At least one closure condition failed.",
        "- Trust 21_targeted_closure_assertions.txt for the exact remaining blocker(s).",
    ])

verdict_lines.extend([
    "",
    "Review:",
    "- 02_public_surface_identity_probe.txt",
    "- 03_structural_public_router_def_snapshot.txt",
    "- 08_phase36_digest_key_lines.txt",
    "- 14_phase45b_digest_key_lines.txt",
    "- 17_phase58_reconciliation_matrix.txt",
    "- 18_phase58_recommended_next_move.txt",
    "- 21_targeted_closure_assertions.txt",
])

(out / "22_router_consolidation_closure_verdict.txt").write_text(
    "\n".join(verdict_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict_lines))

if not closed:
    raise SystemExit(1)
PY

echo
echo "PHASE60_OUT=$OUT"
