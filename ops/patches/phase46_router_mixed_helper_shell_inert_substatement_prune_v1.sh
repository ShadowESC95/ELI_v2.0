#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase46_router_mixed_helper_shell_inert_substatement_prune_${STAMP}"

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

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase46.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 46 — Router Mixed Helper/Shell Inert Substatement Prune

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase 45b identified six mechanically splittable pre-Phase38 helper-hosting
Try blocks. Their helper functions remain live to the Phase38 flattened
canonical dispatcher, but certain shell/capture substatements inside those
blocks are inert.

Phase 46 removes only those inert substatements while preserving:

- all live helper functions;
- the enclosing Try/except failure-policy structure;
- Phase38 canonical dispatch behaviour;
- Phase36 semantic baseline exactness.

## Intended deletion surface

1. _ELI_PROFILE_SCOPE_ROUTE_PREV = route
2. _ELI_MEMORY_COUNT_GROUNDED_ROUTE_PREV = route
3. _ELI_RECENT_MEMORY_ROUTE_PREV = route
4. import re as _eli_self_report_re
5. _ELI_SELF_REPORT_RECENT_UPDATES_PREV_ROUTE = route
6. _ELI_GUI_AUDIT_ACTUAL_SCAN_PREV_ROUTE_V2 = route
7. _ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE = route
8. dead route_intent previous-route capture If block
9. dead route_command previous-route capture If block
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

removal_targets: list[tuple[int, int, str]] = []
changes: list[str] = []

SIMPLE_ASSIGN_TARGETS = {
    "_ELI_PROFILE_SCOPE_ROUTE_PREV",
    "_ELI_MEMORY_COUNT_GROUNDED_ROUTE_PREV",
    "_ELI_RECENT_MEMORY_ROUTE_PREV",
    "_ELI_SELF_REPORT_RECENT_UPDATES_PREV_ROUTE",
    "_ELI_GUI_AUDIT_ACTUAL_SCAN_PREV_ROUTE_V2",
    "_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE",
}

