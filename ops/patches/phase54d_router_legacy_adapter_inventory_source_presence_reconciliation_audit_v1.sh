#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase54d_router_legacy_adapter_inventory_source_presence_reconciliation_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

for f in "$ROUTER" "$PHASE45B_SCRIPT"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase54d — Router Legacy Adapter Inventory Source-Presence Reconciliation Audit

## Purpose

Phase54c proved that Phase45b's legacy-adapter candidate inventory is real
and parseable. However, Phase45b's inventory is generated from a static
adapter-group catalogue and classifies rows only by post-Phase38 liveness.

This audit determines whether each Phase45b candidate group still has
actual source presence in the current router file.

It distinguishes:

1. Concrete source-present candidate chains
2. Catalogue-only rows whose source has already been retired
3. Rows with any remaining post-Phase38 liveness, which must be retained

No source files are modified.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

echo "=== PHASE45b REFRESH ===" | tee "$OUT/01_phase45b_refresh.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/01_phase45b_refresh.txt"

PHASE45B_OUT="$(
  grep -oE 'PHASE45B_OUT=.*' "$OUT/01_phase45b_refresh.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  PHASE45B_OUT="$(ls -td ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_* 2>/dev/null | head -1 || true)"
fi

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve refreshed Phase45b output directory." >&2
  exit 1
fi

INV="$PHASE45B_OUT/07_legacy_adapter_chain_transitive_liveness_inventory.txt"

if [[ ! -f "$INV" ]]; then
  echo "Missing Phase45b legacy adapter inventory: $INV" >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/02_phase45b_out_path.txt"
echo "PHASE45B_INVENTORY=$INV" | tee -a "$OUT/02_phase45b_out_path.txt"

python3 - "$ROUTER" "$PHASE45B_SCRIPT" "$INV" "$OUT" "$PHASE38_MARKER" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

router_path = Path(sys.argv[1])
phase45b_script_path = Path(sys.argv[2])
inventory_path = Path(sys.argv[3])
out = Path(sys.argv[4])
phase38_marker = sys.argv[5]

router_text = router_path.read_text(encoding="utf-8")
router_lines = router_text.splitlines()

script_text = phase45b_script_path.read_text(encoding="utf-8")
inventory_text = inventory_path.read_text(encoding="utf-8")

# ---------------------------------------------------------------------
# Locate Phase38 marker
# ---------------------------------------------------------------------

phase38_line = None
for idx, line in enumerate(router_lines, start=1):
    if phase38_marker in line:
        phase38_line = idx
        break

if phase38_line is None:
    raise SystemExit(f"Phase38 marker not found: {phase38_marker}")

pre_lines = router_lines[: phase38_line - 1]
post_lines = router_lines[phase38_line - 1 :]
pre_source = "\n".join(pre_lines)
post_source = "\n".join(post_lines)

# ---------------------------------------------------------------------
# Extract adapter_groups catalogue from Phase45b script
# ---------------------------------------------------------------------

m_groups = re.search(
    r"adapter_groups:\s*dict\[str,\s*set\[str\]\]\s*=\s*(\{.*?\n\})\n\nadapter_inventory",
    script_text,
    re.S,
)

if not m_groups:
    raise SystemExit("Could not extract adapter_groups catalogue from Phase45b script.")

adapter_groups_src = m_groups.group(1)
adapter_groups = ast.literal_eval(adapter_groups_src)

if not isinstance(adapter_groups, dict):
    raise SystemExit("adapter_groups extraction did not produce a dict.")

