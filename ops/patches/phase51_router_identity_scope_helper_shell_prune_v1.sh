#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase51_router_identity_scope_helper_shell_prune_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"
PHASE51_MARKER="ELI_PHASE51_IDENTITY_SCOPE_HELPER_SHELL_PRUNE_V1"

mkdir -p "$OUT/backups"

for f in "$ROUTER" "$PHASE36_SCRIPT" "$PHASE45B_SCRIPT"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Missing Phase38 marker in router: $PHASE38_MARKER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase51.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 51 — Router Identity-Scope Helper Shell Prune

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase50 v2 proved that exactly one remaining mixed pre-Phase38 Try block is
mechanically splittable:

- helper: \`_eli_identity_scope_for_text\`
- shell residue: obsolete non-live statements inside the old Try container

Phase51:

1. Finds the exact pre-Phase38 Try block containing
   \`_eli_identity_scope_for_text\`.
2. Verifies that the helper does not depend on the dead shell assignment
   \`_ELI_IDENTITY_SCOPE_PREV_ROUTE\`.
3. Replaces the full obsolete Try shell with the standalone helper function.
4. Verifies:
   - router compilation;
   - exact Phase36 semantic JSON equality;
   - public route surface identity;
   - multi-PDF enrichment;
   - identity-scope behaviour;
   - Phase45b residual mixed-block count reduction from 7 to 6;
   - mechanically splittable mixed-block count reduction from 1 to 0.
EOF

# ---------------------------------------------------------------------
# 1. Pre-patch Phase36 golden semantic baseline
# ---------------------------------------------------------------------

echo "=== PRE-PATCH PHASE36 BASELINE ===" | tee "$OUT/00_pre_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/00_pre_phase36_console.txt"

PRE36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"
cp "$PRE36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/01_pre_phase36_semantic_baseline.json"
cp "$PRE36_OUT/06_router_flattening_semantic_baseline_matrix.txt" \
   "$OUT/02_pre_phase36_semantic_baseline_matrix.txt"
cp "$PRE36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/03_pre_phase36_targeted_assertions.txt"

# ---------------------------------------------------------------------
# 2. Patch router: replace single mixed Try helper shell with standalone helper
# ---------------------------------------------------------------------

python3 - "$ROUTER" "$OUT" "$PHASE51_MARKER" <<'PY'
from __future__ import annotations

import ast
import difflib
import sys
import textwrap
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])
marker = sys.argv[3]

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

if marker in src:
    raise SystemExit(f"Phase51 marker already present: {marker}")

tree = ast.parse(src)

phase38_marker_line = None
for idx, line in enumerate(src.splitlines(), start=1):
    if "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1" in line:
        phase38_marker_line = idx
        break

if phase38_marker_line is None:
    raise RuntimeError("Could not locate Phase38 marker line")

target_try: ast.Try | None = None
target_helper: ast.FunctionDef | ast.AsyncFunctionDef | None = None
candidate_count = 0

for node in ast.walk(tree):
    if not isinstance(node, ast.Try):
        continue

    start = getattr(node, "lineno", 10**9)
    if start >= phase38_marker_line:
        continue

    helpers = [
        stmt
        for stmt in node.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
        and stmt.name == "_eli_identity_scope_for_text"
    ]

    if helpers:
        candidate_count += 1
        target_try = node
        target_helper = helpers[0]

if candidate_count != 1 or target_try is None or target_helper is None:
    raise RuntimeError(
        f"Expected exactly 1 pre-Phase38 Try block containing "
        f"_eli_identity_scope_for_text; found {candidate_count}"
    )

try_start = target_try.lineno
try_end = target_try.end_lineno
helper_start = target_helper.lineno
helper_end = target_helper.end_lineno

try_text = "".join(lines[try_start - 1:try_end])
helper_text_indented = "".join(lines[helper_start - 1:helper_end])
helper_text = textwrap.dedent(helper_text_indented).rstrip() + "\n"

if "_ELI_IDENTITY_SCOPE_PREV_ROUTE" in helper_text:
    raise RuntimeError(
        "_eli_identity_scope_for_text unexpectedly depends on "
        "_ELI_IDENTITY_SCOPE_PREV_ROUTE; refusing prune"
    )

body_stmt_count = len(target_try.body)
helper_stmt_count = sum(
    1 for stmt in target_try.body
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    and stmt.name == "_eli_identity_scope_for_text"
)
non_helper_body_count = body_stmt_count - helper_stmt_count

if helper_stmt_count != 1:
    raise RuntimeError(
        f"Expected exactly 1 target helper statement; found {helper_stmt_count}"
    )

if non_helper_body_count != 2:
    raise RuntimeError(
        f"Expected exactly 2 removable non-helper body statements in the Phase51 "
        f"Try block; found {non_helper_body_count}"
    )

replacement = (
    f"# {marker}\n"
    "# Standalone helper retained from the obsolete identity-scope Try shell.\n"
    f"{helper_text}"
)

new_lines = (
    lines[:try_start - 1]
    + [replacement]
    + lines[try_end:]
)
new_src = "".join(new_lines)

if new_src == src:
    raise RuntimeError("Patch produced no source change")

router_path.write_text(new_src, encoding="utf-8")

(out / "04_target_try_shell_before.txt").write_text(
    try_text,
    encoding="utf-8",
)
(out / "05_preserved_helper_after.txt").write_text(
    replacement,
    encoding="utf-8",
)

changes = [
    "replace pre-Phase38 mixed Try shell containing _eli_identity_scope_for_text "
    f"lines={try_start}-{try_end}",
    "preserve standalone _eli_identity_scope_for_text helper",
    f"remove obsolete non-helper body statements count={non_helper_body_count}",
    f"insert marker={marker}",
]
(out / "06_changes_applied.txt").write_text(
    "\n".join(changes) + "\n",
    encoding="utf-8",
)

diff = "".join(
    difflib.unified_diff(
        src.splitlines(keepends=True),
        new_src.splitlines(keepends=True),
        fromfile="router_enhanced.py.before_phase51",
        tofile="router_enhanced.py.after_phase51",
    )
)
(out / "07_phase51_source_diff.patch").write_text(diff, encoding="utf-8")

print("=== PHASE 51 PATCH APPLIED ===")
for change in changes:
    print(change)
PY

# ---------------------------------------------------------------------
# 3. Compile router after patch
# ---------------------------------------------------------------------

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/08_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/08_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/08_compile.txt"

# ---------------------------------------------------------------------
# 4. Post-patch Phase36 baseline and exact semantic compare
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE36 BASELINE ===" | tee "$OUT/09_post_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/09_post_phase36_console.txt"

POST36_OUT="$(ls -td ops/reports/phase36_router_flattening_semantic_baseline_v2_* | head -1)"
cp "$POST36_OUT/05_router_flattening_semantic_baseline.json" \
   "$OUT/10_post_phase36_semantic_baseline.json"
cp "$POST36_OUT/06_router_flattening_semantic_baseline_matrix.txt" \
   "$OUT/11_post_phase36_semantic_baseline_matrix.txt"
cp "$POST36_OUT/07_targeted_baseline_assertions.txt" \
   "$OUT/12_post_phase36_targeted_assertions.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

pre_path = out / "01_pre_phase36_semantic_baseline.json"
post_path = out / "10_post_phase36_semantic_baseline.json"

pre_raw = pre_path.read_text(encoding="utf-8")
post_raw = post_path.read_text(encoding="utf-8")

pre_json = json.loads(pre_raw)
post_json = json.loads(post_raw)

raw_equal = pre_raw == post_raw
parsed_equal = pre_json == post_json

report = [
    "=== PHASE 51 PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EXACT_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
]

diff = "".join(
    difflib.unified_diff(
        pre_raw.splitlines(keepends=True),
        post_raw.splitlines(keepends=True),
        fromfile=str(pre_path),
        tofile=str(post_path),
    )
)

(out / "13_phase36_semantic_compare.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)
(out / "14_phase36_semantic_diff.txt").write_text(
    diff if diff else "NO_DIFF\n",
    encoding="utf-8",
)

print("\n".join(report))

if not raw_equal or not parsed_equal:
    raise SystemExit("Phase51 semantic baseline comparison failed")
PY

# ---------------------------------------------------------------------
# 5. Refresh Phase45b audit after prune
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE45b AUDIT ===" | tee "$OUT/15_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/15_post_phase45b_console.txt"

POST45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"

cp "$POST45B_OUT/02_mixed_tryblock_liveness_matrix.txt" \
   "$OUT/16_post_phase45b_mixed_tryblock_liveness_matrix.txt"
cp "$POST45B_OUT/03_preserve_substatement_manifest.txt" \
   "$OUT/17_post_phase45b_preserve_manifest.txt"
cp "$POST45B_OUT/04_remove_candidate_substatement_manifest.txt" \
   "$OUT/18_post_phase45b_remove_candidate_manifest.txt"
cp "$POST45B_OUT/08_residual_route_capture_symbol_hits.txt" \
   "$OUT/19_post_phase45b_residual_capture_hits.txt"
cp "$POST45B_OUT/09_residual_public_alias_rebinding_hits.txt" \
   "$OUT/20_post_phase45b_residual_alias_hits.txt"
cp "$POST45B_OUT/10_runtime_public_surface_identity_probe.txt" \
   "$OUT/21_post_phase45b_runtime_public_surface_identity_probe.txt"
cp "$POST45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/22_post_phase45b_conclusion.txt"
cp "$POST45B_OUT/12_console_digest.txt" \
   "$OUT/23_post_phase45b_digest.txt"

# ---------------------------------------------------------------------
# 6. Direct runtime probe: surfaces, multi-PDF, identity-scope behaviour
# ---------------------------------------------------------------------

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

lines: list[str] = ["=== PHASE 51 DIRECT RUNTIME PROBE ==="]
failures: list[str] = []

surfaces = {
    "route": getattr(router, "route", None),
    "route_intent": getattr(router, "route_intent", None),
    "route_command": getattr(router, "route_command", None),
    "parse_command": getattr(router, "parse_command", None),
    "classify": getattr(router, "classify", None),
}

surface_ids = {name: id(fn) for name, fn in surfaces.items()}
same_surface = len(set(surface_ids.values())) == 1

lines.append("surface_ids=" + json.dumps(surface_ids, sort_keys=True))
lines.append(f"all_public_surfaces_same_object={same_surface}")

if not same_surface:
    failures.append("FAIL: public router surfaces are not the same live function object")

route = surfaces["route"]
if not callable(route):
    failures.append("FAIL: route is not callable")
else:
    multipdf = route("analyze /tmp/a.pdf and /tmp/b.pdf")
    lines.append("multipdf_probe_result=" + json.dumps(multipdf, sort_keys=True, ensure_ascii=False))

    if not isinstance(multipdf, dict):
        failures.append("FAIL: multi-PDF probe did not return a dict")
    else:
        args = multipdf.get("args") or {}
        meta = multipdf.get("meta") or {}

        if args.get("paths") != ["/tmp/a.pdf", "/tmp/b.pdf"]:
            failures.append(f"FAIL: multi-PDF paths changed unexpectedly: {args.get('paths')!r}")

        matched_by = str(meta.get("matched_by") or "")
        if "phase11_multipdf" not in matched_by:
            failures.append(f"FAIL: multi-PDF matched_by lost phase11 tag: {matched_by!r}")

    identity = route("Who am I?")
    lines.append("identity_scope_probe_result=" + json.dumps(identity, sort_keys=True, ensure_ascii=False))

    if not isinstance(identity, dict):
        failures.append("FAIL: identity scope probe did not return a dict")
    else:
        action = str(identity.get("action") or "")
        args = identity.get("args") or {}
        meta = identity.get("meta") or {}

        if action != "USER_IDENTITY_SUMMARY":
            failures.append(f"FAIL: identity probe action changed unexpectedly: {action!r}")

        scope = args.get("identity_scope")
        meta_scope = meta.get("identity_scope_contract")

        if scope != "identity_only":
            failures.append(f"FAIL: identity_scope changed unexpectedly: {scope!r}")

        if meta_scope != "identity_only":
            failures.append(f"FAIL: identity_scope_contract changed unexpectedly: {meta_scope!r}")

if failures:
    lines.extend(failures)
else:
    lines.append("DIRECT_RUNTIME_PROBE_PASS")

(out / "24_direct_runtime_probe.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print("\n".join(lines))

if failures:
    raise SystemExit("Phase51 direct runtime probe failed")
PY

# ---------------------------------------------------------------------
# 7. Targeted assertions
# ---------------------------------------------------------------------

python3 - "$OUT" "$ROUTER" "$PHASE51_MARKER" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
router = Path(sys.argv[2])
marker = sys.argv[3]

router_text = router.read_text(encoding="utf-8")
phase45b_digest = (out / "23_post_phase45b_digest.txt").read_text(encoding="utf-8")
phase45b_matrix = (out / "16_post_phase45b_mixed_tryblock_liveness_matrix.txt").read_text(encoding="utf-8")
capture_hits = (out / "19_post_phase45b_residual_capture_hits.txt").read_text(encoding="utf-8")
alias_hits = (out / "20_post_phase45b_residual_alias_hits.txt").read_text(encoding="utf-8")

lines = ["=== PHASE 51 TARGETED POST-PATCH ASSERTIONS ==="]
failures: list[str] = []

def expect(condition: bool, ok: str, bad: str) -> None:
    if condition:
        lines.append(f"PASS: {ok}")
    else:
        lines.append(f"FAIL: {bad}")
        failures.append(bad)

expect(
    marker in router_text,
    f"Phase51 marker present: {marker}",
    f"Phase51 marker missing: {marker}",
)

expect(
    "def _eli_identity_scope_for_text" in router_text,
    "standalone _eli_identity_scope_for_text helper retained",
    "_eli_identity_scope_for_text helper missing after prune",
)

expect(
    "_ELI_IDENTITY_SCOPE_PREV_ROUTE = route" not in router_text,
    "obsolete _ELI_IDENTITY_SCOPE_PREV_ROUTE route-capture assignment absent",
    "obsolete _ELI_IDENTITY_SCOPE_PREV_ROUTE route-capture assignment still present",
)

expect(
    "Mixed pre-Phase38 Try blocks with post-marker live binds: 6" in phase45b_digest,
    "Phase45b mixed Try-block count reduced from 7 to 6",
    "Phase45b mixed Try-block count did not reduce to 6",
)

expect(
    "Mechanically splittable mixed blocks: 0" in phase45b_digest,
    "Phase45b mechanically splittable mixed-block count reduced from 1 to 0",
    "Phase45b mechanically splittable mixed-block count did not reduce to 0",
)

expect(
    "Residual route-capture symbol hit lines before Phase38: 0" in phase45b_digest,
    "residual route-capture hit count remains 0",
    "residual route-capture hit count is no longer 0",
)

expect(
    "Residual public alias rebinding hit lines before Phase38: 0" in phase45b_digest,
    "residual public alias rebinding hit count remains 0",
    "residual public alias rebinding hit count is no longer 0",
)

expect(
    "_eli_identity_scope_for_text" not in phase45b_matrix,
    "identity-scope helper Try block no longer appears in mixed Try-block matrix",
    "identity-scope helper still appears in mixed Try-block matrix",
)

expect(
    "HIT_LINE_COUNT=0" in capture_hits,
    "post-Phase45b residual capture-hit manifest remains zero",
    "post-Phase45b residual capture-hit manifest is non-zero",
)

expect(
    "HIT_LINE_COUNT=0" in alias_hits,
    "post-Phase45b residual alias-hit manifest remains zero",
    "post-Phase45b residual alias-hit manifest is non-zero",
)

if failures:
    lines.append("PHASE51_ASSERTIONS_FAILED")
else:
    lines.append("PHASE51_TARGETED_ASSERTIONS_PASS")

(out / "25_targeted_post_patch_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print("\n".join(lines))

if failures:
    raise SystemExit("Phase51 targeted assertions failed")
PY

# ---------------------------------------------------------------------
# 8. Final digest
# ---------------------------------------------------------------------

python3 - "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

out = Path(sys.argv[1])

digest = f"""=== PHASE 51 DIGEST ===
Router compile: PASS

Identity-scope helper mixed-shell prune:
- preserved standalone _eli_identity_scope_for_text helper: PASS
- removed obsolete pre-Phase38 mixed Try shell: PASS
- removed stale _ELI_IDENTITY_SCOPE_PREV_ROUTE route-capture residue: PASS

Phase36 semantic lock:
- pre/post raw semantic JSON exact equality: PASS
- pre/post parsed semantic JSON equality: PASS

Direct runtime probe:
- public router surfaces remain canonical: PASS
- multi-PDF enrichment remains intact: PASS
- USER_IDENTITY_SUMMARY identity_scope contract remains intact: PASS

Post-Phase45b residual debt:
- mixed pre-Phase38 Try blocks with post-marker live binds: 6
- mechanically splittable mixed blocks: 0
- residual route-capture hit lines before Phase38: 0
- residual public alias rebinding hit lines before Phase38: 0

Phase51 succeeded.

Interpretation:
- The only mechanically splittable helper/shell block identified by Phase50 v2
  is now removed.
- The remaining 6 mixed pre-Phase38 Try blocks are helper-hosting live blocks
  that Phase45b does not classify as mechanically splittable.
- The next pass should be an audit/planning phase for those 6 retained helper
  containers: determine whether each should be hoisted cleanly as a whole or
  retained until a broader helper-normalisation pass.

Review:
- 06_changes_applied.txt
- 07_phase51_source_diff.patch
- 13_phase36_semantic_compare.txt
- 14_phase36_semantic_diff.txt
- 23_post_phase45b_digest.txt
- 24_direct_runtime_probe.txt
- 25_targeted_post_patch_assertions.txt

PHASE51_OUT={out}
"""

(out / "26_console_digest.txt").write_text(digest, encoding="utf-8")
print(digest)
PY

echo
echo "PHASE51_OUT=$OUT"
