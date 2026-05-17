#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase49_router_residual_public_alias_rebinding_guarded_delete_${STAMP}"

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
  echo "Missing or non-executable Phase36 script: $PHASE36_SCRIPT" >&2
  exit 1
fi

if [[ ! -x "$PHASE45B_SCRIPT" ]]; then
  echo "Missing or non-executable Phase45b script: $PHASE45B_SCRIPT" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Missing required Phase38 marker: $PHASE38_MARKER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase49.bak"

PATCH_APPLIED=0

restore_on_failure() {
  local code="$1"
  if [[ "$PATCH_APPLIED" == "1" ]]; then
    echo
    echo "PHASE49 FAILURE DETECTED — restoring router from pre-Phase49 backup." >&2
    cp "$OUT/backups/router_enhanced.py.before_phase49.bak" "$ROUTER"
    python3 -m py_compile "$ROUTER" >/dev/null 2>&1 || true
    echo "ROUTER_RESTORED_AFTER_PHASE49_FAILURE" >&2
  fi
  exit "$code"
}

trap 'restore_on_failure $?' ERR

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 49 — Residual Public Alias Rebinding Guarded Delete

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair purpose

Phase48 eliminated all residual pre-Phase38 route-capture hits and reduced
residual public alias rebinding hits to exactly 7:

