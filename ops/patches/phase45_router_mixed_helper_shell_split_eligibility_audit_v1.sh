#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase45_router_mixed_helper_shell_split_eligibility_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"
PHASE38_FN="_eli_phase38_flattened_route"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Missing Phase 38 marker: $PHASE38_MARKER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 45 — Router Mixed Helper/Shell Split Eligibility Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase 44 removed the final pure dead-shell cluster.

Phase 45 audits the remaining pre-Phase38 residue and determines:

1. Which mixed Try blocks contain Phase38-required helper functions.
2. Which exact substatements inside those blocks must be preserved.
3. Which exact substatements are wrapper-install / rebinding scaffolding that can likely be removed in Phase 46.
4. Which legacy adapter chains appear no longer referenced by Phase38 and may become later deletion candidates after a guarded semantic-equivalence patch.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_compile.txt"

python3 - "$ROUTER" "$OUT" "$PHASE38_MARKER" "$PHASE38_FN" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])
phase38_marker = sys.argv[3]
phase38_fn_name = sys.argv[4]

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

# ---------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def text_for(node: ast.AST) -> str:
    s, e = span(node)
    return "\n".join(lines[s - 1:e])

def target_names(target: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            names |= target_names(elt)
    return names

def direct_bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
        return names

    if isinstance(node, ast.Assign):
        for target in node.targets:
            names |= target_names(target)
        return names

    if isinstance(node, ast.AnnAssign):
        names |= target_names(node.target)
        return names

    if isinstance(node, ast.AugAssign):
        names |= target_names(node.target)
        return names

    if isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.asname or alias.name.split(".")[0])
        return names

    if isinstance(node, ast.ImportFrom):
        for alias in node.names:
            names.add(alias.asname or alias.name)
        return names

    return names

def recursive_bound_names(node: ast.AST) -> set[str]:
    names = direct_bound_names(node)

    if isinstance(node, ast.If):
        for child in node.body:
            names |= recursive_bound_names(child)
        for child in node.orelse:
            names |= recursive_bound_names(child)

    elif isinstance(node, ast.Try):
        for child in node.body:
            names |= recursive_bound_names(child)
        for handler in node.handlers:
            for child in handler.body:
                names |= recursive_bound_names(child)
        for child in node.orelse:
            names |= recursive_bound_names(child)
        for child in node.finalbody:
            names |= recursive_bound_names(child)

    return names

def loaded_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            found.add(sub.id)
    return found

def dump_window(node: ast.AST, title: str) -> str:
    s, e = span(node)
    return "\n".join([
        "=" * 120,
        f"{title} | lines={s}-{e} | kind={type(node).__name__}",
        "=" * 120,
        text_for(node),
        "",
    ])

def marker_line() -> int:
    for idx, line in enumerate(lines, start=1):
        if phase38_marker in line:
            return idx
    raise RuntimeError("Phase 38 marker not found during AST audit")

PHASE38_MARKER_LINE = marker_line()

# ---------------------------------------------------------------------
# Locate Phase 38 flattened dispatcher and its direct symbol loads
# ---------------------------------------------------------------------

phase38_fn: ast.FunctionDef | None = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == phase38_fn_name:
        phase38_fn = node
        break

if phase38_fn is None:
    raise RuntimeError(f"Could not locate Phase 38 function: {phase38_fn_name}")

phase38_direct_loads = loaded_names(phase38_fn)

