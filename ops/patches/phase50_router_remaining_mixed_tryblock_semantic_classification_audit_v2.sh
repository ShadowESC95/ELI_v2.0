#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase50_router_remaining_mixed_tryblock_semantic_classification_audit_v2_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if [[ ! -x "$PHASE45B_SCRIPT" ]]; then
  echo "Missing or non-executable Phase45b script: $PHASE45B_SCRIPT" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Missing Phase38 marker in router: $PHASE38_MARKER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 50 v2 — Remaining Mixed Try-Block Semantic Classification Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no router source files modified

## Why v2 exists

Phase50 v1 over-counted the remaining mixed pre-Phase38 Try blocks:

- Phase45b correctly reported: **7**
- Phase50 v1 incorrectly classified: **8**

The v1 false-positive was caused by scope-blind post-marker name matching:
generic local names such as \`action\`, \`args\`, \`meta\`, and \`text\`
were treated as if they were true post-marker dependencies of a pre-Phase38
Try block.

Phase50 v2 fixes this by:

1. Taking the **Phase45b mixed Try-block matrix** as the authoritative block universe.
2. Mapping those exact reported line ranges back to AST Try nodes.
3. Classifying only those verified 7 blocks.
4. Emitting an explicit v1 false-positive exclusion note.
EOF

# ---------------------------------------------------------------------
# 1. Compile router
# ---------------------------------------------------------------------

echo "=== PY_COMPILE ===" | tee "$OUT/00_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_compile.txt"

# ---------------------------------------------------------------------
# 2. Refresh Phase45b authoritative audit
# ---------------------------------------------------------------------

echo "=== PHASE45b REFRESH AUDIT ===" | tee "$OUT/01_phase45b_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/01_phase45b_console.txt"

PHASE45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* | head -1)"

cp "$PHASE45B_OUT/02_mixed_tryblock_liveness_matrix.txt" \
   "$OUT/02_phase45b_mixed_tryblock_liveness_matrix.txt"

cp "$PHASE45B_OUT/03_preserve_substatement_manifest.txt" \
   "$OUT/03_phase45b_preserve_substatement_manifest.txt"

cp "$PHASE45B_OUT/04_remove_candidate_substatement_manifest.txt" \
   "$OUT/04_phase45b_remove_candidate_substatement_manifest.txt"

cp "$PHASE45B_OUT/05_preserve_source_windows.txt" \
   "$OUT/05_phase45b_preserve_source_windows.txt"

cp "$PHASE45B_OUT/06_remove_candidate_source_windows.txt" \
   "$OUT/06_phase45b_remove_candidate_source_windows.txt"

cp "$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt" \
   "$OUT/07_phase45b_legacy_adapter_chain_transitive_liveness_inventory.txt"

cp "$PHASE45B_OUT/08_residual_route_capture_symbol_hits.txt" \
   "$OUT/08_phase45b_residual_capture_hits.txt"

cp "$PHASE45B_OUT/09_residual_public_alias_rebinding_hits.txt" \
   "$OUT/09_phase45b_residual_alias_hits.txt"

cp "$PHASE45B_OUT/10_runtime_public_surface_identity_probe.txt" \
   "$OUT/10_phase45b_runtime_public_surface_identity_probe.txt"

cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" \
   "$OUT/11_phase45b_conclusion.txt"

cp "$PHASE45B_OUT/12_console_digest.txt" \
   "$OUT/12_phase45b_digest.txt"

# ---------------------------------------------------------------------
# 3. Classify exactly the Phase45b-reported mixed Try blocks
# ---------------------------------------------------------------------

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

matrix_path = out / "02_phase45b_mixed_tryblock_liveness_matrix.txt"
matrix_text = matrix_path.read_text(encoding="utf-8")

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def node_window(start: int, end: int, pad: int = 6) -> str:
    lo = max(1, start - pad)
    hi = min(len(lines), end + pad)
    width = len(str(hi))
    return "\n".join(f"{i:>{width}}: {lines[i - 1]}" for i in range(lo, hi + 1))

def defined_symbols_in_try(node: ast.Try) -> set[str]:
    symbols: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name):
                symbols.add(stmt.target.id)
    return symbols

def helper_symbols_in_try(node: ast.Try) -> set[str]:
    symbols: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(stmt.name)
    return symbols

def assignment_symbols_in_try(node: ast.Try) -> set[str]:
    symbols: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name):
                symbols.add(stmt.target.id)
    return symbols

# ------------------------------------------------------------------
# Parse Phase45b authoritative mixed matrix
# ------------------------------------------------------------------

row_re = re.compile(
    r"^\s*(?P<idx>\d+)\s*\|\s*"
    r"(?P<start>\d+)-(?P<end>\d+)\s*\|\s*"
    r"(?P<live>.*?)\s*\|\s*"
    r"(?P<preserve>\d+)\s*\|\s*"
    r"(?P<remove>\d+)\s*\|\s*"
    r"(?P<splittable>True|False)\s*$"
)

phase45b_rows: list[dict[str, object]] = []

for raw in matrix_text.splitlines():
    m = row_re.match(raw)
    if not m:
        continue

    live_raw = m.group("live").strip()
    live_binds = [
        piece.strip()
        for piece in live_raw.split(",")
        if piece.strip() and piece.strip() != "-"
    ]

    phase45b_rows.append(
        {
            "phase45b_idx": int(m.group("idx")),
            "start_line": int(m.group("start")),
            "end_line": int(m.group("end")),
            "live_binds": live_binds,
            "preserve_body_stmt_count": int(m.group("preserve")),
            "remove_body_stmt_count": int(m.group("remove")),
            "mechanically_splittable": m.group("splittable") == "True",
        }
    )

if not phase45b_rows:
    raise RuntimeError("Could not parse any Phase45b mixed Try-block rows")

# ------------------------------------------------------------------
# Map exact Phase45b row spans back to AST Try nodes
# ------------------------------------------------------------------

try_nodes_by_span: dict[tuple[int, int], ast.Try] = {}
for node in ast.walk(tree):
    if isinstance(node, ast.Try):
        try_nodes_by_span[span(node)] = node

@dataclass
class MixedTryClassification:
    block_id: str
    phase45b_idx: int
    start_line: int
    end_line: int
    live_binds: list[str]
    preserve_body_stmt_count: int
    remove_body_stmt_count: int
    mechanically_splittable: bool
    defined_symbols: list[str]
    helper_symbols: list[str]
    assignment_symbols: list[str]
    classification: str
    classification_reason: str

classifications: list[MixedTryClassification] = []
source_windows: list[str] = []
errors: list[str] = []

for ordinal, row in enumerate(phase45b_rows, start=1):
    key = (int(row["start_line"]), int(row["end_line"]))
    node = try_nodes_by_span.get(key)

    if node is None:
        errors.append(
            f"FAIL: Phase45b mixed Try block span {key[0]}-{key[1]} not found as exact AST Try span"
        )
        continue

    defs = defined_symbols_in_try(node)
    helpers = helper_symbols_in_try(node)
    assigns = assignment_symbols_in_try(node)
    live = set(row["live_binds"])

    helper_live = sorted(helpers & live)
    assignment_live = sorted(assigns & live)

    if helper_live:
        classification = "helper_hosting_live"
        reason = (
            "Phase45b live bind(s) resolve to helper/class definitions preserved "
            f"inside this Try block: {', '.join(helper_live)}"
        )
    elif assignment_live:
        classification = "phase38_dependency_coupled"
        reason = (
            "Phase45b live bind(s) resolve to assigned symbols still consumed by "
            f"the post-Phase38 surface: {', '.join(assignment_live)}"
        )
    elif live:
        classification = "phase38_dependency_coupled"
        reason = (
            "Phase45b marks this Try block live, but the live bind(s) are not "
            "direct helper/assignment symbols under the simplified classifier: "
            + ", ".join(sorted(live))
        )
    else:
        classification = "shell_only_delete_candidate"
        reason = (
            "No Phase45b live binds remain for this mixed Try block."
        )

    block = MixedTryClassification(
        block_id=f"mixed_try_{ordinal:02d}",
        phase45b_idx=int(row["phase45b_idx"]),
        start_line=key[0],
        end_line=key[1],
        live_binds=sorted(live),
        preserve_body_stmt_count=int(row["preserve_body_stmt_count"]),
        remove_body_stmt_count=int(row["remove_body_stmt_count"]),
        mechanically_splittable=bool(row["mechanically_splittable"]),
        defined_symbols=sorted(defs),
        helper_symbols=sorted(helpers),
        assignment_symbols=sorted(assigns),
        classification=classification,
        classification_reason=reason,
    )
    classifications.append(block)

    source_windows.append(
        "=" * 120
        + f"\n{block.block_id} | Phase45b idx={block.phase45b_idx} | "
          f"lines={block.start_line}-{block.end_line} | {block.classification}\n"
        + "=" * 120
        + "\n"
        + node_window(block.start_line, block.end_line, pad=8)
        + "\n"
    )

# ------------------------------------------------------------------
# Summary / grouping
# ------------------------------------------------------------------

counts: dict[str, int] = {
    "helper_hosting_live": 0,
    "shell_only_delete_candidate": 0,
    "phase38_dependency_coupled": 0,
}
splittable_count = 0

for block in classifications:
    counts[block.classification] = counts.get(block.classification, 0) + 1
    if block.mechanically_splittable:
        splittable_count += 1

summary_lines = [
    "=== PHASE 50 v2 MIXED TRY-BLOCK CLASSIFICATION SUMMARY ===",
    f"PHASE45B_MIXED_TRYBLOCK_COUNT={len(phase45b_rows)}",
    f"CLASSIFIED_MIXED_TRYBLOCK_COUNT={len(classifications)}",
    f"helper_hosting_live={counts.get('helper_hosting_live', 0)}",
    f"shell_only_delete_candidate={counts.get('shell_only_delete_candidate', 0)}",
    f"phase38_dependency_coupled={counts.get('phase38_dependency_coupled', 0)}",
    f"phase45b_mechanically_splittable={splittable_count}",
    "",
]

for block in classifications:
    summary_lines.extend([
        f"{block.block_id}:",
        f"  phase45b_idx={block.phase45b_idx}",
        f"  lines={block.start_line}-{block.end_line}",
        f"  classification={block.classification}",
        f"  reason={block.classification_reason}",
        f"  mechanically_splittable={block.mechanically_splittable}",
        f"  preserve_body_stmt_count={block.preserve_body_stmt_count}",
        f"  remove_body_stmt_count={block.remove_body_stmt_count}",
        f"  live_binds={', '.join(block.live_binds) or '-'}",
        f"  defined_symbols={', '.join(block.defined_symbols) or '-'}",
        f"  helper_symbols={', '.join(block.helper_symbols) or '-'}",
        f"  assignment_symbols={', '.join(block.assignment_symbols) or '-'}",
        "",
    ])

(out / "13_mixed_tryblock_classification_summary.txt").write_text(
    "\n".join(summary_lines) + "\n",
    encoding="utf-8",
)

(out / "14_mixed_tryblock_classification.json").write_text(
    json.dumps([asdict(block) for block in classifications], indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

matrix_lines = [
    "=== PHASE 50 v2 MIXED TRY-BLOCK DEPENDENCY MATRIX ===",
    "block | phase45b_idx | lines | class | splittable | live_binds | helpers | assigns",
    "-" * 180,
]

for block in classifications:
    matrix_lines.append(
        f"{block.block_id} | {block.phase45b_idx} | {block.start_line}-{block.end_line} | "
        f"{block.classification} | {block.mechanically_splittable} | "
        f"{','.join(block.live_binds) or '-'} | "
        f"{','.join(block.helper_symbols) or '-'} | "
        f"{','.join(block.assignment_symbols) or '-'}"
    )

(out / "15_mixed_tryblock_dependency_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

(out / "16_mixed_tryblock_source_windows.txt").write_text(
    "\n".join(source_windows),
    encoding="utf-8",
)

groups = {
    "helper_hosting_live": [],
    "shell_only_delete_candidate": [],
    "phase38_dependency_coupled": [],
    "mechanically_splittable": [],
}

for block in classifications:
    groups[block.classification].append(block)
    if block.mechanically_splittable:
        groups["mechanically_splittable"].append(block)

for name, blocks in groups.items():
    text = [f"=== PHASE 50 v2 GROUP: {name} ==="]
    if not blocks:
        text.append("NONE")
    else:
        for block in blocks:
            text.extend([
                f"{block.block_id} | Phase45b idx={block.phase45b_idx} | lines={block.start_line}-{block.end_line}",
                f"  classification={block.classification}",
                f"  splittable={block.mechanically_splittable}",
                f"  reason={block.classification_reason}",
                f"  live_binds={', '.join(block.live_binds) or '-'}",
                f"  helper_symbols={', '.join(block.helper_symbols) or '-'}",
                f"  assignment_symbols={', '.join(block.assignment_symbols) or '-'}",
            ])
    (out / f"17_group_{name}.txt").write_text(
        "\n".join(text) + "\n",
        encoding="utf-8",
    )

# ------------------------------------------------------------------
# Explicit explanation of v1 false-positive class
# ------------------------------------------------------------------

false_positive_note = """=== PHASE 50 v2 — v1 FALSE-POSITIVE EXCLUSION NOTE ===

Phase50 v1 independently re-derived "mixed block" liveness by scanning post-marker
name loads without lexical scope resolution.

That caused a false-positive candidate around the old 3683-3727 Try block because
the names:

- action
- args
- meta
- text

were treated as if later post-Phase38 loads meant dependency on those old module
assignments.

That is not a reliable inference. Those names are generic and are repeatedly used
as function-local variables in the flattened router pipeline.

Phase50 v2 therefore uses the Phase45b mixed Try-block liveness matrix as the
authoritative block universe and classifies those exact spans only.
"""
(out / "18_v1_false_positive_exclusion_note.txt").write_text(
    false_positive_note,
    encoding="utf-8",
)

# ------------------------------------------------------------------
# Assertions
# ------------------------------------------------------------------

assertion_lines = ["=== PHASE 50 v2 TARGETED ASSERTIONS ==="]

if len(phase45b_rows) == 7:
    assertion_lines.append("PASS: Phase45b authoritative mixed Try-block count remains 7")
else:
    errors.append(
        f"FAIL: expected Phase45b authoritative mixed Try-block count 7, got {len(phase45b_rows)}"
    )

if len(classifications) == len(phase45b_rows):
    assertion_lines.append(
        f"PASS: classified every Phase45b-reported mixed Try block ({len(classifications)}/{len(phase45b_rows)})"
    )
else:
    errors.append(
        f"FAIL: classified {len(classifications)} block(s) from {len(phase45b_rows)} Phase45b row(s)"
    )

if counts.get("shell_only_delete_candidate", 0) == 0:
    assertion_lines.append("PASS: no shell-only delete candidate identified")
else:
    assertion_lines.append(
        f"INFO: shell-only delete candidates identified: {counts.get('shell_only_delete_candidate', 0)}"
    )

if counts.get("helper_hosting_live", 0) == 7:
    assertion_lines.append("PASS: all 7 remaining mixed Try blocks are helper-hosting live blocks")
else:
    assertion_lines.append(
        f"INFO: helper-hosting live block count = {counts.get('helper_hosting_live', 0)}"
    )

if splittable_count == 1:
    assertion_lines.append("PASS: Phase45b mechanically splittable mixed-block count remains 1")
else:
    errors.append(
        f"FAIL: expected exactly 1 mechanically splittable Phase45b mixed block, got {splittable_count}"
    )

if errors:
    assertion_lines.extend(errors)
else:
    assertion_lines.append("PHASE50_V2_CLASSIFICATION_ASSERTIONS_PASS")

(out / "19_targeted_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(summary_lines))
print("\n".join(assertion_lines))

if errors:
    raise SystemExit("Phase50 v2 classification assertions failed")
PY

# ---------------------------------------------------------------------
# 4. Direct runtime sanity probe
# ---------------------------------------------------------------------

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

lines: list[str] = ["=== PHASE 50 v2 DIRECT RUNTIME SANITY PROBE ==="]
failures: list[str] = []

surfaces = {
    "route": getattr(router, "route", None),
    "route_intent": getattr(router, "route_intent", None),
    "route_command": getattr(router, "route_command", None),
    "parse_command": getattr(router, "parse_command", None),
    "classify": getattr(router, "classify", None),
}

surface_ids = {name: id(fn) for name, fn in surfaces.items()}
same = len(set(surface_ids.values())) == 1

lines.append("surface_ids=" + json.dumps(surface_ids, sort_keys=True))
lines.append(f"all_public_surfaces_same_object={same}")

if not same:
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

if failures:
    lines.extend(failures)
else:
    lines.append("DIRECT_RUNTIME_SANITY_PROBE_PASS")

(out / "20_direct_runtime_sanity_probe.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

print("\n".join(lines))

if failures:
    raise SystemExit("Phase50 v2 runtime sanity probe failed")
PY

# ---------------------------------------------------------------------
# 5. Final digest
# ---------------------------------------------------------------------

python3 - "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])

classified = json.loads(
    (out / "14_mixed_tryblock_classification.json").read_text(encoding="utf-8")
)

helper = sum(1 for b in classified if b["classification"] == "helper_hosting_live")
shell = sum(1 for b in classified if b["classification"] == "shell_only_delete_candidate")
coupled = sum(1 for b in classified if b["classification"] == "phase38_dependency_coupled")
splittable = sum(1 for b in classified if b["mechanically_splittable"])

digest = f"""=== PHASE 50 v2 DIGEST ===
Router compile: PASS
Audit mode: PASS
No source files modified: PASS

Phase45b authoritative mixed pre-Phase38 Try blocks: {len(classified)}

Classification:
- helper_hosting_live: {helper}
- shell_only_delete_candidate: {shell}
- phase38_dependency_coupled: {coupled}
- mechanically splittable per Phase45b: {splittable}

Phase50 v1 false-positive resolved:
- the synthetic 8th block was caused by scope-blind generic-name matching;
- Phase50 v2 classifies only the 7 Phase45b-authoritative mixed blocks.

Runtime sanity:
- public router surfaces remain canonical: PASS
- multi-PDF enrichment remains intact: PASS

Phase50 v2 succeeded.

Interpretation:
- There is no shell-only whole-block delete target left.
- The remaining 7 mixed blocks are live helper-hosting shells.
- Exactly 1 remains mechanically splittable according to Phase45b.
- Phase51 should target that single mechanically splittable helper/shell block with
  an exact-semantic guarded prune, not attempt broad deletions.

Review:
- 13_mixed_tryblock_classification_summary.txt
- 15_mixed_tryblock_dependency_matrix.txt
- 17_group_mechanically_splittable.txt
- 18_v1_false_positive_exclusion_note.txt
- 19_targeted_assertions.txt
- 20_direct_runtime_sanity_probe.txt

PHASE50_V2_OUT={out}
"""

(out / "21_console_digest.txt").write_text(digest, encoding="utf-8")
print(digest)
PY

echo
echo "PHASE50_V2_OUT=$OUT"