(out / "03_adapter_groups_extracted.json").write_text(
    json.dumps({k: sorted(v) for k, v in adapter_groups.items()}, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Parse Phase45b inventory rows
# ---------------------------------------------------------------------

@dataclass
class InventoryRow:
    group: str
    postmarker_ast_hits: str
    postmarker_text_hits: str
    classification: str

inventory_rows: list[InventoryRow] = []

for raw in inventory_text.splitlines():
    line = raw.strip()
    if not line or "|" not in line:
        continue
    if line.startswith("group |"):
        continue
    parts = [part.strip() for part in line.split("|")]
    if len(parts) != 4:
        continue
    inventory_rows.append(
        InventoryRow(
            group=parts[0],
            postmarker_ast_hits=parts[1],
            postmarker_text_hits=parts[2],
            classification=parts[3],
        )
    )

(out / "04_inventory_rows_parsed.json").write_text(
    json.dumps([row.__dict__ for row in inventory_rows], indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# AST binder collection for current router
# ---------------------------------------------------------------------

tree = ast.parse(router_text)

@dataclass
class Binder:
    name: str
    kind: str
    lineno: int
    end_lineno: int

binders: list[Binder] = []

def assigned_names(node: ast.AST) -> list[str]:
    names: list[str] = []

    def walk_target(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                walk_target(elt)

    if isinstance(node, ast.Assign):
        for target in node.targets:
            walk_target(target)
    elif isinstance(node, ast.AnnAssign):
        walk_target(node.target)
    elif isinstance(node, ast.AugAssign):
        walk_target(node.target)

    return names

for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        binders.append(
            Binder(
                name=node.name,
                kind=type(node).__name__,
                lineno=getattr(node, "lineno", -1),
                end_lineno=getattr(node, "end_lineno", getattr(node, "lineno", -1)),
            )
        )
    elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        for name in assigned_names(node):
            binders.append(
                Binder(
                    name=name,
                    kind=type(node).__name__,
                    lineno=getattr(node, "lineno", -1),
                    end_lineno=getattr(node, "end_lineno", getattr(node, "lineno", -1)),
                )
            )

# ---------------------------------------------------------------------
# Reconcile inventory groups against current router source
# ---------------------------------------------------------------------

def text_hit_lines(symbol: str, lines: list[str], offset: int = 0) -> list[int]:
    pat = re.compile(rf"\b{re.escape(symbol)}\b")
    hits: list[int] = []
    for idx, line in enumerate(lines, start=1 + offset):
        if pat.search(line):
            hits.append(idx)
    return hits

records: list[dict[str, Any]] = []

for row in inventory_rows:
    symbols = sorted(adapter_groups.get(row.group, set()))
    pre_text_hits: dict[str, list[int]] = {}
    post_text_hits: dict[str, list[int]] = {}
    pre_binders: list[dict[str, Any]] = []
    post_binders: list[dict[str, Any]] = []

    for symbol in symbols:
        pre_hits = text_hit_lines(symbol, pre_lines, offset=0)
        post_hits = text_hit_lines(symbol, post_lines, offset=phase38_line - 1)

        if pre_hits:
            pre_text_hits[symbol] = pre_hits
        if post_hits:
            post_text_hits[symbol] = post_hits

        for binder in binders:
            if binder.name != symbol:
                continue
            item = {
                "name": binder.name,
                "kind": binder.kind,
                "lineno": binder.lineno,
                "end_lineno": binder.end_lineno,
            }
            if binder.lineno < phase38_line:
                pre_binders.append(item)
            else:
                post_binders.append(item)

    has_pre_source_presence = bool(pre_text_hits or pre_binders)
    has_post_source_presence = bool(post_text_hits or post_binders)

    if has_post_source_presence:
        reconciliation = "RETAIN_OR_DEEPER_REVIEW__POST_PHASE38_SOURCE_PRESENT"
    elif has_pre_source_presence:
        reconciliation = "CONCRETE_SOURCE_PRESENT__GUARDED_DELETE_AUDIT_REQUIRED"
    else:
        reconciliation = "CATALOGUE_ONLY__SOURCE_ALREADY_ABSENT"

    records.append(
        {
            "group": row.group,
            "inventory_classification": row.classification,
            "symbols": symbols,
            "pre_text_hits": pre_text_hits,
            "post_text_hits": post_text_hits,
            "pre_binders": pre_binders,
            "post_binders": post_binders,
            "has_pre_source_presence": has_pre_source_presence,
            "has_post_source_presence": has_post_source_presence,
            "reconciliation": reconciliation,
        }
    )

(out / "05_source_presence_reconciliation.json").write_text(
    json.dumps(records, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Human-readable matrix
# ---------------------------------------------------------------------

matrix = [
    "=== PHASE54d LEGACY ADAPTER INVENTORY SOURCE-PRESENCE RECONCILIATION ===",
    f"PHASE38_MARKER_LINE={phase38_line}",
    "",
    "group | inventory_classification | symbols | pre_source_hits | post_source_hits | reconciliation",
    "-" * 260,
]

for rec in records:
    pre_count = sum(len(v) for v in rec["pre_text_hits"].values()) + len(rec["pre_binders"])
    post_count = sum(len(v) for v in rec["post_text_hits"].values()) + len(rec["post_binders"])
    matrix.append(
        f"{rec['group']} | "
        f"{rec['inventory_classification']} | "
        f"{len(rec['symbols'])} | "
        f"{pre_count} | "
        f"{post_count} | "
        f"{rec['reconciliation']}"
    )

(out / "06_source_presence_reconciliation_matrix.txt").write_text(
    "\n".join(matrix) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Per-group detail
# ---------------------------------------------------------------------

details: list[str] = [
    "=== PHASE54d PER-GROUP SOURCE-PRESENCE DETAIL ===",
    "",
]

for rec in records:
    details.append("=" * 140)
    details.append(rec["group"])
    details.append("=" * 140)
    details.append(f"inventory_classification={rec['inventory_classification']}")
    details.append(f"reconciliation={rec['reconciliation']}")
    details.append(f"symbols={', '.join(rec['symbols']) or '-'}")
    details.append("")
    details.append("pre_text_hits:")
    if rec["pre_text_hits"]:
        for symbol, hits in rec["pre_text_hits"].items():
            details.append(f"  {symbol}: {hits}")
    else:
        details.append("  -")
    details.append("")
    details.append("post_text_hits:")
    if rec["post_text_hits"]:
        for symbol, hits in rec["post_text_hits"].items():
            details.append(f"  {symbol}: {hits}")
    else:
        details.append("  -")
    details.append("")
    details.append("pre_binders:")
    if rec["pre_binders"]:
        for binder in rec["pre_binders"]:
            details.append(f"  {binder}")
    else:
        details.append("  -")
    details.append("")
    details.append("post_binders:")
    if rec["post_binders"]:
        for binder in rec["post_binders"]:
            details.append(f"  {binder}")
    else:
        details.append("  -")
    details.append("")

(out / "07_source_presence_group_detail.txt").write_text(
    "\n".join(details) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Source windows for any actual source presence
# ---------------------------------------------------------------------

windows: list[str] = [
    "=== PHASE54d SOURCE WINDOWS FOR ANY REMAINING ADAPTER SYMBOL PRESENCE ===",
    "",
]

seen_windows: set[tuple[int, int]] = set()

all_hit_lines: set[int] = set()
for rec in records:
    for hit_map in (rec["pre_text_hits"], rec["post_text_hits"]):
        for hits in hit_map.values():
            all_hit_lines.update(hits)
    for binder in rec["pre_binders"] + rec["post_binders"]:
        all_hit_lines.add(int(binder["lineno"]))

for hit in sorted(all_hit_lines):
    start = max(1, hit - 5)
    end = min(len(router_lines), hit + 8)
    key = (start, end)
    if key in seen_windows:
        continue
    seen_windows.add(key)

    windows.append("=" * 140)
    windows.append(f"ROUTER WINDOW {start}-{end} | trigger_line={hit}")
    windows.append("=" * 140)
    for lineno in range(start, end + 1):
        windows.append(f"{lineno:>6}: {router_lines[lineno - 1]}")
    windows.append("")

(out / "08_source_presence_router_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Direct runtime sanity probe
# ---------------------------------------------------------------------

runtime_probe = r'''
from __future__ import annotations

import inspect
import json

from eli.execution import router_enhanced as r

surfaces = {
    "route": r.route,
    "route_intent": r.route_intent,
    "route_command": r.route_command,
    "parse_command": r.parse_command,
    "classify": r.classify,
}

ids = {name: id(fn) for name, fn in surfaces.items()}
same_object = len(set(ids.values())) == 1

identity_probe = r.route("Who am I?")
memory_runtime_probe = r.route(
    "Explain exactly how your memory system works internally — which files, which DB tables, which functions."
)
multipdf_probe = r.route("analyze /tmp/a.pdf and /tmp/b.pdf")

print("=== PHASE54d DIRECT RUNTIME SANITY PROBE ===")
print("surface_ids=" + json.dumps(ids, sort_keys=True))
print("all_public_surfaces_same_object=" + str(same_object))
print("identity_probe=" + json.dumps(identity_probe, sort_keys=True, ensure_ascii=False))
print("memory_runtime_probe=" + json.dumps(memory_runtime_probe, sort_keys=True, ensure_ascii=False))
print("multipdf_probe=" + json.dumps(multipdf_probe, sort_keys=True, ensure_ascii=False))

ok = (
    same_object
    and identity_probe.get("action") == "USER_IDENTITY_SUMMARY"
    and memory_runtime_probe.get("action") == "EXPLAIN_MEMORY_RUNTIME"
    and multipdf_probe.get("action") == "ANALYZE_PDF"
    and multipdf_probe.get("args", {}).get("paths") == ["/tmp/a.pdf", "/tmp/b.pdf"]
)

print("PHASE54D_DIRECT_RUNTIME_SANITY_PASS" if ok else "PHASE54D_DIRECT_RUNTIME_SANITY_FAIL")
raise SystemExit(0 if ok else 1)
'''.strip() + "\n"

(out / "09_direct_runtime_probe.py").write_text(runtime_probe, encoding="utf-8")

# ---------------------------------------------------------------------
# Targeted assertions and recommendation
# ---------------------------------------------------------------------

concrete_present = [r for r in records if r["reconciliation"] == "CONCRETE_SOURCE_PRESENT__GUARDED_DELETE_AUDIT_REQUIRED"]
catalogue_only = [r for r in records if r["reconciliation"] == "CATALOGUE_ONLY__SOURCE_ALREADY_ABSENT"]
retain = [r for r in records if r["reconciliation"].startswith("RETAIN_OR_DEEPER_REVIEW")]

assertions = [
    "=== PHASE54d TARGETED ASSERTIONS ===",
    f"parsed_inventory_row_count={len(inventory_rows)}",
    f"adapter_group_catalogue_count={len(adapter_groups)}",
    f"concrete_source_present_candidate_count={len(concrete_present)}",
    f"catalogue_only_already_absent_count={len(catalogue_only)}",
    f"retain_or_deeper_review_count={len(retain)}",
    "",
]

if len(inventory_rows) == 4:
    assertions.append("PASS: Parsed all 4 Phase45b legacy-adapter inventory rows.")
else:
    assertions.append("FAIL: Expected 4 Phase45b inventory rows.")

if len(adapter_groups) == 4:
    assertions.append("PASS: Extracted all 4 Phase45b adapter-group catalogue entries.")
else:
    assertions.append("FAIL: Expected 4 adapter-group catalogue entries.")

if not retain:
    assertions.append("PASS: No candidate adapter group has post-Phase38 source presence.")
else:
    assertions.append("FAIL-CLOSED: At least one adapter group retains post-Phase38 source presence.")

if not concrete_present:
    assertions.append("PASS: No concrete source-present adapter delete chain remains in the current router.")
else:
    assertions.append("NOTICE: One or more concrete source-present adapter delete chains remain and require exact-semantic deletion audit.")

(out / "10_targeted_assertions.txt").write_text(
    "\n".join(assertions) + "\n",
    encoding="utf-8",
)

recommendation = [
    "=== PHASE54d RECOMMENDED NEXT MOVE ===",
    "",
]

if retain:
    recommendation.extend([
        "Do not delete anything.",
        "At least one adapter group still has post-Phase38 source presence.",
        "The next phase must be a deeper liveness audit for the retained groups.",
    ])
elif concrete_present:
    recommendation.extend([
        "Phase55 may proceed as an exact-semantic guarded deletion readiness audit.",
        "Concrete source-present adapter delete candidates still exist.",
        "The deletion patch must be driven by precise source spans and semantic baseline equivalence.",
    ])
else:
    recommendation.extend([
        "Do not build a router deletion patch from Phase45b's candidate count.",
        "The current router has no concrete source-present legacy adapter delete chains remaining.",
        "Phase45b's reported count of 4 is therefore stale catalogue accounting, not actionable source debt.",
        "",
        "The next phase should repair the Phase45b audit itself so that:",
        "- candidate-chain totals count only source-present groups;",
        "- already-retired catalogue rows are reported separately or suppressed;",
        "- the digest no longer implies 4 actionable delete chains when zero remain.",
    ])

(out / "11_recommended_next_move.txt").write_text(
    "\n".join(recommendation) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Console digest
# ---------------------------------------------------------------------

digest = [
    "=== PHASE 54d DIGEST ===",
    "Router compile: PASS",
    "Phase45b refresh: PASS",
    f"Phase38 marker line: {phase38_line}",
    f"Parsed Phase45b inventory rows: {len(inventory_rows)}",
    f"Extracted adapter catalogue groups: {len(adapter_groups)}",
    f"Concrete source-present candidate chains: {len(concrete_present)}",
    f"Catalogue-only already-absent chains: {len(catalogue_only)}",
    f"Retain/deeper-review chains: {len(retain)}",
    "",
]

if retain:
    digest.extend([
        "Conclusion:",
        "Phase45b inventory is parseable, but at least one listed group still has",
        "post-Phase38 source presence. No deletion patch is authorised.",
    ])
elif concrete_present:
    digest.extend([
        "Conclusion:",
        "Phase45b inventory is parseable and at least one candidate group still has",
        "concrete source presence before Phase38. Phase55 may become a guarded",
        "exact-semantic deletion readiness audit.",
    ])
else:
    digest.extend([
        "Conclusion:",
        "Phase45b inventory is parseable, but all 4 rows are catalogue-only residues.",
        "No concrete legacy adapter source remains in the current router for deletion.",
        "The real defect is now Phase45b's stale candidate accounting.",
    ])

digest.extend([
    "",
    "Review:",
    "- 05_source_presence_reconciliation.json",
    "- 06_source_presence_reconciliation_matrix.txt",
    "- 07_source_presence_group_detail.txt",
    "- 08_source_presence_router_windows.txt",
    "- 10_targeted_assertions.txt",
    "- 11_recommended_next_move.txt",
])

(out / "12_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("PHASE54D_STATIC_AUDIT_OK")
print(f"PHASE38_MARKER_LINE={phase38_line}")
print(f"PARSED_INVENTORY_ROW_COUNT={len(inventory_rows)}")
print(f"ADAPTER_GROUP_CATALOGUE_COUNT={len(adapter_groups)}")
print(f"CONCRETE_SOURCE_PRESENT_CANDIDATE_COUNT={len(concrete_present)}")
print(f"CATALOGUE_ONLY_ALREADY_ABSENT_COUNT={len(catalogue_only)}")
print(f"RETAIN_OR_DEEPER_REVIEW_COUNT={len(retain)}")
PY

echo "=== DIRECT RUNTIME SANITY PROBE ===" | tee "$OUT/13_direct_runtime_probe.txt"
PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
python3 "$OUT/09_direct_runtime_probe.py" 2>&1 | tee -a "$OUT/13_direct_runtime_probe.txt"

echo "=== PHASE 54d DIGEST ==="
cat "$OUT/12_console_digest.txt"

echo
echo "PHASE54D_OUT=$OUT"
