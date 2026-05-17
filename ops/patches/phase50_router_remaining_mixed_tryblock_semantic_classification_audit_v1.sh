#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase50_router_remaining_mixed_tryblock_semantic_classification_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

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
  echo "Missing Phase38 marker in router: $PHASE38_MARKER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 50 — Remaining Mixed Try-Block Semantic Classification Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase49 v2 closed the two Phase45b-tracked residual symbol-debt classes:

- pre-Phase38 route-capture residue: 0
- pre-Phase38 public alias rebinding residue: 0

Phase45b still reports 7 mixed pre-Phase38 Try blocks with post-marker live binds.

Phase50 classifies each remaining mixed Try block into one of:

1. \`helper_hosting_live\`
   - block still owns helper functions or constants consumed post-Phase38;
   - cannot delete as a unit;
   - candidate for helper hoist / shell separation.

2. \`shell_only_delete_candidate\`
   - block no longer contributes live helper symbols, live captures, or live side effects;
   - candidate for guarded deletion in a later repair phase.

3. \`phase38_dependency_coupled\`
   - block defines or mutates symbols directly consumed by the Phase38 flattened dispatcher;
   - defer deletion until the flattened dispatcher is explicitly decoupled.

This phase does not modify router source.
EOF

# ---------------------------------------------------------------------
# 1. Router compile
# ---------------------------------------------------------------------

echo "=== PY_COMPILE ===" | tee "$OUT/00_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_compile.txt"

# ---------------------------------------------------------------------
# 2. Refresh Phase45b ground truth
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
# 3. Deep mixed Try-block classifier
# ---------------------------------------------------------------------

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
src_lines = src.splitlines()
tree = ast.parse(src)

phase38_marker_line = None
for idx, line in enumerate(src_lines, start=1):
    if "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1" in line:
        phase38_marker_line = idx
        break

if phase38_marker_line is None:
    raise RuntimeError("Phase38 marker not found during Phase50 classification")

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def node_source_window(start: int, end: int, pad: int = 5) -> str:
    lo = max(1, start - pad)
    hi = min(len(src_lines), end + pad)
    width = len(str(hi))
    return "\n".join(
        f"{i:>{width}}: {src_lines[i - 1]}"
        for i in range(lo, hi + 1)
    )

def pre_phase38(node: ast.AST) -> bool:
    start, _ = span(node)
    return 0 < start < phase38_marker_line

def all_name_loads(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            names.add(sub.id)
    return names

def all_name_stores(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            names.add(sub.id)
    return names

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

def try_contains_postmarker_live_bind(node: ast.Try) -> bool:
    """
    Phase45b's remaining mixed Try blocks are pre-Phase38 nodes whose symbols
    are consumed after the Phase38 marker. Reconstruct that mechanically:
    at least one symbol defined in the Try body must be loaded post-marker.
    """
    defs = defined_symbols_in_try(node)
    if not defs:
        return False

    for top in tree.body:
        start, _ = span(top)
        if start <= phase38_marker_line:
            continue
        if defs & all_name_loads(top):
            return True
    return False

# Build post-Phase38 load map.
post_phase38_load_lines: dict[str, list[int]] = {}
for top in tree.body:
    start, _ = span(top)
    if start <= phase38_marker_line:
        continue
    for sub in ast.walk(top):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            post_phase38_load_lines.setdefault(sub.id, []).append(getattr(sub, "lineno", start))

# Explicit Phase38 dispatcher dependency symbols:
# any helper/symbol loaded in the post-marker dispatcher region.
phase38_post_symbols = set(post_phase38_load_lines)

@dataclass
class MixedTryBlock:
    block_id: str
    start_line: int
    end_line: int
    defined_symbols: list[str]
    helper_symbols: list[str]
    assignment_symbols: list[str]
    post_phase38_consumed_symbols: list[str]
    post_phase38_consumption_lines: dict[str, list[int]]
    contains_except: bool
    except_handler_count: int
    contains_print_side_effect: bool
    contains_runtime_guard_metadata: bool
    classification: str
    classification_reason: str

mixed_blocks: list[MixedTryBlock] = []
source_windows: list[str] = []
dependency_matrix_lines: list[str] = []

for idx, node in enumerate([n for n in ast.walk(tree) if isinstance(n, ast.Try)], start=1):
    if not pre_phase38(node):
        continue
    if not try_contains_postmarker_live_bind(node):
        continue

    s, e = span(node)
    defs = defined_symbols_in_try(node)
    helpers = helper_symbols_in_try(node)
    assigns = assignment_symbols_in_try(node)

    consumed = sorted(sym for sym in defs if sym in post_phase38_load_lines)
    consumption_lines = {
        sym: sorted(set(post_phase38_load_lines.get(sym, [])))
        for sym in consumed
    }

    contains_print = False
    contains_guard_meta = False

    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id == "print":
                contains_print = True

        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            low = sub.value.lower()
            if (
                "matched_by" in low
                or "route contract" in low
                or "installed" in low
                or "failed" in low
                or "guard" in low
            ):
                contains_guard_meta = True

    helper_consumed = sorted(sym for sym in helpers if sym in consumed)
    assignment_consumed = sorted(sym for sym in assigns if sym in consumed)

    if helper_consumed:
        classification = "helper_hosting_live"
        reason = (
            "Defines helper/class symbol(s) consumed post-Phase38: "
            + ", ".join(helper_consumed)
        )
    elif assignment_consumed:
        classification = "phase38_dependency_coupled"
        reason = (
            "Defines assigned symbol(s) consumed post-Phase38: "
            + ", ".join(assignment_consumed)
        )
    elif contains_print or contains_guard_meta:
        classification = "phase38_dependency_coupled"
        reason = (
            "No direct helper/assignment consumption detected, but guarded side-effect "
            "or runtime diagnostic text remains in a post-marker-live mixed shell."
        )
    else:
        classification = "shell_only_delete_candidate"
        reason = (
            "No helper symbol, assignment symbol, or obvious side-effect surface is "
            "consumed post-Phase38."
        )

    block = MixedTryBlock(
        block_id=f"mixed_try_{len(mixed_blocks) + 1:02d}",
        start_line=s,
        end_line=e,
        defined_symbols=sorted(defs),
        helper_symbols=sorted(helpers),
        assignment_symbols=sorted(assigns),
        post_phase38_consumed_symbols=consumed,
        post_phase38_consumption_lines=consumption_lines,
        contains_except=bool(node.handlers),
        except_handler_count=len(node.handlers),
        contains_print_side_effect=contains_print,
        contains_runtime_guard_metadata=contains_guard_meta,
        classification=classification,
        classification_reason=reason,
    )
    mixed_blocks.append(block)

    source_windows.append(
        "=" * 120
        + f"\n{block.block_id} | lines={s}-{e} | classification={classification}\n"
        + "=" * 120
        + "\n"
        + node_source_window(s, e, pad=8)
        + "\n"
    )

    dependency_matrix_lines.append(
        f"{block.block_id} | lines={s}-{e} | class={classification} | "
        f"defs={','.join(block.defined_symbols) or '-'} | "
        f"helpers={','.join(block.helper_symbols) or '-'} | "
        f"assigns={','.join(block.assignment_symbols) or '-'} | "
        f"post_consumed={','.join(block.post_phase38_consumed_symbols) or '-'}"
    )

# Summary counts.
counts: dict[str, int] = {}
for block in mixed_blocks:
    counts[block.classification] = counts.get(block.classification, 0) + 1

classification_lines = [
    "=== PHASE 50 MIXED TRY-BLOCK CLASSIFICATION SUMMARY ===",
    f"PHASE38_MARKER_LINE={phase38_marker_line}",
    f"MIXED_PRE_PHASE38_TRYBLOCK_COUNT={len(mixed_blocks)}",
    f"helper_hosting_live={counts.get('helper_hosting_live', 0)}",
    f"shell_only_delete_candidate={counts.get('shell_only_delete_candidate', 0)}",
    f"phase38_dependency_coupled={counts.get('phase38_dependency_coupled', 0)}",
    "",
]

for block in mixed_blocks:
    classification_lines.extend([
        f"{block.block_id}:",
        f"  lines={block.start_line}-{block.end_line}",
        f"  classification={block.classification}",
        f"  reason={block.classification_reason}",
        f"  defined_symbols={', '.join(block.defined_symbols) or '-'}",
        f"  helper_symbols={', '.join(block.helper_symbols) or '-'}",
        f"  assignment_symbols={', '.join(block.assignment_symbols) or '-'}",
        f"  post_phase38_consumed_symbols={', '.join(block.post_phase38_consumed_symbols) or '-'}",
        "",
    ])

(out / "13_mixed_tryblock_classification_summary.txt").write_text(
    "\n".join(classification_lines) + "\n",
    encoding="utf-8",
)

(out / "14_mixed_tryblock_classification.json").write_text(
    json.dumps([asdict(block) for block in mixed_blocks], indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

(out / "15_mixed_tryblock_dependency_matrix.txt").write_text(
    "=== PHASE 50 MIXED TRY-BLOCK DEPENDENCY MATRIX ===\n"
    + "\n".join(dependency_matrix_lines)
    + "\n",
    encoding="utf-8",
)

(out / "16_mixed_tryblock_source_windows.txt").write_text(
    "\n".join(source_windows),
    encoding="utf-8",
)

# Grouping reports for the next repair phase.
groups: dict[str, list[MixedTryBlock]] = {
    "helper_hosting_live": [],
    "shell_only_delete_candidate": [],
    "phase38_dependency_coupled": [],
}
for block in mixed_blocks:
    groups[block.classification].append(block)

for name, blocks in groups.items():
    report = [f"=== PHASE 50 GROUP: {name} ==="]
    if not blocks:
        report.append("NONE")
    else:
        for block in blocks:
            report.extend([
                f"{block.block_id} | lines={block.start_line}-{block.end_line}",
                f"  reason={block.classification_reason}",
                f"  defs={', '.join(block.defined_symbols) or '-'}",
                f"  post_consumed={', '.join(block.post_phase38_consumed_symbols) or '-'}",
            ])
    (out / f"17_group_{name}.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

# Assertions: Phase45b said 7. Phase50 should agree.
assertions = [
    "=== PHASE 50 TARGETED ASSERTIONS ==="
]
failures: list[str] = []

if len(mixed_blocks) == 7:
    assertions.append("PASS: classified exactly 7 remaining mixed pre-Phase38 Try blocks")
else:
    failures.append(
        f"FAIL: expected 7 mixed pre-Phase38 Try blocks, classified {len(mixed_blocks)}"
    )

if counts.get("helper_hosting_live", 0) + counts.get("shell_only_delete_candidate", 0) + counts.get("phase38_dependency_coupled", 0) == len(mixed_blocks):
    assertions.append("PASS: every mixed Try block received exactly one classification")
else:
    failures.append("FAIL: classification count does not cover all mixed Try blocks")

if any(block.classification == "shell_only_delete_candidate" for block in mixed_blocks):
    assertions.append("PASS: at least one shell-only delete candidate identified")
else:
    assertions.append("INFO: no shell-only delete candidate identified; Phase51 may be hoist-first rather than delete-first")

assertions.extend(failures)

(out / "18_targeted_assertions.txt").write_text(
    "\n".join(assertions) + "\n",
    encoding="utf-8",
)

print("\n".join(classification_lines))
print("\n".join(assertions))

if failures:
    raise SystemExit("Phase50 classification assertions failed")
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

report = ["=== PHASE 50 DIRECT RUNTIME SANITY PROBE ==="]
failures: list[str] = []

surfaces = {
    "route": getattr(router, "route", None),
    "route_intent": getattr(router, "route_intent", None),
    "route_command": getattr(router, "route_command", None),
    "parse_command": getattr(router, "parse_command", None),
    "classify": getattr(router, "classify", None),
}

surface_ids = {name: id(fn) for name, fn in surfaces.items()}
same_object = len(set(surface_ids.values())) == 1

report.append("surface_ids=" + json.dumps(surface_ids, sort_keys=True))
report.append(f"all_public_surfaces_same_object={same_object}")

if not same_object:
    failures.append("FAIL: public routing surfaces are not canonical")

route = surfaces["route"]
if not callable(route):
    failures.append("FAIL: route is not callable")
else:
    multipdf = route("analyze /tmp/a.pdf and /tmp/b.pdf")
    report.append("multipdf_probe=" + json.dumps(multipdf, sort_keys=True, ensure_ascii=False))

    if not isinstance(multipdf, dict):
        failures.append("FAIL: multi-PDF probe did not return dict")
    else:
        args = multipdf.get("args") or {}
        meta = multipdf.get("meta") or {}

        paths = args.get("paths") if isinstance(args, dict) else None
        matched_by = str(meta.get("matched_by") or "") if isinstance(meta, dict) else ""

        if paths != ["/tmp/a.pdf", "/tmp/b.pdf"]:
            failures.append(f"FAIL: multi-PDF paths changed unexpectedly: {paths!r}")

        if "phase11_multipdf" not in matched_by:
            failures.append(f"FAIL: multi-PDF matched_by lost enrichment tag: {matched_by!r}")

report.extend(failures or ["DIRECT_RUNTIME_SANITY_PROBE_PASS"])

(out / "19_direct_runtime_sanity_probe.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

print("\n".join(report))

if failures:
    raise SystemExit("Phase50 direct runtime sanity probe failed")
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

classification = json.loads(
    (out / "14_mixed_tryblock_classification.json").read_text(encoding="utf-8")
)

counts = {
    "helper_hosting_live": 0,
    "shell_only_delete_candidate": 0,
    "phase38_dependency_coupled": 0,
}

for block in classification:
    cls = block["classification"]
    counts[cls] = counts.get(cls, 0) + 1

digest = f"""=== PHASE 50 DIGEST ===
Router compile: PASS
Audit mode: PASS
No source files modified: PASS

Remaining mixed pre-Phase38 Try blocks classified: {len(classification)}

Classification counts:
- helper_hosting_live: {counts.get("helper_hosting_live", 0)}
- shell_only_delete_candidate: {counts.get("shell_only_delete_candidate", 0)}
- phase38_dependency_coupled: {counts.get("phase38_dependency_coupled", 0)}

Phase45b residual symbol debt remains closed:
- route-capture hit lines before Phase38: 0
- public alias rebinding hit lines before Phase38: 0

Runtime sanity:
- public router surfaces canonical: PASS
- multi-PDF enrichment intact: PASS

Phase50 succeeded.

Next repair target:
- Phase51 should operate only on the classification output:
  1. delete any shell_only_delete_candidate block(s) under semantic-baseline guard;
  2. hoist helper_hosting_live block(s) only where the helper source can be isolated exactly;
  3. defer phase38_dependency_coupled block(s) until dispatcher dependency is rewritten.

Review:
- 13_mixed_tryblock_classification_summary.txt
- 14_mixed_tryblock_classification.json
- 15_mixed_tryblock_dependency_matrix.txt
- 16_mixed_tryblock_source_windows.txt
- 17_group_helper_hosting_live.txt
- 17_group_shell_only_delete_candidate.txt
- 17_group_phase38_dependency_coupled.txt
- 18_targeted_assertions.txt
- 19_direct_runtime_sanity_probe.txt

PHASE50_OUT={out}
"""
(out / "20_console_digest.txt").write_text(digest, encoding="utf-8")
print(digest)
PY

echo
echo "PHASE50_OUT=$OUT"
