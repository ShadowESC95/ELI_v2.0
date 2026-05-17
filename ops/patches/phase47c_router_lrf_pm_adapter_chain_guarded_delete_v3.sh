#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase47c_router_lrf_pm_adapter_chain_guarded_delete_${STAMP}"

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

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase47c.bak"

PATCH_APPLIED=0

restore_on_failure() {
  local code="$1"
  if [[ "$PATCH_APPLIED" == "1" ]]; then
    echo
    echo "PHASE47C FAILURE DETECTED — restoring router from pre-Phase47c backup." >&2
    cp "$OUT/backups/router_enhanced.py.before_phase47c.bak" "$ROUTER"
    python3 -m py_compile "$ROUTER" >/dev/null 2>&1 || true
    echo "ROUTER_RESTORED_AFTER_PHASE47C_FAILURE" >&2
  fi
  exit "$code"
}

trap 'restore_on_failure $?' ERR

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 47c — Router LRF / PM Legacy Adapter Chain Guarded Delete

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Purpose

Delete only the two now-removable legacy adapter chains:

1. legacy_lrf_adapter_chain
2. legacy_pm_adapter_chain

Explicitly preserve:

- final_personal_memory_route_adapter
- final_personal_memory_route_intent_adapter
- Phase11 multi-PDF route / route_intent capture dependency

## Correction over Phase47b

Phase47b's source mutation was correct, but its final gate falsely expected
Phase45b's static inventory catalogue to stop listing the deleted chain names.

Phase45b continues to list known catalogue groups even after deletion.
The correct post-delete assertion is:

- the row may remain;
- postmarker AST hits must be '-';
- postmarker text hits must be '-';
- source-level LRF / PM adapter symbols must be absent.
EOF

# ---------------------------------------------------------------------
# 1. Pre-patch Phase36 semantic baseline
# ---------------------------------------------------------------------

echo "=== PRE-PATCH PHASE 36 BASELINE ===" | tee "$OUT/01_pre_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/01_pre_phase36_console.txt"

PRE36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"

cp "$PRE36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/02_pre_phase36_semantic_baseline.json"
cp "$PRE36_OUT/06_router_flattening_semantic_baseline_matrix.txt" \
   "$OUT/03_pre_phase36_semantic_baseline_matrix.txt"
cp "$PRE36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/04_pre_phase36_targeted_assertions.txt"

# Avoid timestamp collision with the next Phase36 report directory.
sleep 1

# ---------------------------------------------------------------------
# 2. Delete only LRF + PM legacy adapter chains
# ---------------------------------------------------------------------

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
    raise RuntimeError("Phase38 marker not found during Phase47c AST prune")

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

for node in tree.body:
    if not before_marker(node):
        continue

    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        bound = target_names(node)
        hit = bound & ASSIGN_SYMBOLS_TO_REMOVE
        if hit:
            s, e = span(node)
            label = f"remove legacy capture assignment {', '.join(sorted(hit))} lines={s}-{e}"
            removals.append((s, e, label))
            changes.append(label)
            continue

    if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS_TO_REMOVE:
        s, e = span(node)
        label = f"remove legacy adapter function {node.name} lines={s}-{e}"
        removals.append((s, e, label))
        changes.append(label)
        continue

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

if not removals:
    raise RuntimeError("Phase47c found no removable LRF/PM legacy adapter chain statements")

removals = sorted(set(removals), key=lambda x: x[0])

for (s1, e1, _), (s2, e2, _) in zip(removals, removals[1:]):
    if s2 <= e1:
        raise RuntimeError(f"Overlapping removal spans detected: {s1}-{e1} and {s2}-{e2}")

EXPECTED_REMOVAL_SPANS = 10
if len(removals) != EXPECTED_REMOVAL_SPANS:
    raise RuntimeError(
        f"Expected {EXPECTED_REMOVAL_SPANS} Phase47c removal spans, found {len(removals)}:\n"
        + "\n".join(label for _, _, label in removals)
    )

