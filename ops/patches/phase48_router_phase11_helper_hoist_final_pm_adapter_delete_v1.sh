#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase48_router_phase11_helper_hoist_final_pm_adapter_delete_${STAMP}"

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

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase48.bak"

PATCH_APPLIED=0

restore_on_failure() {
  local code="$1"
  if [[ "$PATCH_APPLIED" == "1" ]]; then
    echo
    echo "PHASE48 FAILURE DETECTED — restoring router from pre-Phase48 backup." >&2
    cp "$OUT/backups/router_enhanced.py.before_phase48.bak" "$ROUTER"
    python3 -m py_compile "$ROUTER" >/dev/null 2>&1 || true
    echo "ROUTER_RESTORED_AFTER_PHASE48_FAILURE" >&2
  fi
  exit "$code"
}

trap 'restore_on_failure $?' ERR

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 48 — Phase11 Helper Hoist / Final-PM Adapter Delete

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Purpose

Phase47c removed the dead LRF/PM adapter chains and left only:

- 2 residual pre-Phase38 route-capture hits:
  - \`_eli_phase11_prev_route = route\`
  - \`_eli_phase11_prev_route_intent = route_intent\`

- 8 residual public alias rebinding hits, including:
  - \`route_intent = _eli_final_personal_memory_precedence_route_intent\`

The Phase11 block is now retained only because Phase38 directly depends on:

- \`_eli_phase11_enrich_pdf_route\`

This Phase48 patch:

1. Hoists \`_eli_phase11_enrich_pdf_route\` out of the stale Phase11 try/capture shell.
2. Deletes stale Phase11 capture variables.
3. Deletes the no-longer-needed final personal-memory adapter chain:
   - \`_eli_final_pm_previous_route_20260511\`
   - \`_eli_final_personal_memory_precedence_route\`
   - \`_eli_final_pm_previous_route_intent_20260511\`
   - \`_eli_final_personal_memory_precedence_route_intent\`
   - any residual direct \`route\` / \`route_intent\` alias assignments to those helpers.
4. Preserves exact Phase36 semantic baseline equality.
5. Verifies residual capture hits reduce from 2 to 0.
6. Verifies residual alias rebinding hits reduce from 8 to 7.
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
# 2. Source rewrite:
#    - remove final-PM adapter chain
#    - hoist Phase11 helper
#    - delete stale Phase11 captures
# ---------------------------------------------------------------------

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import sys
import textwrap
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
    raise RuntimeError("Phase38 marker not found during Phase48 rewrite")

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def before_marker(node: ast.AST) -> bool:
    s, _ = span(node)
    return 0 < s < marker_line

def assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    def walk_target(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for item in t.elts:
                walk_target(item)

    if isinstance(node, ast.Assign):
        for target in node.targets:
            walk_target(target)
    elif isinstance(node, ast.AnnAssign):
        walk_target(node.target)

    return names

def assigned_value_name(node: ast.AST) -> str:
    if isinstance(node, ast.Assign):
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        value = node.value
    else:
        return ""
    return value.id if isinstance(value, ast.Name) else ""

def try_mentions_name(node: ast.Try, name: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == name:
            return True
    return False

def try_contains_function(node: ast.Try, fn_name: str) -> ast.FunctionDef | None:
    for sub in ast.walk(node):
        if isinstance(sub, ast.FunctionDef) and sub.name == fn_name:
            return sub
    return None

ops: list[tuple[int, int, str, str]] = []
changes: list[str] = []

required_hits = {
    "final_pm_prev_route_try": False,
    "final_pm_route_fn": False,
    "final_pm_prev_route_intent_try": False,
    "final_pm_route_intent_fn": False,
    "final_pm_route_intent_assign": False,
    "phase11_try_replaced": False,
}

optional_hits = {
    "final_pm_route_assign": False,
}

phase11_helper_source: str | None = None

for node in tree.body:
    if not before_marker(node):
        continue

    # -----------------------------------------------------------------
    # Remove final-PM capture tries
    # -----------------------------------------------------------------
    if isinstance(node, ast.Try):
        if try_mentions_name(node, "_eli_final_pm_previous_route_20260511"):
            s, e = span(node)
            ops.append((s, e, "", "remove final-PM previous-route capture Try"))
            changes.append(f"remove final-PM previous-route capture Try lines={s}-{e}")
            required_hits["final_pm_prev_route_try"] = True
            continue

        if try_mentions_name(node, "_eli_final_pm_previous_route_intent_20260511"):
            s, e = span(node)
            ops.append((s, e, "", "remove final-PM previous-route-intent capture Try"))
            changes.append(f"remove final-PM previous-route-intent capture Try lines={s}-{e}")
            required_hits["final_pm_prev_route_intent_try"] = True
            continue

        # -------------------------------------------------------------
        # Replace Phase11 Try shell with top-level helper only
        # -------------------------------------------------------------
        helper = try_contains_function(node, "_eli_phase11_enrich_pdf_route")
        if helper is not None:
            s, e = span(node)
            hs, he = span(helper)

            helper_raw = "".join(lines[hs - 1:he])
            helper_dedented = textwrap.dedent(helper_raw).rstrip() + "\n"

            replacement = (
                "# --- Phase 48: standalone Phase11 multi-PDF enrichment helper -----------\n"
                "# Phase38 flattened dispatch uses this helper directly. The older Phase11\n"
                "# route/route_intent capture shell has been removed as dead pre-marker debt.\n"
                f"{helper_dedented}\n"
            )

            ops.append((s, e, replacement, "replace Phase11 capture shell with helper-only definition"))
            changes.append(
                f"replace Phase11 Try shell with standalone _eli_phase11_enrich_pdf_route helper lines={s}-{e}"
            )
            required_hits["phase11_try_replaced"] = True
            phase11_helper_source = helper_dedented
            continue

    # -----------------------------------------------------------------
    # Remove final-PM helper functions
    # -----------------------------------------------------------------
    if isinstance(node, ast.FunctionDef):
        if node.name == "_eli_final_personal_memory_precedence_route":
            s, e = span(node)
            ops.append((s, e, "", "remove final-PM route adapter helper"))
            changes.append(f"remove final-PM route adapter helper lines={s}-{e}")
            required_hits["final_pm_route_fn"] = True
            continue

        if node.name == "_eli_final_personal_memory_precedence_route_intent":
            s, e = span(node)
            ops.append((s, e, "", "remove final-PM route_intent adapter helper"))
            changes.append(f"remove final-PM route_intent adapter helper lines={s}-{e}")
            required_hits["final_pm_route_intent_fn"] = True
            continue

    # -----------------------------------------------------------------
    # Remove alias assignment(s) to final-PM helpers
    # -----------------------------------------------------------------
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = assigned_names(node)
        value_name = assigned_value_name(node)

        if "route" in targets and value_name == "_eli_final_personal_memory_precedence_route":
            s, e = span(node)
            ops.append((s, e, "", "remove final-PM route alias assignment"))
            changes.append(f"remove final-PM route alias assignment lines={s}-{e}")
            optional_hits["final_pm_route_assign"] = True
            continue

        if "route_intent" in targets and value_name == "_eli_final_personal_memory_precedence_route_intent":
            s, e = span(node)
            ops.append((s, e, "", "remove final-PM route_intent alias assignment"))
            changes.append(f"remove final-PM route_intent alias assignment lines={s}-{e}")
            required_hits["final_pm_route_intent_assign"] = True
            continue

missing = [name for name, seen in required_hits.items() if not seen]
if missing:
    raise RuntimeError(
        "Phase48 missing required rewrite target(s): " + ", ".join(missing)
    )

if phase11_helper_source is None:
    raise RuntimeError("Phase48 did not capture Phase11 helper source for hoist")

# Verify no span overlap.
ops_sorted = sorted(ops, key=lambda x: x[0])
for (s1, e1, _, label1), (s2, e2, _, label2) in zip(ops_sorted, ops_sorted[1:]):
    if s2 <= e1:
        raise RuntimeError(
            f"Overlapping Phase48 rewrite spans: {s1}-{e1} ({label1}) and {s2}-{e2} ({label2})"
        )

# Apply in reverse line order.
for start, end, replacement, _label in sorted(ops, key=lambda x: x[0], reverse=True):
    replacement_lines = replacement.splitlines(keepends=True)
    lines[start - 1:end] = replacement_lines

router_path.write_text("".join(lines), encoding="utf-8")

(out / "05_changes_applied.txt").write_text(
    "\n".join(changes) + "\n",
    encoding="utf-8",
)

(out / "06_optional_rewrite_hits.txt").write_text(
    "\n".join(
        f"{name}={seen}"
        for name, seen in sorted(optional_hits.items())
    ) + "\n",
    encoding="utf-8",
)

(out / "07_phase11_hoisted_helper_snapshot.py.txt").write_text(
    phase11_helper_source,
    encoding="utf-8",
)
PY

PATCH_APPLIED=1

# ---------------------------------------------------------------------
# 3. Compile
# ---------------------------------------------------------------------

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/08_post_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/08_post_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/08_post_compile.txt"

# ---------------------------------------------------------------------
# 4. Post-patch Phase36 semantic baseline
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/09_post_phase36_console.txt"
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

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

pre_path = out / "02_pre_phase36_semantic_baseline.json"
post_path = out / "10_post_phase36_semantic_baseline.json"

pre_raw = pre_path.read_text(encoding="utf-8")
post_raw = post_path.read_text(encoding="utf-8")

pre_json = json.loads(pre_raw)
post_json = json.loads(post_raw)

raw_equal = pre_raw == post_raw
parsed_equal = pre_json == post_json

report = [
    "=== PHASE 48 PHASE36 SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"RAW_JSON_EXACT_EQUAL={raw_equal}",
    f"PARSED_JSON_EQUAL={parsed_equal}",
]

(out / "13_phase36_semantic_compare.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

(out / "14_phase36_semantic_raw_diff_status.txt").write_text(
    "NO_DIFF\n" if raw_equal else "RAW_JSON_DIFF_PRESENT\n",
    encoding="utf-8",
)

print("\n".join(report))

if not raw_equal:
    raise SystemExit("Phase48 failed: raw Phase36 semantic baseline JSON changed")

if not parsed_equal:
    raise SystemExit("Phase48 failed: parsed Phase36 semantic baseline JSON changed")
PY

sleep 1

# ---------------------------------------------------------------------
# 5. Post-patch Phase45b audit
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE45b AUDIT ===" | tee "$OUT/15_post_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/15_post_phase45b_console.txt"

POST45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"

cp "$POST45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/16_post_phase45b_legacy_adapter_inventory.txt"
cp "$POST45B_OUT/08_residual_route_capture_symbol_hits.txt" \
   "$OUT/17_post_phase45b_residual_capture_hits.txt"
cp "$POST45B_OUT/09_residual_public_alias_rebinding_hits.txt" \
   "$OUT/18_post_phase45b_residual_alias_hits.txt"
cp "$POST45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/19_post_phase45b_conclusion.txt"
cp "$POST45B_OUT/12_console_digest.txt" \
   "$OUT/20_post_phase45b_digest.txt"

# ---------------------------------------------------------------------
# 6. Direct runtime helper/surface probe
# ---------------------------------------------------------------------

python3 - "$OUT" <<'PY'
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

probe_lines: list[str] = []
failures: list[str] = []

helper = getattr(router, "_eli_phase11_enrich_pdf_route", None)

probe_lines.append("=== PHASE 48 DIRECT RUNTIME PROBE ===")
probe_lines.append(f"phase11_helper_present={callable(helper)}")

if not callable(helper):
    failures.append("FAIL: _eli_phase11_enrich_pdf_route is not callable")

route = getattr(router, "route", None)
route_intent = getattr(router, "route_intent", None)
route_command = getattr(router, "route_command", None)
parse_command = getattr(router, "parse_command", None)
classify = getattr(router, "classify", None)

surfaces = {
    "route": route,
    "route_intent": route_intent,
    "route_command": route_command,
    "parse_command": parse_command,
    "classify": classify,
}

ids = {name: id(fn) for name, fn in surfaces.items()}
probe_lines.append("surface_ids=" + json.dumps(ids, sort_keys=True))
same_object = len(set(ids.values())) == 1
probe_lines.append(f"all_public_surfaces_same_object={same_object}")

if not same_object:
    failures.append("FAIL: public router surfaces are no longer the same function object")

question = "analyze /tmp/a.pdf and /tmp/b.pdf"
result = route(question) if callable(route) else None
probe_lines.append("multipdf_probe_result=" + json.dumps(result, sort_keys=True, ensure_ascii=False))

paths = []
matched_by = ""
if isinstance(result, dict):
    args = result.get("args") or {}
    meta = result.get("meta") or {}
    if isinstance(args, dict):
        paths = args.get("paths") or []
    if isinstance(meta, dict):
        matched_by = str(meta.get("matched_by") or "")

if paths != ["/tmp/a.pdf", "/tmp/b.pdf"]:
    failures.append(f"FAIL: multi-PDF enrichment paths changed unexpectedly: {paths!r}")

if "phase11_multipdf" not in matched_by:
    failures.append(f"FAIL: multi-PDF matched_by no longer carries phase11_multipdf: {matched_by!r}")

probe_lines.extend(failures or ["DIRECT_RUNTIME_PROBE_PASS"])

(out / "21_direct_runtime_probe.txt").write_text(
    "\n".join(probe_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(probe_lines))

if failures:
    raise SystemExit("Phase48 direct runtime probe failed")
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
    "_eli_final_pm_previous_route_20260511",
    "_eli_final_pm_previous_route_intent_20260511",
    "def _eli_final_personal_memory_precedence_route(",
    "def _eli_final_personal_memory_precedence_route_intent(",
    "route = _eli_final_personal_memory_precedence_route",
    "route_intent = _eli_final_personal_memory_precedence_route_intent",
    "_eli_phase11_prev_route = route",
    "_eli_phase11_prev_route_intent = route_intent",
    "_ELI_PHASE11_MULTIPDF_ROUTE_INSTALLED",
]

must_be_present = [
    "def _eli_phase11_enrich_pdf_route(",
]

assertions: list[str] = []
failures: list[str] = []

for fragment in must_be_absent:
    if fragment in src:
        failures.append(f"FAIL: stale Phase48 residue remains: {fragment}")
    else:
        assertions.append(f"PASS: removed stale Phase48 residue: {fragment}")

for fragment in must_be_present:
    if fragment in src:
        assertions.append(f"PASS: retained required helper surface: {fragment}")
    else:
        failures.append(f"FAIL: required helper surface missing: {fragment}")

digest = (out / "20_post_phase45b_digest.txt").read_text(encoding="utf-8")
capture_hits = (out / "17_post_phase45b_residual_capture_hits.txt").read_text(encoding="utf-8")
alias_hits = (out / "18_post_phase45b_residual_alias_hits.txt").read_text(encoding="utf-8")
inventory = (out / "16_post_phase45b_legacy_adapter_inventory.txt").read_text(encoding="utf-8")

m = re.search(r"Residual route-capture symbol hit lines before Phase38:\s*(\d+)", digest)
digest_capture_count = int(m.group(1)) if m else -1

m = re.search(r"Residual public alias rebinding hit lines before Phase38:\s*(\d+)", digest)
digest_alias_count = int(m.group(1)) if m else -1

m = re.search(r"HIT_LINE_COUNT=(\d+)", capture_hits)
capture_file_count = int(m.group(1)) if m else -1

m = re.search(r"HIT_LINE_COUNT=(\d+)", alias_hits)
alias_file_count = int(m.group(1)) if m else -1

if digest_capture_count == 0 and capture_file_count == 0:
    assertions.append("PASS: residual pre-Phase38 route-capture hit count reduced to 0")
else:
    failures.append(
        f"FAIL: expected residual route-capture hit count 0, "
        f"digest={digest_capture_count}, file={capture_file_count}"
    )

if digest_alias_count == 7 and alias_file_count == 7:
    assertions.append("PASS: residual pre-Phase38 public alias rebinding hit count reduced to 7")
else:
    failures.append(
        f"FAIL: expected residual alias rebinding hit count 7, "
        f"digest={digest_alias_count}, file={alias_file_count}"
    )

# Phase45b inventory is catalogue-style. Rows may persist.
# Correct acceptance rule: absent rows are acceptable; present rows must show no hits.
inventory_rows: dict[str, list[str]] = {}
for line in inventory.splitlines():
    if "|" not in line:
        continue
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 4:
        continue
    group = parts[0]
    if group:
        inventory_rows[group] = parts

for chain in (
    "final_personal_memory_route_adapter",
    "final_personal_memory_route_intent_adapter",
):
    row = inventory_rows.get(chain)
    if row is None:
        assertions.append(f"PASS: {chain} no longer appears in Phase45b catalogue")
        continue

    ast_hits = row[1]
    text_hits = row[2]

    if ast_hits == "-" and text_hits == "-":
        assertions.append(
            f"PASS: {chain} catalogue row retained but source/postmarker hits are clear (- / -)"
        )
    else:
        failures.append(
            f"FAIL: {chain} still reports live hits; ast={ast_hits!r}, text={text_hits!r}"
        )

report = [
    "=== PHASE 48 TARGETED POST-PATCH ASSERTIONS ===",
    *assertions,
]

if failures:
    report.extend(failures)

(out / "22_targeted_post_patch_assertions.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

print("\n".join(report))

if failures:
    raise SystemExit("Phase48 targeted assertions failed")
PY

# ---------------------------------------------------------------------
# 8. Final digest
# ---------------------------------------------------------------------

cat > "$OUT/23_console_digest.txt" <<EOF
=== PHASE 48 DIGEST ===
Router compile: PASS

Phase11 helper hoist:
- standalone _eli_phase11_enrich_pdf_route retained: PASS
- stale Phase11 capture shell removed: PASS
- _eli_phase11_prev_route / _eli_phase11_prev_route_intent captures removed: PASS

Final personal-memory adapter cleanup:
- previous route capture removed: PASS
- previous route_intent capture removed: PASS
- route adapter helper removed: PASS
- route_intent adapter helper removed: PASS
- stale final-PM route_intent alias assignment removed: PASS

Phase36 pre/post raw semantic JSON exact equality: PASS
Phase36 pre/post parsed semantic JSON equality: PASS

Direct runtime probe:
- public router surfaces remain canonical: PASS
- multi-PDF enrichment remains intact: PASS

Post-Phase45b residual debt:
- residual route-capture symbol hit lines before Phase38: 0
- residual public alias rebinding hit lines before Phase38: 7

Phase48 succeeded.

Next target:
- Phase49 should classify and remove or preserve the remaining 7 pre-Phase38
  public alias rebinding lines, especially the stale Phase33 canonical alias shell
  and the earlier route_command / parse_command / classify shell residue.

Review:
- 05_changes_applied.txt
- 06_optional_rewrite_hits.txt
- 07_phase11_hoisted_helper_snapshot.py.txt
- 13_phase36_semantic_compare.txt
- 16_post_phase45b_legacy_adapter_inventory.txt
- 17_post_phase45b_residual_capture_hits.txt
- 18_post_phase45b_residual_alias_hits.txt
- 21_direct_runtime_probe.txt
- 22_targeted_post_patch_assertions.txt

PHASE48_OUT=$OUT
EOF

trap - ERR
PATCH_APPLIED=0

cat "$OUT/23_console_digest.txt"
echo
echo "PHASE48_OUT=$OUT"