- \`route_command = route\`
- \`parse_command = route\`
- \`classify = route\`
- \`route_intent = _ELI_PHASE33_FINAL_CANONICAL_ROUTE\`
- \`route_command = _ELI_PHASE33_FINAL_CANONICAL_ROUTE\`
- \`parse_command = _ELI_PHASE33_FINAL_CANONICAL_ROUTE\`
- \`classify = _ELI_PHASE33_FINAL_CANONICAL_ROUTE\`

Phase38 already installs the final canonical public routing surface after these
legacy pre-marker assignments. Phase49 therefore performs a guarded delete of
only those 7 residual alias-rebinding statements.

Acceptance gates:

1. Router compiles after deletion.
2. Phase36 raw semantic baseline JSON remains exactly equal.
3. Phase36 parsed semantic baseline remains equal.
4. Public router surfaces remain canonical at runtime.
5. Multi-PDF enrichment remains intact.
6. Phase45b residual route-capture hit count remains 0.
7. Phase45b residual public alias rebinding hit count becomes 0.
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

sleep 1

# ---------------------------------------------------------------------
# 2. Remove exactly the 7 residual pre-Phase38 alias rebinding assignments
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
    raise RuntimeError("Phase38 marker not found during Phase49 rewrite")

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def before_marker(node: ast.AST) -> bool:
    s, _ = span(node)
    return 0 < s < marker_line

def target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return ""

def assignment_signature(node: ast.AST) -> tuple[str, str] | None:
    if not isinstance(node, ast.Assign):
        return None

    if len(node.targets) != 1:
        return None

    left = target_name(node.targets[0])
    right = target_name(node.value)

    if not left or not right:
        return None

    return left, right

expected = {
    ("route_command", "route"),
    ("parse_command", "route"),
    ("classify", "route"),
    ("route_intent", "_ELI_PHASE33_FINAL_CANONICAL_ROUTE"),
    ("route_command", "_ELI_PHASE33_FINAL_CANONICAL_ROUTE"),
    ("parse_command", "_ELI_PHASE33_FINAL_CANONICAL_ROUTE"),
    ("classify", "_ELI_PHASE33_FINAL_CANONICAL_ROUTE"),
}

found: list[tuple[int, int, str, str]] = []

for node in ast.walk(tree):
    if not before_marker(node):
        continue

    sig = assignment_signature(node)
    if sig in expected:
        s, e = span(node)
        found.append((s, e, sig[0], sig[1]))

found_sigs = {(left, right) for _, _, left, right in found}

missing = expected - found_sigs
unexpected_duplicate_count = len(found) != len(expected)

if missing:
    raise RuntimeError(
        "Phase49 missing expected residual alias assignment(s): "
        + ", ".join(f"{l}={r}" for l, r in sorted(missing))
    )

if unexpected_duplicate_count:
    raise RuntimeError(
        f"Phase49 expected exactly {len(expected)} matching alias assignments, found {len(found)}"
    )

# Ensure spans do not overlap.
found_sorted = sorted(found, key=lambda row: row[0])
for (s1, e1, _, _), (s2, e2, _, _) in zip(found_sorted, found_sorted[1:]):
    if s2 <= e1:
        raise RuntimeError(f"Overlapping alias assignment spans: {s1}-{e1} and {s2}-{e2}")

changes: list[str] = []
for start, end, left, right in sorted(found, key=lambda row: row[0], reverse=True):
    lines[start - 1:end] = []
    changes.append(f"remove alias rebinding {left} = {right} lines={start}-{end}")

router_path.write_text("".join(lines), encoding="utf-8")

(out / "05_changes_applied.txt").write_text(
    "\n".join(reversed(changes)) + "\n",
    encoding="utf-8",
)

(out / "06_removed_alias_assignment_manifest.txt").write_text(
    "\n".join(
        f"{left} = {right} lines={start}-{end}"
        for start, end, left, right in found_sorted
    ) + "\n",
    encoding="utf-8",
)
PY

PATCH_APPLIED=1

# ---------------------------------------------------------------------
# 3. Compile
# ---------------------------------------------------------------------

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/07_post_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/07_post_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/07_post_compile.txt"

# ---------------------------------------------------------------------
# 4. Post-patch Phase36 semantic baseline
# ---------------------------------------------------------------------

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

report = [
    "=== PHASE 49 PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EXACT_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
]

(out / "12_phase36_semantic_compare.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

(out / "13_phase36_semantic_raw_diff_status.txt").write_text(
    "NO_DIFF\n" if raw_equal else "RAW_JSON_DIFF_PRESENT\n",
    encoding="utf-8",
)

print("\n".join(report))

if not raw_equal:
    raise SystemExit("Phase49 failed: raw Phase36 semantic baseline JSON changed")

if not parsed_equal:
    raise SystemExit("Phase49 failed: parsed Phase36 semantic baseline JSON changed")
PY

sleep 1

# ---------------------------------------------------------------------
# 5. Post-patch Phase45b audit
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE45b AUDIT ===" | tee "$OUT/14_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/14_post_phase45b_console.txt"

POST45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"

cp "$POST45B_OUT/08_residual_route_capture_symbol_hits.txt" \
   "$OUT/15_post_phase45b_residual_capture_hits.txt"
cp "$POST45B_OUT/09_residual_public_alias_rebinding_hits.txt" \
   "$OUT/16_post_phase45b_residual_alias_hits.txt"
cp "$POST45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/17_post_phase45b_conclusion.txt"
cp "$POST45B_OUT/12_console_digest.txt" \
   "$OUT/18_post_phase45b_digest.txt"

# ---------------------------------------------------------------------
# 6. Direct runtime probe
# ---------------------------------------------------------------------

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

report: list[str] = ["=== PHASE 49 DIRECT RUNTIME PROBE ==="]
failures: list[str] = []

surfaces = {
    "route": getattr(router, "route", None),
    "route_intent": getattr(router, "route_intent", None),
    "route_command": getattr(router, "route_command", None),
    "parse_command": getattr(router, "parse_command", None),
    "classify": getattr(router, "classify", None),
}

ids = {name: id(fn) for name, fn in surfaces.items()}
same_object = len(set(ids.values())) == 1

report.append("surface_ids=" + json.dumps(ids, sort_keys=True))
report.append(f"all_public_surfaces_same_object={same_object}")

if not same_object:
    failures.append("FAIL: public routing surfaces are no longer canonical")

route = surfaces["route"]
if not callable(route):
    failures.append("FAIL: route is not callable")
    multipdf_result = None
else:
    multipdf_result = route("analyze /tmp/a.pdf and /tmp/b.pdf")

report.append(
    "multipdf_probe_result="
    + json.dumps(multipdf_result, sort_keys=True, ensure_ascii=False)
)

paths = []
matched_by = ""

if isinstance(multipdf_result, dict):
    args = multipdf_result.get("args") or {}
    meta = multipdf_result.get("meta") or {}
    if isinstance(args, dict):
        paths = args.get("paths") or []
    if isinstance(meta, dict):
        matched_by = str(meta.get("matched_by") or "")

if paths != ["/tmp/a.pdf", "/tmp/b.pdf"]:
    failures.append(f"FAIL: multi-PDF paths changed unexpectedly: {paths!r}")

if "phase11_multipdf" not in matched_by:
    failures.append(f"FAIL: multi-PDF matched_by lost phase11 enrichment tag: {matched_by!r}")

report.extend(failures or ["DIRECT_RUNTIME_PROBE_PASS"])

(out / "19_direct_runtime_probe.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

print("\n".join(report))

if failures:
    raise SystemExit("Phase49 direct runtime probe failed")
PY

# ---------------------------------------------------------------------
# 7. Targeted post-patch assertions
# ---------------------------------------------------------------------

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")

must_be_absent = [
    "route_command = route",
    "parse_command = route",
    "classify = route",
    "route_intent = _ELI_PHASE33_FINAL_CANONICAL_ROUTE",
    "route_command = _ELI_PHASE33_FINAL_CANONICAL_ROUTE",
    "parse_command = _ELI_PHASE33_FINAL_CANONICAL_ROUTE",
    "classify = _ELI_PHASE33_FINAL_CANONICAL_ROUTE",
]

assertions: list[str] = []
failures: list[str] = []

for fragment in must_be_absent:
    if fragment in src:
        failures.append(f"FAIL: stale public alias rebinding remains: {fragment}")
    else:
        assertions.append(f"PASS: removed residual public alias rebinding: {fragment}")

capture_hits = (out / "15_post_phase45b_residual_capture_hits.txt").read_text(encoding="utf-8")
alias_hits = (out / "16_post_phase45b_residual_alias_hits.txt").read_text(encoding="utf-8")
digest = (out / "18_post_phase45b_digest.txt").read_text(encoding="utf-8")

m = re.search(r"HIT_LINE_COUNT=(\d+)", capture_hits)
capture_hit_count = int(m.group(1)) if m else -1

m = re.search(r"HIT_LINE_COUNT=(\d+)", alias_hits)
alias_hit_count = int(m.group(1)) if m else -1

m = re.search(r"Residual route-capture symbol hit lines before Phase38:\s*(\d+)", digest)
digest_capture_hit_count = int(m.group(1)) if m else -1

m = re.search(r"Residual public alias rebinding hit lines before Phase38:\s*(\d+)", digest)
digest_alias_hit_count = int(m.group(1)) if m else -1

if capture_hit_count == 0 and digest_capture_hit_count == 0:
    assertions.append("PASS: residual route-capture hit count remains 0")
else:
    failures.append(
        f"FAIL: residual route-capture hit count changed unexpectedly; "
        f"file={capture_hit_count}, digest={digest_capture_hit_count}"
    )

if alias_hit_count == 0 and digest_alias_hit_count == 0:
    assertions.append("PASS: residual public alias rebinding hit count reduced to 0")
else:
    failures.append(
        f"FAIL: expected residual public alias rebinding hit count 0; "
        f"file={alias_hit_count}, digest={digest_alias_hit_count}"
    )

report = [
    "=== PHASE 49 TARGETED POST-PATCH ASSERTIONS ===",
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
    raise SystemExit("Phase49 targeted assertions failed")
PY

# ---------------------------------------------------------------------
# 8. Final digest
# ---------------------------------------------------------------------

cat > "$OUT/21_console_digest.txt" <<EOF
=== PHASE 49 DIGEST ===
Router compile: PASS

Residual public alias rebinding guarded delete:
- removed old route_command = route shell residue: PASS
- removed old parse_command = route shell residue: PASS
- removed old classify = route shell residue: PASS
- removed stale Phase33 route_intent canonical alias residue: PASS
- removed stale Phase33 route_command canonical alias residue: PASS
- removed stale Phase33 parse_command canonical alias residue: PASS
- removed stale Phase33 classify canonical alias residue: PASS

Phase36 pre/post raw semantic JSON exact equality: PASS
Phase36 pre/post parsed semantic JSON equality: PASS

Direct runtime probe:
- public router surfaces remain canonical: PASS
- multi-PDF enrichment remains intact: PASS

Post-Phase45b residual debt:
- residual route-capture symbol hit lines before Phase38: 0
- residual public alias rebinding hit lines before Phase38: 0

Phase49 succeeded.

Interpretation:
- The pre-Phase38 router wrapper/capture cleanup frontier is now materially closed
  for the two debt classes Phase45b has been tracking:
  - route-capture symbol residue: 0
  - public alias rebinding residue: 0
- The remaining Phase45b "mixed pre-Phase38 Try blocks with post-marker live binds"
  count should now be treated as helper-hosting structural debt, not public router
  surface rebinding debt.

Next target:
- Phase50 should audit the 8 remaining mixed pre-Phase38 Try blocks and classify
  which are:
  1. helper-hosting blocks that should be hoisted into clean standalone helpers;
  2. shell-only blocks that can be deleted;
  3. blocks that are still dependency-coupled to the Phase38 flattened dispatcher.

Review:
- 05_changes_applied.txt
- 06_removed_alias_assignment_manifest.txt
- 12_phase36_semantic_compare.txt
- 15_post_phase45b_residual_capture_hits.txt
- 16_post_phase45b_residual_alias_hits.txt
- 19_direct_runtime_probe.txt
- 20_targeted_post_patch_assertions.txt

PHASE49_OUT=$OUT
EOF

trap - ERR
PATCH_APPLIED=0

cat "$OUT/21_console_digest.txt"
echo
echo "PHASE49_OUT=$OUT"