for start, end, _label in sorted(removals, key=lambda x: x[0], reverse=True):
    del lines[start - 1:end]

router_path.write_text("".join(lines), encoding="utf-8")

(out / "05_changes_applied.txt").write_text(
    "\n".join(changes) + "\n",
    encoding="utf-8",
)

(out / "06_removal_span_manifest.txt").write_text(
    "\n".join(f"{s}-{e}: {label}" for s, e, label in removals) + "\n",
    encoding="utf-8",
)
PY

PATCH_APPLIED=1

# ---------------------------------------------------------------------
# 3. Compile + post-patch Phase36 exact semantic compare
# ---------------------------------------------------------------------

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/07_post_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/07_post_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/07_post_compile.txt"

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/08_post_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/08_post_phase36_console.txt"

POST36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"

cp "$POST36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/09_post_phase36_semantic_baseline.json"
cp "$POST36_OUT/06_router_flattening_semantic_baseline_matrix.txt" \
   "$OUT/10_post_phase36_semantic_baseline_matrix.txt"
cp "$POST36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/11_post_phase36_targeted_assertions.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

pre_path = out / "02_pre_phase36_semantic_baseline.json"
post_path = out / "09_post_phase36_semantic_baseline.json"

pre_raw = pre_path.read_text(encoding="utf-8")
post_raw = post_path.read_text(encoding="utf-8")

pre_json = json.loads(pre_raw)
post_json = json.loads(post_raw)

raw_equal = pre_raw == post_raw
parsed_equal = pre_json == post_json

lines = [
    "=== PHASE 47c PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EXACT_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
]

