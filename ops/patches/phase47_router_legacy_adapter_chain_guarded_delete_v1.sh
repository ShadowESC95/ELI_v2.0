#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase47_router_legacy_adapter_chain_guarded_delete_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT/backups"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if [[ ! -x "$PHASE36_SCRIPT" ]]; then
  echo "Missing or non-executable Phase36 baseline script: $PHASE36_SCRIPT" >&2
  exit 1
fi

if [[ ! -x "$PHASE45B_SCRIPT" ]]; then
  echo "Missing or non-executable Phase45b audit script: $PHASE45B_SCRIPT" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Missing Phase38 marker: $PHASE38_MARKER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase47.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 47 — Router Legacy Adapter Chain Guarded Delete

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase45b classified four pre-Phase38 legacy adapter chains as having no
post-marker AST/text liveness:

1. legacy_lrf_adapter_chain
2. legacy_pm_adapter_chain
3. final_personal_memory_route_adapter
4. final_personal_memory_route_intent_adapter

Phase47 deletes those adapter chains only if:

- all expected source statements are located structurally;
- exactly the expected removal span count is found;
- router compilation still passes;
- Phase36 pre/post raw semantic JSON is exactly equal;
- Phase36 parsed semantic JSON is exactly equal;
- Phase45b residual debt drops in the expected direction.

## Expected unique top-level deletion spans

- LRF chain: 5
- PM chain: 5
- Final personal-memory route/intent cluster: 6

Total expected removal spans: 16
EOF

echo "=== PRE-PATCH PHASE 36 BASELINE ===" | tee "$OUT/00_pre_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/00_pre_phase36_console.txt"

PRE36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"
cp "$PRE36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/01_pre_phase36_semantic_baseline.json"
cp "$PRE36_OUT/06_router_flattening_semantic_baseline_matrix.txt" \
   "$OUT/02_pre_phase36_semantic_baseline_matrix.txt"
cp "$PRE36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/03_pre_phase36_targeted_assertions.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)
tree = ast.parse(src)

marker_line = None
for i, line in enumerate(src.splitlines(), start=1):
    if "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1" in line:
        marker_line = i
        break

if marker_line is None:
    raise RuntimeError("Phase38 marker not found during AST prune")

removals: list[tuple[int, int, str]] = []
changes: list[str] = []

ASSIGN_SYMBOLS_TO_REMOVE = {
    "_ELI_LRF_ORIG_ROUTE",
    "_ELI_LRF_ORIG_ROUTE_INTENT",
    "_ELI_PM_ORIG_ROUTE",
    "_ELI_PM_ORIG_ROUTE_INTENT",
}

FUNCTIONS_TO_REMOVE = {
    "_eli_lrf_route",
    "_eli_lrf_route_intent",
    "_eli_pm_route",
    "_eli_pm_route_intent",
    "_eli_final_personal_memory_precedence_route",
    "_eli_final_personal_memory_precedence_route_intent",
}

FINAL_CAPTURE_TRY_SYMBOLS = {
    "_eli_final_pm_previous_route_20260511",
    "_eli_final_pm_previous_route_intent_20260511",
}

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def before_marker(node: ast.AST) -> bool:
    s, _ = span(node)
    return 0 < s < marker_line

def target_names(node: ast.AST) -> set[str]:
    found: set[str] = set()

    def walk_target(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            found.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for item in t.elts:
                walk_target(item)

    if isinstance(node, ast.Assign):
        for target in node.targets:
            walk_target(target)
    elif isinstance(node, ast.AnnAssign):
        walk_target(node.target)

    return found

def assign_value_name(node: ast.AST) -> str:
    if isinstance(node, ast.Assign):
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        value = node.value
    else:
        return ""
    return value.id if isinstance(value, ast.Name) else ""

def try_binds_any(node: ast.Try, names: set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Assign, ast.AnnAssign)):
            if target_names(sub) & names:
                return True
    return False