def node_span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def assign_bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    def visit_target(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                visit_target(item)

    if isinstance(node, ast.Assign):
        for target in node.targets:
            visit_target(target)
    elif isinstance(node, ast.AnnAssign):
        visit_target(node.target)

    return names

def if_assigns_exact_name(node: ast.If, wanted: str) -> bool:
    for child in node.body:
        if isinstance(child, ast.Assign):
            if wanted in assign_bound_names(child):
                return True
        if isinstance(child, ast.AnnAssign):
            if wanted in assign_bound_names(child):
                return True
    return False

for top in tree.body:
    if not isinstance(top, ast.Try):
        continue

    # Only prune child statements within top-level Try blocks.
    for child in top.body:
        # Remove targeted assignments.
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            bound = assign_bound_names(child)
            hit = bound & SIMPLE_ASSIGN_TARGETS
            if hit:
                s, e = node_span(child)
                label = f"remove assignment {', '.join(sorted(hit))} lines={s}-{e}"
                removal_targets.append((s, e, label))
                changes.append(label)
                continue

        # Remove dead self-report import alias.
        if isinstance(child, ast.Import):
            for alias in child.names:
                if alias.name == "re" and alias.asname == "_eli_self_report_re":
                    s, e = node_span(child)
                    label = f"remove unused import re as _eli_self_report_re lines={s}-{e}"
                    removal_targets.append((s, e, label))
                    changes.append(label)
                    break

        # Remove exact dead route_intent / route_command capture If blocks.
        if isinstance(child, ast.If):
            if if_assigns_exact_name(child, "_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_INTENT"):
                s, e = node_span(child)
                label = (
                    "remove dead route_intent previous-route capture If block "
                    f"lines={s}-{e}"
                )
                removal_targets.append((s, e, label))
                changes.append(label)
                continue

            if if_assigns_exact_name(child, "_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_COMMAND"):
                s, e = node_span(child)
                label = (
                    "remove dead route_command previous-route capture If block "
                    f"lines={s}-{e}"
                )
                removal_targets.append((s, e, label))
                changes.append(label)
                continue

if not removal_targets:
    raise RuntimeError("Phase46 found no removable mixed helper/shell substatements")

# Deduplicate and detect overlaps.
removal_targets = sorted(set(removal_targets), key=lambda item: item[0])
for (s1, e1, _), (s2, e2, _) in zip(removal_targets, removal_targets[1:]):
    if s2 <= e1:
        raise RuntimeError(f"Overlapping removal spans detected: {s1}-{e1} and {s2}-{e2}")

# Enforce exact expected deletion count.
EXPECTED = 9
if len(removal_targets) != EXPECTED:
    raise RuntimeError(
        f"Expected {EXPECTED} Phase46 removal spans, found {len(removal_targets)}: "
        + "; ".join(label for _, _, label in removal_targets)
    )

# Delete bottom-up by source lines.
for start, end, _label in sorted(removal_targets, key=lambda item: item[0], reverse=True):
    del lines[start - 1:end]

new_src = "".join(lines)
router_path.write_text(new_src, encoding="utf-8")

(out / "04_changes_applied.txt").write_text(
    "\n".join(changes) + "\n",
    encoding="utf-8",
)

(out / "05_removal_span_manifest.txt").write_text(
    "\n".join(
        f"{start}-{end}: {label}"
        for start, end, label in removal_targets
    ) + "\n",
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

diff_text = "NO_DIFF\n" if raw_equal else "RAW_JSON_DIFF_PRESENT\n"
(out / "11_phase36_semantic_raw_diff_status.txt").write_text(diff_text, encoding="utf-8")

compare = [
    "=== PHASE 46 PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EXACT_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
]

(out / "12_phase36_semantic_compare.txt").write_text(
    "\n".join(compare) + "\n",
    encoding="utf-8",
)

if not raw_equal:
    raise SystemExit("Phase46 failed: raw Phase36 semantic baseline JSON changed")
if not parsed_equal:
    raise SystemExit("Phase46 failed: parsed Phase36 semantic baseline JSON changed")

print("\n".join(compare))
PY

echo "=== POST-PATCH PHASE45b AUDIT ===" | tee "$OUT/13_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/13_post_phase45b_console.txt"

POST45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"
cp "$POST45B_OUT/02_mixed_tryblock_liveness_matrix.txt" \
   "$OUT/14_post_phase45b_mixed_tryblock_liveness_matrix.txt"
cp "$POST45B_OUT/04_remove_candidate_substatement_manifest.txt" \
   "$OUT/15_post_phase45b_remove_candidate_manifest.txt"
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

forbidden_strings = [
    "_ELI_PROFILE_SCOPE_ROUTE_PREV = route",
    "_ELI_MEMORY_COUNT_GROUNDED_ROUTE_PREV = route",
    "_ELI_RECENT_MEMORY_ROUTE_PREV = route",
    "import re as _eli_self_report_re",
    "_ELI_SELF_REPORT_RECENT_UPDATES_PREV_ROUTE = route",
    "_ELI_GUI_AUDIT_ACTUAL_SCAN_PREV_ROUTE_V2 = route",
    "_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE = route",
    "_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_INTENT = route_intent",
    "_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_COMMAND = route_command",
]

assertions: list[str] = []
failures: list[str] = []

for needle in forbidden_strings:
    if needle in src:
        failures.append(f"FAIL: forbidden residual remains: {needle}")
    else:
        assertions.append(f"PASS: removed residual: {needle}")

post45b_digest = (out / "19_post_phase45b_digest.txt").read_text(encoding="utf-8")
if "Mechanically splittable mixed blocks: 0" in post45b_digest:
    assertions.append("PASS: post-Phase45b mechanically splittable mixed blocks reduced to 0")
else:
    failures.append("FAIL: post-Phase45b mechanically splittable mixed blocks did not reduce to 0")

capture_hits = (out / "16_post_phase45b_residual_capture_hits.txt").read_text(encoding="utf-8")
m = re.search(r"HIT_LINE_COUNT=(\d+)", capture_hits)
capture_count = int(m.group(1)) if m else -1
if capture_count == 12:
    assertions.append("PASS: residual route-capture hit count reduced to 12")
else:
    failures.append(f"FAIL: expected residual route-capture hit count 12, found {capture_count}")

alias_hits = (out / "17_post_phase45b_residual_alias_hits.txt").read_text(encoding="utf-8")
m = re.search(r"HIT_LINE_COUNT=(\d+)", alias_hits)
alias_count = int(m.group(1)) if m else -1
if alias_count == 10:
    assertions.append("PASS: residual public alias rebinding hit count remains 10 as expected")
else:
    failures.append(f"FAIL: expected residual public alias rebinding hit count 10, found {alias_count}")

report = [
    "=== PHASE 46 TARGETED POST-PATCH ASSERTIONS ===",
    *assertions,
]
if failures:
    report.extend(failures)

(out / "20_targeted_post_patch_assertions.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

print("\n".join(report))

if failures:
    raise SystemExit("Phase46 targeted post-patch assertions failed")
PY

cat > "$OUT/21_console_digest.txt" <<EOF
=== PHASE 46 DIGEST ===
Router compile: PASS
Targeted inert mixed helper/shell substatement prune: PASS
Deleted mixed-block inert substatements: 9

Phase36 pre/post raw semantic JSON exact equality: PASS
Phase36 pre/post parsed semantic JSON equality: PASS

Post-Phase45b confirmation:
- mechanically splittable mixed blocks reduced to: 0
- residual route-capture hit lines reduced to: 12
- residual public alias rebinding hit lines remain: 10

Phase46 succeeded.

What remains:
- 5 non-mechanically-splittable retained/helper/surface blocks;
- 4 legacy adapter chains classified by Phase45b as probable guarded-delete candidates;
- Phase47 should be a guarded exact-semantic deletion pass for those legacy adapter chains, not another mixed helper split.

Review:
- 04_changes_applied.txt
- 05_removal_span_manifest.txt
- 12_phase36_semantic_compare.txt
- 14_post_phase45b_mixed_tryblock_liveness_matrix.txt
- 15_post_phase45b_remove_candidate_manifest.txt
- 16_post_phase45b_residual_capture_hits.txt
- 17_post_phase45b_residual_alias_hits.txt
- 20_targeted_post_patch_assertions.txt

PHASE46_OUT=$OUT
EOF

cat "$OUT/21_console_digest.txt"
echo
echo "PHASE46_OUT=$OUT"