(out / "12_phase36_semantic_compare.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

(out / "13_phase36_semantic_raw_diff_status.txt").write_text(
    "NO_DIFF\n" if raw_equal else "RAW_JSON_DIFF_PRESENT\n",
    encoding="utf-8",
)

print("\n".join(lines))

if not raw_equal:
    raise SystemExit("Phase47c failed: raw Phase36 semantic baseline JSON changed")

if not parsed_equal:
    raise SystemExit("Phase47c failed: parsed Phase36 semantic baseline JSON changed")
PY

sleep 1

# ---------------------------------------------------------------------
# 4. Post-patch Phase45b residual audit
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE45b AUDIT ===" | tee "$OUT/14_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/14_post_phase45b_console.txt"

POST45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"

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

# ---------------------------------------------------------------------
# 5. Corrected targeted assertions
# ---------------------------------------------------------------------

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

router = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router.read_text(encoding="utf-8")

forbidden_removed = [
    "_ELI_LRF_ORIG_ROUTE =",
    "_ELI_LRF_ORIG_ROUTE_INTENT =",
    "def _eli_lrf_route(",
    "def _eli_lrf_route_intent(",
    "_ELI_PM_ORIG_ROUTE =",
    "_ELI_PM_ORIG_ROUTE_INTENT =",
    "def _eli_pm_route(",
    "def _eli_pm_route_intent(",
]

must_remain = [
    "_eli_final_pm_previous_route_20260511",
    "_eli_final_pm_previous_route_intent_20260511",
    "def _eli_final_personal_memory_precedence_route(",
    "def _eli_final_personal_memory_precedence_route_intent(",
    "_eli_phase11_prev_route = route",
    "_eli_phase11_prev_route_intent = route_intent",
]

assertions: list[str] = []
failures: list[str] = []

for fragment in forbidden_removed:
    if fragment in src:
        failures.append(f"FAIL: LRF/PM adapter residue remains: {fragment}")
    else:
        assertions.append(f"PASS: removed LRF/PM adapter residue: {fragment}")

for fragment in must_remain:
    if fragment in src:
        assertions.append(f"PASS: required Phase11/final-PM dependency retained: {fragment}")
    else:
        failures.append(f"FAIL: required Phase11/final-PM dependency missing: {fragment}")

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

if digest_alias_count == 8 and alias_file_count == 8:
    assertions.append("PASS: residual public alias rebinding hit count reduced to 8")
else:
    failures.append(
        f"FAIL: expected residual public alias rebinding hit count 8, "
        f"digest={digest_alias_count}, file={alias_file_count}"
    )

# Correct Phase47b mistake:
# Phase45b's inventory is a static catalogue. The chain rows may remain.
# What matters is that these rows now show no postmarker AST/text hits.
inventory_rows: dict[str, list[str]] = {}

for line in adapter_inventory.splitlines():
    if "|" not in line:
        continue
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 4:
        continue
    group = parts[0]
    if group:
        inventory_rows[group] = parts

for chain in (
    "legacy_lrf_adapter_chain",
    "legacy_pm_adapter_chain",
):
    row = inventory_rows.get(chain)
    if row is None:
        failures.append(f"FAIL: Phase45b catalogue row missing unexpectedly: {chain}")
        continue

    ast_hits = row[1]
    text_hits = row[2]

    if ast_hits == "-" and text_hits == "-":
        assertions.append(
            f"PASS: {chain} catalogue row retained but source/postmarker hits are clear (- / -)"
        )
    else:
        failures.append(
            f"FAIL: {chain} still has inventory hits; ast={ast_hits!r}, text={text_hits!r}"
        )

for chain in (
    "final_personal_memory_route_adapter",
    "final_personal_memory_route_intent_adapter",
):
    row = inventory_rows.get(chain)
    if row is None:
        failures.append(f"FAIL: retained deferred final-PM adapter catalogue row missing: {chain}")
        continue

    ast_hits = row[1]
    text_hits = row[2]

    if ast_hits == "-" and text_hits == "-":
        assertions.append(
            f"PASS: retained deferred chain remains catalogue-classified with no postmarker hits: {chain}"
        )
    else:
        failures.append(
            f"FAIL: retained deferred chain inventory row unexpectedly carries hits; "
            f"{chain}: ast={ast_hits!r}, text={text_hits!r}"
        )

report = [
    "=== PHASE 47c TARGETED POST-PATCH ASSERTIONS ===",
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
    raise SystemExit("Phase47c targeted post-patch assertions failed")
PY

cat > "$OUT/21_console_digest.txt" <<EOF
=== PHASE 47c DIGEST ===
Router compile: PASS
LRF / PM legacy adapter-chain guarded deletion: PASS
Deleted unique top-level adapter-chain statements: 10

Phase36 pre/post raw semantic JSON exact equality: PASS
Phase36 pre/post parsed semantic JSON equality: PASS

Post-Phase45b residual debt:
- residual route-capture symbol hit lines before Phase38: 2
- residual public alias rebinding hit lines before Phase38: 8
- deleted adapter chains:
  - legacy_lrf_adapter_chain
  - legacy_pm_adapter_chain
- intentionally retained deferred chains:
  - final_personal_memory_route_adapter
  - final_personal_memory_route_intent_adapter

Acceptance-gate correction:
- Phase45b inventory rows are catalogue rows, not live-source existence checks.
- Deleted LRF / PM adapter groups may remain listed there.
- The correct proof is:
  - source symbols absent,
  - postmarker AST hits = '-',
  - postmarker text hits = '-'.

Phase47c succeeded.

Next target:
- Phase48 should rewire or absorb the Phase11 multi-PDF enrichment dependency so the
  final personal-memory route / route_intent adapter pair can be removed safely.

Review:
- 05_changes_applied.txt
- 06_removal_span_manifest.txt
- 12_phase36_semantic_compare.txt
- 15_post_phase45b_legacy_adapter_inventory.txt
- 16_post_phase45b_residual_capture_hits.txt
- 17_post_phase45b_residual_alias_hits.txt
- 20_targeted_post_patch_assertions.txt

PHASE47C_OUT=$OUT
EOF

trap - ERR
PATCH_APPLIED=0

cat "$OUT/21_console_digest.txt"
echo
echo "PHASE47C_OUT=$OUT"
