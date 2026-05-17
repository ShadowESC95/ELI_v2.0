#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase45b_router_transitive_postmarker_mixed_shell_split_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

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
# Phase 45b — Router Transitive Post-Marker Mixed Shell Split Audit v2

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Why this replaces Phase 45 v1

Phase 45 v1 only checked symbols directly loaded inside the single
\`_eli_phase38_flattened_route\` function body. That is insufficient.

Phase 45b audits the entire post-Phase38 live region and determines:

1. Which pre-Phase38 mixed Try blocks still bind helper symbols referenced anywhere after Phase38.
2. Which exact child statements inside those mixed blocks are live preserve-candidates.
3. Which child statements are dead shell/capture/rebinding scaffolding.
4. Which legacy adapter groups are source-present actionable delete candidates versus catalogue-only already-retired rows.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_compile.txt"

python3 - "$ROUTER" "$OUT" "$PHASE38_MARKER" <<'PY'
from __future__ import annotations

import ast
import importlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])
phase38_marker = sys.argv[3]

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", -1)
    end = getattr(node, "end_lineno", start)
    return start, end

def text_for(node: ast.AST) -> str:
    s, e = span(node)
    return "\n".join(lines[s - 1:e])

def target_names(target: ast.AST) -> set[str]:
    out_names: set[str] = set()
    if isinstance(target, ast.Name):
        out_names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for child in target.elts:
            out_names |= target_names(child)
    return out_names

def direct_bound_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            names |= target_names(target)
    elif isinstance(node, ast.AnnAssign):
        names |= target_names(node.target)
    elif isinstance(node, ast.AugAssign):
        names |= target_names(node.target)
    elif isinstance(node, ast.Import):
        for alias in node.names:
            names.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            names.add(alias.asname or alias.name)

    return names

def recursive_bound_names(node: ast.AST) -> set[str]:
    names = direct_bound_names(node)

    if isinstance(node, ast.Try):
        for child in node.body:
            names |= recursive_bound_names(child)
        for handler in node.handlers:
            for child in handler.body:
                names |= recursive_bound_names(child)
        for child in node.orelse:
            names |= recursive_bound_names(child)
        for child in node.finalbody:
            names |= recursive_bound_names(child)

    elif isinstance(node, ast.If):
        for child in node.body:
            names |= recursive_bound_names(child)
        for child in node.orelse:
            names |= recursive_bound_names(child)

    return names

def loaded_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            found.add(child.id)
    return found

def marker_line() -> int:
    for idx, line in enumerate(lines, start=1):
        if phase38_marker in line:
            return idx
    raise RuntimeError("Phase 38 marker not found")

def code_window(title: str, node: ast.AST) -> str:
    s, e = span(node)
    return "\n".join([
        "=" * 120,
        f"{title} | {type(node).__name__} | lines={s}-{e}",
        "=" * 120,
        text_for(node),
        "",
    ])

def is_capture_or_wrapper_symbol(name: str) -> bool:
    return bool(
        name in {"route", "route_intent", "route_command", "parse_command", "classify"}
        or re.search(r"(?:PREV|ORIG_ROUTE|PREVIOUS_ROUTE)", name)
        or re.search(r"_eli_.*(?:prev_route|previous_route)", name)
    )

PHASE38_LINE = marker_line()
post_marker_source = "\n".join(lines[PHASE38_LINE - 1:])

# ---------------------------------------------------------------------
# Post-marker liveness surface
# ---------------------------------------------------------------------

post_marker_nodes = [
    node for node in tree.body
    if getattr(node, "lineno", 10**9) >= PHASE38_LINE
]

post_marker_ast_loads: set[str] = set()
for node in post_marker_nodes:
    post_marker_ast_loads |= loaded_names(node)

(out / "01_postmarker_ast_loaded_symbols.txt").write_text(
    "\n".join([
        "=== PHASE 45b POST-MARKER AST-LOADED SYMBOLS ===",
        f"PHASE38_MARKER_LINE={PHASE38_LINE}",
        f"POST_MARKER_TOPLEVEL_NODE_COUNT={len(post_marker_nodes)}",
        "",
        *sorted(post_marker_ast_loads),
    ]) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Pre-marker mixed Try block audit
# ---------------------------------------------------------------------

@dataclass
class MixedBlock:
    idx: int
    node: ast.Try
    lines: tuple[int, int]
    all_binds: set[str]
    live_binds_ast: set[str]
    live_binds_text: set[str]
    live_binds_combined: set[str]
    preserve_body_indexes: set[int]
    remove_body_indexes: set[int]
    preserve_symbols: set[str]
    remove_symbols: set[str]
    shell_symbols_preserved: set[str]
    mechanically_splittable: bool
    notes: list[str]

mixed_blocks: list[MixedBlock] = []

for idx, node in enumerate(tree.body):
    s, e = span(node)
    if s >= PHASE38_LINE:
        continue
    if not isinstance(node, ast.Try):
        continue

    all_binds = recursive_bound_names(node)
    if not all_binds:
        continue

    live_ast = all_binds & post_marker_ast_loads
    live_text = {name for name in all_binds if re.search(rf"\b{re.escape(name)}\b", post_marker_source)}
    live_combined = live_ast | live_text

    if not live_combined:
        continue

    body_bind_map: dict[int, set[str]] = {}
    body_load_map: dict[int, set[str]] = {}

    for body_i, child in enumerate(node.body):
        body_bind_map[body_i] = recursive_bound_names(child)
        body_load_map[body_i] = loaded_names(child)

    preserve: set[int] = {
        body_i for body_i, binds in body_bind_map.items()
        if binds & live_combined
    }

    # Dependency closure within the Try.body:
    # if a preserved statement loads a symbol defined by another child statement,
    # preserve that child too.
    changed = True
    while changed:
        changed = False
        preserved_loads: set[str] = set()
        for body_i in preserve:
            preserved_loads |= body_load_map.get(body_i, set())

        for body_i, binds in body_bind_map.items():
            if body_i in preserve:
                continue
            if binds & preserved_loads:
                preserve.add(body_i)
                changed = True

    remove = set(range(len(node.body))) - preserve

    preserve_symbols: set[str] = set()
    remove_symbols: set[str] = set()

    for body_i in preserve:
        preserve_symbols |= body_bind_map.get(body_i, set())

    for body_i in remove:
        remove_symbols |= body_bind_map.get(body_i, set())

    shell_preserved = {sym for sym in preserve_symbols if is_capture_or_wrapper_symbol(sym)}

    notes: list[str] = []
    if shell_preserved:
        notes.append(
            "Preservation closure still includes shell/capture symbols: "
            + ", ".join(sorted(shell_preserved))
        )
    if not remove:
        notes.append("No removable Try.body child statements identified")
    if node.handlers:
        notes.append(f"Try block has {len(node.handlers)} except handler(s); patch must preserve or consciously replace failure policy")

    mechanically_splittable = bool(remove) and not shell_preserved

    mixed_blocks.append(
        MixedBlock(
            idx=idx,
            node=node,
            lines=(s, e),
            all_binds=all_binds,
            live_binds_ast=live_ast,
            live_binds_text=live_text,
            live_binds_combined=live_combined,
            preserve_body_indexes=preserve,
            remove_body_indexes=remove,
            preserve_symbols=preserve_symbols,
            remove_symbols=remove_symbols,
            shell_symbols_preserved=shell_preserved,
            mechanically_splittable=mechanically_splittable,
            notes=notes,
        )
    )

matrix_lines = [
    "=== PHASE 45b MIXED TRY-BLOCK TRANSITIVE POST-MARKER LIVENESS MATRIX ===",
    f"PHASE38_MARKER_LINE={PHASE38_LINE}",
    f"MIXED_TRY_BLOCK_COUNT={len(mixed_blocks)}",
    "",
    "idx | lines | live_binds_combined | preserve_body_stmt_count | remove_body_stmt_count | mechanically_splittable",
    "-" * 240,
]

for block in mixed_blocks:
    matrix_lines.append(
        f"{block.idx} | {block.lines[0]}-{block.lines[1]} | "
        f"{', '.join(sorted(block.live_binds_combined)) or '-'} | "
        f"{len(block.preserve_body_indexes)} | "
        f"{len(block.remove_body_indexes)} | "
        f"{block.mechanically_splittable}"
    )

(out / "02_mixed_tryblock_liveness_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Preserve/remove manifests
# ---------------------------------------------------------------------

preserve_manifest = [
    "=== PHASE 45b PRESERVE SUBSTATEMENT MANIFEST ===",
    "",
]

remove_manifest = [
    "=== PHASE 45b REMOVE-CANDIDATE SUBSTATEMENT MANIFEST ===",
    "",
]

preserve_windows: list[str] = []
remove_windows: list[str] = []

for block in mixed_blocks:
    preserve_manifest.append(
        f"BLOCK idx={block.idx} lines={block.lines[0]}-{block.lines[1]} "
        f"mechanically_splittable={block.mechanically_splittable}"
    )
    preserve_manifest.append("  live_binds_ast=" + (", ".join(sorted(block.live_binds_ast)) or "-"))
    preserve_manifest.append("  live_binds_text=" + (", ".join(sorted(block.live_binds_text)) or "-"))
    preserve_manifest.append("  live_binds_combined=" + (", ".join(sorted(block.live_binds_combined)) or "-"))
    preserve_manifest.append("  preserve_symbols=" + (", ".join(sorted(block.preserve_symbols)) or "-"))
    if block.notes:
        for note in block.notes:
            preserve_manifest.append(f"  note={note}")

    for body_i in sorted(block.preserve_body_indexes):
        child = block.node.body[body_i]
        s, e = span(child)
        binds = recursive_bound_names(child)
        preserve_manifest.append(
            f"  PRESERVE body[{body_i}] {type(child).__name__} lines={s}-{e} binds={', '.join(sorted(binds)) or '-'}"
        )
        preserve_windows.append(
            code_window(
                f"PRESERVE block_idx={block.idx} body[{body_i}] binds={', '.join(sorted(binds)) or '-'}",
                child,
            )
        )

    preserve_manifest.append("")

    remove_manifest.append(
        f"BLOCK idx={block.idx} lines={block.lines[0]}-{block.lines[1]} "
        f"mechanically_splittable={block.mechanically_splittable}"
    )
    remove_manifest.append("  remove_symbols=" + (", ".join(sorted(block.remove_symbols)) or "-"))

    for body_i in sorted(block.remove_body_indexes):
        child = block.node.body[body_i]
        s, e = span(child)
        binds = recursive_bound_names(child)
        remove_manifest.append(
            f"  REMOVE_CANDIDATE body[{body_i}] {type(child).__name__} lines={s}-{e} binds={', '.join(sorted(binds)) or '-'}"
        )
        remove_windows.append(
            code_window(
                f"REMOVE_CANDIDATE block_idx={block.idx} body[{body_i}] binds={', '.join(sorted(binds)) or '-'}",
                child,
            )
        )

    remove_manifest.append("")

(out / "03_preserve_substatement_manifest.txt").write_text(
    "\n".join(preserve_manifest) + "\n",
    encoding="utf-8",
)

(out / "04_remove_candidate_substatement_manifest.txt").write_text(
    "\n".join(remove_manifest) + "\n",
    encoding="utf-8",
)

(out / "05_preserve_source_windows.txt").write_text(
    "\n".join(preserve_windows) + "\n",
    encoding="utf-8",
)

(out / "06_remove_candidate_source_windows.txt").write_text(
    "\n".join(remove_windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Legacy adapter chain audit
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

adapter_inventory = [
    "=== PHASE 45b LEGACY ADAPTER CHAIN TRANSITIVE LIVENESS INVENTORY ===",
    "",
    "group | postmarker_ast_hits | postmarker_text_hits | classification",
    "-" * 220,
]

pre_marker_source = "\n".join(lines[:PHASE38_LINE - 1])

adapter_actionable_delete_candidate_count = 0
adapter_catalogue_only_absent_count = 0
adapter_retain_or_review_count = 0

adapter_source_presence_reconciliation = [
    "=== PHASE 45b LEGACY ADAPTER CHAIN SOURCE-PRESENCE RECONCILIATION ===",
    "",
    "group | premarker_source_hits | postmarker_source_hits | classification",
    "-" * 240,
]

for group_name, symbols in adapter_groups.items():
    ast_hits = sorted(symbols & post_marker_ast_loads)
    text_hits = sorted(sym for sym in symbols if re.search(rf"\b{re.escape(sym)}\b", post_marker_source))

    pre_source_hits = sorted(
        sym for sym in symbols
        if re.search(rf"\b{re.escape(sym)}\b", pre_marker_source)
    )
    post_source_hits = sorted(
        sym for sym in symbols
        if re.search(rf"\b{re.escape(sym)}\b", post_marker_source)
    )

    has_current_source_presence = bool(pre_source_hits or post_source_hits)
    has_postmarker_liveness = bool(ast_hits or text_hits)

    if has_postmarker_liveness:
        classification = "RETAIN_OR_DEEPER_REVIEW"
        adapter_retain_or_review_count += 1
    elif has_current_source_presence:
        classification = "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN"
        adapter_actionable_delete_candidate_count += 1
    else:
        classification = "CATALOGUE_ONLY_SOURCE_ALREADY_ABSENT"
        adapter_catalogue_only_absent_count += 1

    adapter_inventory.append(
        f"{group_name} | "
        f"{', '.join(ast_hits) or '-'} | "
        f"{', '.join(text_hits) or '-'} | "
        f"{classification}"
    )

    adapter_source_presence_reconciliation.append(
        f"{group_name} | "
        f"{', '.join(pre_source_hits) or '-'} | "
        f"{', '.join(post_source_hits) or '-'} | "
        f"{classification}"
    )

(out / "07_legacy_adapter_chain_transitive_liveness_inventory.txt").write_text(
    "\n".join(adapter_inventory) + "\n",
    encoding="utf-8",
)

(out / "07b_legacy_adapter_chain_source_presence_reconciliation.txt").write_text(
    "\n".join(adapter_source_presence_reconciliation) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Residual symbol hit lines before Phase38
# ---------------------------------------------------------------------

capture_re = re.compile(
    r"\b(?:"
    r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)|"
    r"_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)"
    r")\b"
)

capture_hits: list[str] = []
for line_no, line in enumerate(lines[:PHASE38_LINE - 1], start=1):
    if capture_re.search(line):
        capture_hits.append(f"{line_no}:{line}")

(out / "08_residual_route_capture_symbol_hits.txt").write_text(
    "\n".join([
        "=== PHASE 45b RESIDUAL ROUTE CAPTURE SYMBOL HITS ===",
        f"HIT_LINE_COUNT={len(capture_hits)}",
        "",
        *capture_hits,
    ]) + "\n",
    encoding="utf-8",
)

alias_re = re.compile(
    r"^\s*(?:route_intent|route_command|parse_command|classify)\s*=\s*"
)

alias_hits: list[str] = []
for line_no, line in enumerate(lines[:PHASE38_LINE - 1], start=1):
    if alias_re.search(line):
        alias_hits.append(f"{line_no}:{line}")

(out / "09_residual_public_alias_rebinding_hits.txt").write_text(
    "\n".join([
        "=== PHASE 45b RESIDUAL PUBLIC ALIAS REBINDING HITS ===",
        f"HIT_LINE_COUNT={len(alias_hits)}",
        "",
        *alias_hits,
    ]) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Runtime public surface identity probe
# ---------------------------------------------------------------------

router_mod = importlib.import_module("eli.execution.router_enhanced")
surface_names = ["route", "route_intent", "route_command", "parse_command", "classify"]
base = getattr(router_mod, "route")

identity_lines = [
    "=== PHASE 45b RUNTIME PUBLIC SURFACE IDENTITY PROBE ===",
]

for name in surface_names:
    fn = getattr(router_mod, name, None)
    code = getattr(fn, "__code__", None)
    identity_lines.append(
        f"{name}: callable={callable(fn)} same_as_route={fn is base} "
        f"id={id(fn) if callable(fn) else None} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"firstlineno={getattr(code, 'co_firstlineno', None)}"
    )

all_same = all(getattr(router_mod, name, None) is base for name in surface_names)
identity_lines.append("")
identity_lines.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all_same}")

(out / "10_runtime_public_surface_identity_probe.txt").write_text(
    "\n".join(identity_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Conclusion / digest
# ---------------------------------------------------------------------

splittable_count = sum(1 for block in mixed_blocks if block.mechanically_splittable)
manual_count = len(mixed_blocks) - splittable_count

adapter_delete_candidate_count = sum(
    1 for line in adapter_inventory
    if "PROBABLE_PHASE46_GUARDED_DELETE_CHAIN" in line
)

# Phase55b correction:
# Only source-present adapter groups with no post-marker liveness are actionable
# guarded-delete candidates. Catalogue-only absent rows must not inflate this count.
adapter_delete_candidate_count = adapter_actionable_delete_candidate_count

conclusion = [
    "=== PHASE 45b CONCLUSION ===",
    f"PHASE38_MARKER_LINE={PHASE38_LINE}",
    "",
    f"Mixed pre-Phase38 Try blocks with post-marker live binds: {len(mixed_blocks)}",
    f"Mechanically splittable mixed blocks: {splittable_count}",
    f"Blocks requiring manual/deeper handling: {manual_count}",
    "",
    f"Residual route-capture symbol hit lines before Phase38: {len(capture_hits)}",
    f"Residual public alias rebinding hit lines before Phase38: {len(alias_hits)}",
    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
    "",
    "Interpretation:",
    "- This audit replaces Phase 45 v1's false-zero direct-load test.",
    "- Phase46 should be based on the transitive post-marker liveness matrix in this report.",
    "- Mechanically splittable mixed blocks are candidates for helper extraction + dead shell removal.",
    "- Only source-present adapter groups with no post-marker AST/text liveness count as actionable guarded-delete candidates.",
    "- Catalogue-only already-absent rows are retired inventory residue, not remaining router source debt.",
    "- No source files were modified in Phase 45b.",
]

(out / "11_phase45b_conclusion.txt").write_text(
    "\n".join(conclusion) + "\n",
    encoding="utf-8",
)

digest = [
    "=== PHASE 45b DIGEST ===",
    "Router compile: PASS",
    "Audit mode: PASS",
    "No source files modified: PASS",
    "",
    f"Mixed pre-Phase38 Try blocks with post-marker live binds: {len(mixed_blocks)}",
    f"Mechanically splittable mixed blocks: {splittable_count}",
    f"Blocks requiring manual/deeper handling: {manual_count}",
    "",
    f"Residual route-capture symbol hit lines before Phase38: {len(capture_hits)}",
    f"Residual public alias rebinding hit lines before Phase38: {len(alias_hits)}",
    f"Legacy adapter actionable guarded-delete candidate chains: {adapter_actionable_delete_candidate_count}",
    f"Legacy adapter catalogue-only already-absent chains: {adapter_catalogue_only_absent_count}",
    f"Legacy adapter retain/deeper-review chains: {adapter_retain_or_review_count}",
    "",
    "Review:",
    "- 02_mixed_tryblock_liveness_matrix.txt",
    "- 03_preserve_substatement_manifest.txt",
    "- 04_remove_candidate_substatement_manifest.txt",
    "- 05_preserve_source_windows.txt",
    "- 06_remove_candidate_source_windows.txt",
    "- 07_legacy_adapter_chain_transitive_liveness_inventory.txt",
    "- 07b_legacy_adapter_chain_source_presence_reconciliation.txt",
    "- 08_residual_route_capture_symbol_hits.txt",
    "- 09_residual_public_alias_rebinding_hits.txt",
    "- 10_runtime_public_surface_identity_probe.txt",
    "- 11_phase45b_conclusion.txt",
    "",
    f"PHASE45B_OUT={out}",
]

(out / "12_console_digest.txt").write_text(
    "\n".join(digest) + "\n",
    encoding="utf-8",
)

print("\n".join(digest))
PY

echo
echo "PHASE45B_OUT=$OUT"