def try_rebinds_legacy_route_pair(node: ast.Try, helper_route: str, helper_intent: str) -> bool:
    saw_route = False
    saw_intent = False

    for sub in ast.walk(node):
        if not isinstance(sub, (ast.Assign, ast.AnnAssign)):
            continue

        targets = target_names(sub)
        value_name = assign_value_name(sub)

        if "route" in targets and value_name == helper_route:
            saw_route = True
        if "route_intent" in targets and value_name == helper_intent:
            saw_intent = True

    return saw_route and saw_intent

def direct_assign_matches(node: ast.AST, target: str, value: str) -> bool:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return False
    return target in target_names(node) and assign_value_name(node) == value

for node in tree.body:
    if not before_marker(node):
        continue

    # 1. Direct legacy captured-route assignments.
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        bound = target_names(node)
        hit = bound & ASSIGN_SYMBOLS_TO_REMOVE
        if hit:
            s, e = span(node)
            label = f"remove legacy capture assignment {', '.join(sorted(hit))} lines={s}-{e}"
            removals.append((s, e, label))
            changes.append(label)
            continue

        if direct_assign_matches(node, "route", "_eli_final_personal_memory_precedence_route"):
            s, e = span(node)
            label = f"remove final personal-memory route alias assignment lines={s}-{e}"
            removals.append((s, e, label))
            changes.append(label)
            continue

        if direct_assign_matches(node, "route_intent", "_eli_final_personal_memory_precedence_route_intent"):
            s, e = span(node)
            label = f"remove final personal-memory route_intent alias assignment lines={s}-{e}"
            removals.append((s, e, label))
            changes.append(label)
            continue

    # 2. Legacy adapter functions.
    if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS_TO_REMOVE:
        s, e = span(node)
        label = f"remove legacy/final adapter function {node.name} lines={s}-{e}"
        removals.append((s, e, label))
        changes.append(label)
        continue

    # 3. Legacy adapter try-block rebindings.
    if isinstance(node, ast.Try):
        if try_rebinds_legacy_route_pair(node, "_eli_lrf_route", "_eli_lrf_route_intent"):
            s, e = span(node)
            label = f"remove legacy LRF route/route_intent adapter Try block lines={s}-{e}"
            removals.append((s, e, label))
            changes.append(label)
            continue

        if try_rebinds_legacy_route_pair(node, "_eli_pm_route", "_eli_pm_route_intent"):
            s, e = span(node)
            label = f"remove legacy PM route/route_intent adapter Try block lines={s}-{e}"
            removals.append((s, e, label))
            changes.append(label)
            continue

        if try_binds_any(node, FINAL_CAPTURE_TRY_SYMBOLS):
            bound_final = set()
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    bound_final |= target_names(sub) & FINAL_CAPTURE_TRY_SYMBOLS
            if bound_final:
                s, e = span(node)
                label = (
                    "remove final personal-memory previous-route capture Try block "
                    f"{', '.join(sorted(bound_final))} lines={s}-{e}"
                )
                removals.append((s, e, label))
                changes.append(label)
                continue

if not removals:
    raise RuntimeError("Phase47 found no removable legacy adapter chain statements")

# Deduplicate / overlap guard.
removals = sorted(set(removals), key=lambda x: x[0])

for (s1, e1, _), (s2, e2, _) in zip(removals, removals[1:]):
    if s2 <= e1:
        raise RuntimeError(f"Overlapping removal spans detected: {s1}-{e1} and {s2}-{e2}")

EXPECTED_REMOVAL_SPANS = 16
if len(removals) != EXPECTED_REMOVAL_SPANS:
    raise RuntimeError(
        f"Expected {EXPECTED_REMOVAL_SPANS} Phase47 removal spans, found {len(removals)}:\n"
        + "\n".join(label for _, _, label in removals)
    )

# Delete bottom-up to preserve line coordinates.
for start, end, _label in sorted(removals, key=lambda x: x[0], reverse=True):
    del lines[start - 1:end]

new_src = "".join(lines)
router_path.write_text(new_src, encoding="utf-8")

(out / "04_changes_applied.txt").write_text(
    "\n".join(changes) + "\n",
    encoding="utf-8",
)