(out / "01_phase38_direct_loaded_symbol_set.txt").write_text(
    "\n".join([
        "=== PHASE 45 PHASE38 DIRECT LOADED SYMBOL SET ===",
        f"PHASE38_MARKER_LINE={PHASE38_MARKER_LINE}",
        f"PHASE38_FUNCTION={phase38_fn_name}",
        f"PHASE38_FUNCTION_LINES={span(phase38_fn)[0]}-{span(phase38_fn)[1]}",
        "",
        *sorted(phase38_direct_loads),
    ]) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Audit mixed Try blocks before Phase38 marker
# ---------------------------------------------------------------------

@dataclass
class SplitBlock:
    stmt_index: int
    node: ast.Try
    lines: tuple[int, int]
    all_binds: set[str]
    direct_phase38_binds: set[str]
    selected_body_indexes: set[int]
    selected_body_symbols: set[str]
    selected_body_loads: set[str]
    support_symbols: set[str]
    removable_body_indexes: set[int]
    mechanically_splittable: bool
    notes: list[str]

mixed_blocks: list[SplitBlock] = []

for stmt_index, node in enumerate(tree.body):
    s, e = span(node)
    if s >= PHASE38_MARKER_LINE:
        continue
    if not isinstance(node, ast.Try):
        continue

    all_binds = recursive_bound_names(node)
    direct_phase38_binds = all_binds & phase38_direct_loads
    if not direct_phase38_binds:
        continue

    body_bind_map: dict[int, set[str]] = {}
    body_load_map: dict[int, set[str]] = {}

    for i, child in enumerate(node.body):
        body_bind_map[i] = recursive_bound_names(child)
        body_load_map[i] = loaded_names(child)

    selected: set[int] = {
        i for i, binds in body_bind_map.items()
        if binds & direct_phase38_binds
    }

    notes: list[str] = []
    if not selected:
        notes.append("Direct Phase38 bind exists in Try block but not in Try.body statement map")

    # Dependency closure inside the Try.body:
    # if selected helpers load a name defined by another body stmt, preserve it too.
    changed = True
    while changed:
        changed = False
        selected_loads_now: set[str] = set()
        for i in selected:
            selected_loads_now |= body_load_map.get(i, set())

        for i, binds in body_bind_map.items():
            if i in selected:
                continue
            if binds & selected_loads_now:
                selected.add(i)
                changed = True

    selected_body_symbols: set[str] = set()
    selected_body_loads: set[str] = set()
    for i in selected:
        selected_body_symbols |= body_bind_map.get(i, set())
        selected_body_loads |= body_load_map.get(i, set())

    support_symbols = selected_body_symbols - direct_phase38_binds
    removable = set(range(len(node.body))) - selected

    # Safety heuristics
    shellish_selected = {
        sym for sym in selected_body_symbols
        if (
            sym in {"route", "route_intent", "route_command", "parse_command", "classify"}
            or re.search(r"(?:PREV|ORIG|PREVIOUS)", sym)
        )
    }

    mechanically_splittable = bool(selected) and not shellish_selected

    if shellish_selected:
        notes.append(
            "Selected preservation closure still contains route-wrapper/capture symbols: "
            + ", ".join(sorted(shellish_selected))
        )

    if not removable:
        notes.append("No removable Try.body statements identified")

    if node.handlers:
        notes.append(f"Try block has {len(node.handlers)} except handler(s); Phase46 should preserve or deliberately rewrite error policy")

    block = SplitBlock(
        stmt_index=stmt_index,
        node=node,
        lines=(s, e),
        all_binds=all_binds,
        direct_phase38_binds=direct_phase38_binds,
        selected_body_indexes=selected,
        selected_body_symbols=selected_body_symbols,
        selected_body_loads=selected_body_loads,
        support_symbols=support_symbols,
        removable_body_indexes=removable,
        mechanically_splittable=mechanically_splittable,
        notes=notes,
    )
    mixed_blocks.append(block)

# ---------------------------------------------------------------------
# Write mixed-block matrix
# ---------------------------------------------------------------------

matrix = [
    "=== PHASE 45 MIXED HELPER/SHELL SPLIT ELIGIBILITY MATRIX ===",
    f"PHASE38_MARKER_LINE={PHASE38_MARKER_LINE}",
    f"MIXED_PHASE38_HELPER_TRY_BLOCK_COUNT={len(mixed_blocks)}",
    "",
    "idx | lines | direct_phase38_binds | preserved_body_stmt_count | removable_body_stmt_count | mechanically_splittable",
    "-" * 220,
]

for block in mixed_blocks:
    matrix.append(
        f"{block.stmt_index} | {block.lines[0]}-{block.lines[1]} | "
        f"{', '.join(sorted(block.direct_phase38_binds)) or '-'} | "
        f"{len(block.selected_body_indexes)} | "
        f"{len(block.removable_body_indexes)} | "
        f"{block.mechanically_splittable}"
    )

(out / "02_mixed_helper_shell_split_eligibility_matrix.txt").write_text(
    "\n".join(matrix) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Detailed preserve/delete manifests
# ---------------------------------------------------------------------

preserve_manifest: list[str] = [
    "=== PHASE 45 PRESERVE SUBSTATEMENT MANIFEST ===",
    "",
]

remove_manifest: list[str] = [
    "=== PHASE 45 REMOVABLE SUBSTATEMENT MANIFEST ===",
    "",
]

preserve_windows: list[str] = []
remove_windows: list[str] = []

for block in mixed_blocks:
    preserve_manifest.append(
        f"BLOCK idx={block.stmt_index} lines={block.lines[0]}-{block.lines[1]} "
        f"mechanically_splittable={block.mechanically_splittable}"
    )
    preserve_manifest.append(
        "  direct_phase38_binds=" + ", ".join(sorted(block.direct_phase38_binds))
    )
    preserve_manifest.append(
        "  support_symbols=" + (", ".join(sorted(block.support_symbols)) or "-")
    )

    if block.notes:
        for note in block.notes:
            preserve_manifest.append(f"  note={note}")

    for body_i in sorted(block.selected_body_indexes):
        child = block.node.body[body_i]
        s, e = span(child)
        binds = recursive_bound_names(child)
        preserve_manifest.append(
            f"  PRESERVE body[{body_i}] {type(child).__name__} lines={s}-{e} binds={', '.join(sorted(binds)) or '-'}"
        )
        preserve_windows.append(
            dump_window(
                child,
                f"PRESERVE block_idx={block.stmt_index} body[{body_i}] binds={', '.join(sorted(binds)) or '-'}",
            )
        )

    preserve_manifest.append("")

    remove_manifest.append(
        f"BLOCK idx={block.stmt_index} lines={block.lines[0]}-{block.lines[1]} "
        f"mechanically_splittable={block.mechanically_splittable}"
    )

    for body_i in sorted(block.removable_body_indexes):
        child = block.node.body[body_i]
        s, e = span(child)
        binds = recursive_bound_names(child)
        remove_manifest.append(
            f"  REMOVE_CANDIDATE body[{body_i}] {type(child).__name__} lines={s}-{e} binds={', '.join(sorted(binds)) or '-'}"
        )
        remove_windows.append(
            dump_window(
                child,
                f"REMOVE_CANDIDATE block_idx={block.stmt_index} body[{body_i}] binds={', '.join(sorted(binds)) or '-'}",
            )
        )

    remove_manifest.append("")

(out / "03_preserve_substatement_manifest.txt").write_text(
    "\n".join(preserve_manifest) + "\n",
    encoding="utf-8",
)

(out / "04_removable_substatement_manifest.txt").write_text(
    "\n".join(remove_manifest) + "\n",
    encoding="utf-8",
)

(out / "05_preserve_substatement_source_windows.txt").write_text(
    "\n".join(preserve_windows) + "\n",
    encoding="utf-8",
)

(out / "06_removable_substatement_source_windows.txt").write_text(
    "\n".join(remove_windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Audit known residual legacy adapter chains
# ---------------------------------------------------------------------

adapter_groups: dict[str, set[str]] = {
    "legacy_lrf_adapter_chain": {
        "_ELI_LRF_ORIG_ROUTE",
        "_ELI_LRF_ORIG_ROUTE_INTENT",
        "_eli_lrf_route",
        "_eli_lrf_route_intent",
    },
    "legacy_pm_adapter_chain": {
        "_ELI_PM_ORIG_ROUTE",
        "_ELI_PM_ORIG_ROUTE_INTENT",
        "_eli_pm_route",
        "_eli_pm_route_intent",
    },
    "final_personal_memory_route_adapter": {
        "_eli_final_pm_previous_route_20260511",
        "_eli_final_personal_memory_precedence_route",
    },
    "final_personal_memory_route_intent_adapter": {
        "_eli_final_pm_previous_route_intent_20260511",
        "_eli_final_personal_memory_precedence_route_intent",
    },
}

adapter_lines: list[str] = [
    "=== PHASE 45 LEGACY ADAPTER CHAIN LIVENESS INVENTORY ===",
    "",
    "group | phase38_direct_symbol_hits | post_marker_text_hits | pre_marker_statement_spans",
    "-" * 240,
]

adapter_windows: list[str] = []

for group_name, symbols in adapter_groups.items():
    phase38_hits = sorted(symbols & phase38_direct_loads)

    post_marker_text = "\n".join(lines[PHASE38_MARKER_LINE - 1:])
    post_marker_hits = sorted(sym for sym in symbols if sym in post_marker_text)

    relevant_pre_marker_nodes: list[ast.AST] = []
    for node in tree.body:
        s, _ = span(node)
        if s >= PHASE38_MARKER_LINE:
            continue
        txt = text_for(node)
        if any(sym in txt for sym in symbols):
            relevant_pre_marker_nodes.append(node)

    spans = [f"{span(node)[0]}-{span(node)[1]}:{type(node).__name__}" for node in relevant_pre_marker_nodes]

    adapter_lines.append(
        f"{group_name} | "
        f"{', '.join(phase38_hits) or '-'} | "
        f"{', '.join(post_marker_hits) or '-'} | "
        f"{' ; '.join(spans) or '-'}"
    )

    adapter_windows.append("=" * 120)
    adapter_windows.append(f"ADAPTER_GROUP={group_name}")
    adapter_windows.append(f"SYMBOLS={', '.join(sorted(symbols))}")
    adapter_windows.append(f"PHASE38_DIRECT_SYMBOL_HITS={', '.join(phase38_hits) or '-'}")
    adapter_windows.append(f"POST_MARKER_TEXT_HITS={', '.join(post_marker_hits) or '-'}")
    adapter_windows.append("=" * 120)

    for node in relevant_pre_marker_nodes:
        adapter_windows.append(
            dump_window(
                node,
                f"ADAPTER_SOURCE group={group_name}",
            )
        )

    adapter_windows.append("")

(out / "07_legacy_adapter_chain_liveness_inventory.txt").write_text(
    "\n".join(adapter_lines) + "\n",
    encoding="utf-8",
)

(out / "08_legacy_adapter_chain_source_windows.txt").write_text(
    "\n".join(adapter_windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Wrapper/capture symbol inventory remaining before Phase38
# ---------------------------------------------------------------------

pre_phase38 = "\n".join(lines[:PHASE38_MARKER_LINE - 1])

capture_pattern = re.compile(
    r"\b(?:"
    r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)|"
    r"_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)"
    r")\b"
)

capture_hits: list[str] = []
for i, line in enumerate(lines[:PHASE38_MARKER_LINE - 1], start=1):
    if capture_pattern.search(line):
        capture_hits.append(f"{i}:{line}")

(out / "09_residual_route_capture_symbol_hit_lines.txt").write_text(
    "\n".join([
        "=== PHASE 45 RESIDUAL ROUTE CAPTURE SYMBOL HIT LINES ===",
        f"HIT_LINE_COUNT={len(capture_hits)}",
        "",
        *capture_hits,
    ]) + "\n",
    encoding="utf-8",
)

alias_pattern = re.compile(
    r"^\s*(?:route_intent|route_command|parse_command|classify)\s*=\s*"
)

alias_hits: list[str] = []
for i, line in enumerate(lines[:PHASE38_MARKER_LINE - 1], start=1):
    if alias_pattern.search(line):
        alias_hits.append(f"{i}:{line}")

(out / "10_residual_public_alias_rebinding_hit_lines.txt").write_text(
    "\n".join([
        "=== PHASE 45 RESIDUAL PUBLIC ALIAS REBINDING HIT LINES ===",
        f"HIT_LINE_COUNT={len(alias_hits)}",
        "",
        *alias_hits,
    ]) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Runtime public surface identity still intact
# ---------------------------------------------------------------------

import importlib
router_mod = importlib.import_module("eli.execution.router_enhanced")

surface_names = ["route", "route_intent", "route_command", "parse_command", "classify"]
base = getattr(router_mod, "route")

surface_lines = [
    "=== PHASE 45 RUNTIME PUBLIC SURFACE IDENTITY PROBE ===",
]

for name in surface_names:
    fn = getattr(router_mod, name, None)
    code = getattr(fn, "__code__", None)
    surface_lines.append(
        f"{name}: callable={callable(fn)} same_as_route={fn is base} "
        f"id={id(fn) if callable(fn) else None} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"firstlineno={getattr(code, 'co_firstlineno', None)}"
    )

all_same = all(getattr(router_mod, name, None) is base for name in surface_names)
surface_lines.append("")
surface_lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "11_runtime_public_surface_identity_probe.txt").write_text(
    "\n".join(surface_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Conclusion
# ---------------------------------------------------------------------

mechanically_splittable_count = sum(1 for b in mixed_blocks if b.mechanically_splittable)
not_splittable_count = len(mixed_blocks) - mechanically_splittable_count

adapter_probable_delete_count = 0
adapter_review_lines: list[str] = []

for group_name, symbols in adapter_groups.items():
    direct = sorted(symbols & phase38_direct_loads)
    post_hits = sorted(sym for sym in symbols if sym in "\n".join(lines[PHASE38_MARKER_LINE - 1:]))

    if not direct and not post_hits:
        status = "PROBABLE_LATER_DELETE_CHAIN__REQUIRES_GUARDED_SEMANTIC_PATCH"
        adapter_probable_delete_count += 1
    else:
        status = "RETAIN_OR_DEEPER_REVIEW"

    adapter_review_lines.append(f"- {group_name}: {status}")

conclusion = [
    "=== PHASE 45 CONCLUSION ===",
    f"PHASE38_MARKER_LINE={PHASE38_MARKER_LINE}",
    f"PHASE38_FUNCTION={phase38_fn_name}",
    "",
    f"Mixed Phase38-helper Try blocks audited: {len(mixed_blocks)}",
    f"Mechanically splittable helper-shell blocks: {mechanically_splittable_count}",
    f"Blocks requiring deeper/manual handling: {not_splittable_count}",
    "",
    f"Residual route-capture symbol hit lines before Phase38: {len(capture_hits)}",
    f"Residual public alias rebinding hit lines before Phase38: {len(alias_hits)}",
    "",
    f"Legacy adapter groups lacking Phase38/post-marker symbol hits: {adapter_probable_delete_count}",
    *adapter_review_lines,
    "",
    "Interpretation:",
    "- Phase 44 correctly exhausted whole-statement pure deletion.",
    "- Phase 45 identifies the next repair frontier: split mixed helper-hosting blocks rather than delete them wholesale.",
    "- Blocks marked mechanically splittable are strong Phase46 candidates.",
    "- Legacy adapter groups reported as probable later delete chains should not be removed in Phase46 unless that patch separately proves exact semantic equivalence.",
    "- No source files were modified in Phase 45.",
]

(out / "12_phase45_split_eligibility_conclusion.txt").write_text(
    "\n".join(conclusion) + "\n",
    encoding="utf-8",
)

digest = [
    "=== PHASE 45 DIGEST ===",
    "Router compile: PASS",
    "Audit mode: PASS",
    "No source files modified: PASS",
    "",
    f"Mixed Phase38-helper Try blocks audited: {len(mixed_blocks)}",
    f"Mechanically splittable helper-shell blocks: {mechanically_splittable_count}",
    f"Blocks requiring deeper/manual handling: {not_splittable_count}",
    "",
    f"Residual route-capture symbol hit lines before Phase38: {len(capture_hits)}",
    f"Residual public alias rebinding hit lines before Phase38: {len(alias_hits)}",
    f"Legacy adapter groups lacking Phase38/post-marker hits: {adapter_probable_delete_count}",
    "",
    "Review:",
    "- 02_mixed_helper_shell_split_eligibility_matrix.txt",
    "- 03_preserve_substatement_manifest.txt",
    "- 04_removable_substatement_manifest.txt",
    "- 05_preserve_substatement_source_windows.txt",
    "- 06_removable_substatement_source_windows.txt",
    "- 07_legacy_adapter_chain_liveness_inventory.txt",
    "- 08_legacy_adapter_chain_source_windows.txt",
    "- 09_residual_route_capture_symbol_hit_lines.txt",
    "- 10_residual_public_alias_rebinding_hit_lines.txt",
    "- 11_runtime_public_surface_identity_probe.txt",
    "- 12_phase45_split_eligibility_conclusion.txt",
    "",
    f"PHASE45_OUT={out}",
]

(out / "13_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
PY

echo
echo "PHASE45_OUT=$OUT"