(out / "05_removal_span_manifest.txt").write_text(
    "\n".join(f"{s}-{e}: {label}" for s, e, label in removals) + "\n",
    encoding="utf-8",
)
PY

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/06_post_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/06_post_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/06_post_compile.txt"

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/07_post_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/07_post_phase36_console.txt"

POST36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"
cp "$POST36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/08_post_phase36_semantic_baseline.json"
cp "$POST36_OUT/06_router_flattening_semantic_baseline_matrix.txt" \
   "$OUT/09_post_phase36_semantic_baseline_matrix.txt"
cp "$POST36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/10_post_phase36_targeted_assertions.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

pre_path = out / "01_pre_phase36_semantic_baseline.json"
post_path = out / "08_post_phase36_semantic_baseline.json"

pre_raw = pre_path.read_text(encoding="utf-8")
post_raw = post_path.read_text(encoding="utf-8")

pre_json = json.loads(pre_raw)
post_json = json.loads(post_raw)

raw_equal = pre_raw == post_raw
parsed_equal = pre_json == post_json

compare_lines = [
    "=== PHASE 47 PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EXACT_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
]

(out / "11_phase36_semantic_compare.txt").write_text(
    "\n".join(compare_lines) + "\n",
    encoding="utf-8",
)

(out / "12_phase36_semantic_raw_diff_status.txt").write_text(
    "NO_DIFF\n" if raw_equal else "RAW_JSON_DIFF_PRESENT\n",
    encoding="utf-8",
)

print("\n".join(compare_lines))

if not raw_equal:
    raise SystemExit("Phase47 failed: raw Phase36 semantic baseline JSON changed")

if not parsed_equal:
    raise SystemExit("Phase47 failed: parsed Phase36 semantic baseline JSON changed")
PY

echo "=== POST-PATCH PHASE45b AUDIT ===" | tee "$OUT/13_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/13_post_phase45b_console.txt"

POST45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"
cp "$POST45B_OUT/02_mixed_tryblock_liveness_matrix.txt" \
   "$OUT/14_post_phase45b_mixed_tryblock_liveness_matrix.txt"
cp "$POST45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/15_post_phase45b_legacy_adapter_inventory.txt"
cp "$POST45B_OUT/08_residual_route_capture_symbol_hits.txt" \
   "$OUT/16_post_phase45b_residual_capture_hits.txt"
cp "$POST45B_OUT/09_residual_public_alias_rebinding_hits.txt" \
   "$OUT/17_post_phase45b_residual_alias_hits.txt"
cp "$POST45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/18_post_phase45b_conclusion.txt"
cp "$POST45B_OUT/12_console_digest.txt" \
   "$OUT/19_post_phase45b_digest.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

router = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router.read_text(encoding="utf-8")

forbidden_fragments = [
    "_ELI_LRF_ORIG_ROUTE =",
    "_ELI_LRF_ORIG_ROUTE_INTENT =",
    "def _eli_lrf_route(",
    "def _eli_lrf_route_intent(",
    "route = _eli_lrf_route",
    "route_intent = _eli_lrf_route_intent",
    "_ELI_PM_ORIG_ROUTE =",
    "_ELI_PM_ORIG_ROUTE_INTENT =",
    "def _eli_pm_route(",
    "def _eli_pm_route_intent(",
    "route = _eli_pm_route",
    "route_intent = _eli_pm_route_intent",
    "_eli_final_pm_previous_route_20260511",
    "_eli_final_pm_previous_route_intent_20260511",
    "def _eli_final_personal_memory_precedence_route(",
    "def _eli_final_personal_memory_precedence_route_intent(",
    "route = _eli_final_personal_memory_precedence_route",
    "route_intent = _eli_final_personal_memory_precedence_route_intent",
]

assertions: list[str] = []
failures: list[str] = []

for fragment in forbidden_fragments:
    if fragment in src:
        failures.append(f"FAIL: forbidden adapter-chain residue remains: {fragment}")
    else:
        assertions.append(f"PASS: removed adapter-chain residue: {fragment}")

digest = (out / "19_post_phase45b_digest.txt").read_text(encoding="utf-8")
capture_hits = (out / "16_post_phase45b_residual_capture_hits.txt").read_text(encoding="utf-8")
alias_hits = (out / "17_post_phase45b_residual_alias_hits.txt").read_text(encoding="utf-8")
adapter_inventory = (out / "15_post_phase45b_legacy_adapter_inventory.txt").read_text(encoding="utf-8")

m = re.search(r"Residual route-capture symbol hit lines before Phase38:\s*(\d+)", digest)
digest_capture_count = int(m.group(1)) if m else -1

m = re.search(r"Residual public alias rebinding hit lines before Phase38:\s*(\d+)", digest)
digest_alias_count = int(m.group(1)) if m else -1

m = re.search(r"HIT_LINE_COUNT=(\d+)", capture_hits)
capture_file_count = int(m.group(1)) if m else -1

m = re.search(r"HIT_LINE_COUNT=(\d+)", alias_hits)
alias_file_count = int(m.group(1)) if m else -1

if digest_capture_count == 2 and capture_file_count == 2:
    assertions.append("PASS: residual route-capture hit count reduced to 2")
else:
    failures.append(
        f"FAIL: expected residual route-capture hit count 2, "
        f"digest={digest_capture_count}, file={capture_file_count}"
    )

if digest_alias_count == 7 and alias_file_count == 7:
    assertions.append("PASS: residual public alias rebinding hit count reduced to 7")
else:
    failures.append(
        f"FAIL: expected residual public alias rebinding hit count 7, "
        f"digest={digest_alias_count}, file={alias_file_count}"
    )

for chain in (
    "legacy_lrf_adapter_chain",
    "legacy_pm_adapter_chain",
    "final_personal_memory_route_adapter",
    "final_personal_memory_route_intent_adapter",
):
    if chain in adapter_inventory:
        failures.append(f"FAIL: Phase45b legacy adapter inventory still reports {chain}")
    else:
        assertions.append(f"PASS: Phase45b legacy adapter inventory no longer reports {chain}")

report_lines = [
    "=== PHASE 47 TARGETED POST-PATCH ASSERTIONS ===",
    *assertions,
]
if failures:
    report_lines.extend(failures)

(out / "20_targeted_post_patch_assertions.txt").write_text(
    "\n".join(report_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(report_lines))

if failures:
    raise SystemExit("Phase47 targeted post-patch assertions failed")
PY

cat > "$OUT/21_console_digest.txt" <<EOF
=== PHASE 47 DIGEST ===
Router compile: PASS
Legacy adapter-chain guarded deletion: PASS
Deleted unique top-level adapter-chain statements: 16

Phase36 pre/post raw semantic JSON exact equality: PASS
Phase36 pre/post parsed semantic JSON equality: PASS

Post-Phase45b residual debt:
- legacy adapter guarded-delete candidate chains: 0 expected / removed from inventory
- residual route-capture symbol hit lines before Phase38: 2
- residual public alias rebinding hit lines before Phase38: 7

Phase47 succeeded.

What remains after Phase47:
- the Phase11 multi-PDF capture pair:
  - _eli_phase11_prev_route = route
  - _eli_phase11_prev_route_intent = route_intent
- retained non-mechanically-splittable helper/surface blocks, especially:
  - block 69 identity-scope / public alias bridge
  - block 82 Phase11 multi-PDF wrapper helper
  - block 83 Phase33 final canonical public-surface rebinding
- Phase48 should audit whether the remaining two Phase11 prev-route captures are still required or can be replaced by direct flattened-dispatch wiring without semantic change.

Review:
- 04_changes_applied.txt
- 05_removal_span_manifest.txt
- 11_phase36_semantic_compare.txt
- 15_post_phase45b_legacy_adapter_inventory.txt
- 16_post_phase45b_residual_capture_hits.txt
- 17_post_phase45b_residual_alias_hits.txt
- 20_targeted_post_patch_assertions.txt

PHASE47_OUT=$OUT
EOF

cat "$OUT/21_console_digest.txt"
echo
echo "PHASE47_OUT=$OUT"
