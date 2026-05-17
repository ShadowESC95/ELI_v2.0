#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase43_router_residual_shell_liveness_split_eligibility_audit_${STAMP}"

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
# Phase 43 — Router Residual Shell Liveness / Split Eligibility Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Audit purpose

Phase 42 safely pruned only dependency-unreachable residual shell statements.
The remaining residue is likely a mixture of:

1. genuinely dependency-connected retained helpers;
2. stale capture / alias shells that survive only because they share a statement
   with live helper definitions;
3. stale rebinding statements that may be overwritten before meaningful use.

Phase 43 performs a finer audit:

- identifies residual capture-symbol statements;
- identifies residual alias-rebinding statements;
- computes per-symbol read/write liveness before Phase 38;
- distinguishes pure shell statements from mixed helper+shell blocks;
- identifies likely Phase 44 split/delete candidates;
- preserves the Phase 38 flattened dispatcher contract.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_compile.txt"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import inspect
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()

PHASE38_MARKER = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

CAPTURE_RE = re.compile(
    r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)"
    r"|_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)"
)

ALIAS_REBIND_RE = re.compile(
    r"^\s*(route_intent|route_command|parse_command|classify)\s*=\s*route\b"
)

PUBLIC_SURFACE_NAMES = {
    "route",
    "route_intent",
    "route_command",
    "parse_command",
    "classify",
}

# ---------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------

def line_span(node: ast.AST) -> tuple[int, int]:
    return (
        getattr(node, "lineno", -1),
        getattr(node, "end_lineno", getattr(node, "lineno", -1)),
    )

def source_window(start: int, end: int) -> str:
    return "\n".join(lines[start - 1:end])

def loaded_names(node: ast.AST) -> set[str]:
    result: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            result.add(sub.id)
    return result

def target_names(target: ast.AST) -> set[str]:
    out: set[str] = set()
    if isinstance(target, ast.Name):
        out.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            out |= target_names(elt)
    return out

def module_scope_bindings(node: ast.AST) -> set[str]:
    """
    Names bound by a top-level statement.
    Descends through top-level control-flow blocks, but not through function/class bodies.
    """
    out: set[str] = set()

    if isinstance(node, ast.FunctionDef):
        out.add(node.name)
        return out

    if isinstance(node, ast.AsyncFunctionDef):
        out.add(node.name)
        return out

    if isinstance(node, ast.ClassDef):
        out.add(node.name)
        return out

    if isinstance(node, ast.Assign):
        for target in node.targets:
            out |= target_names(target)
        return out

    if isinstance(node, ast.AnnAssign):
        out |= target_names(node.target)
        return out

    if isinstance(node, ast.AugAssign):
        out |= target_names(node.target)
        return out

    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            out.add(alias.asname or alias.name.split(".")[0])
        return out

    if isinstance(node, ast.If):
        for stmt in node.body:
            out |= module_scope_bindings(stmt)
        for stmt in node.orelse:
            out |= module_scope_bindings(stmt)
        return out

    if isinstance(node, ast.Try):
        for stmt in node.body:
            out |= module_scope_bindings(stmt)
        for handler in node.handlers:
            for stmt in handler.body:
                out |= module_scope_bindings(stmt)
        for stmt in node.orelse:
            out |= module_scope_bindings(stmt)
        for stmt in node.finalbody:
            out |= module_scope_bindings(stmt)
        return out

    if isinstance(node, (ast.For, ast.AsyncFor)):
        out |= target_names(node.target)
        for stmt in node.body:
            out |= module_scope_bindings(stmt)
        for stmt in node.orelse:
            out |= module_scope_bindings(stmt)
        return out

    if isinstance(node, ast.While):
        for stmt in node.body:
            out |= module_scope_bindings(stmt)
        for stmt in node.orelse:
            out |= module_scope_bindings(stmt)
        return out

    if hasattr(ast, "Match") and isinstance(node, ast.Match):
        for case in node.cases:
            for stmt in case.body:
                out |= module_scope_bindings(stmt)
        return out

    return out

def nested_function_defs(node: ast.AST) -> list[str]:
    out_names: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.FunctionDef):
            out_names.append(sub.name)
    return out_names

def extract_dynamic_lookup_names(text: str) -> set[str]:
    result: set[str] = set()
    patterns = [
        r'globals\(\)\.get\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']',
        r'globals\(\)\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']\s*\]',
        r'getattr\([^,\n]+,\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            result.add(match.group(1))
    return result

# ---------------------------------------------------------------------
# Locate Phase 38 marker and retained core route()
# ---------------------------------------------------------------------

phase38_marker_line = None
for i, line in enumerate(lines, start=1):
    if PHASE38_MARKER in line:
        phase38_marker_line = i
        break

if phase38_marker_line is None:
    raise RuntimeError("Phase 38 marker not found")

tree = ast.parse(src)

pre_marker_top_level = [
    node for node in tree.body
    if getattr(node, "lineno", -1) < phase38_marker_line
]

pre_marker_route_defs = [
    node for node in pre_marker_top_level
    if isinstance(node, ast.FunctionDef)
    and node.name == "route"
]

if len(pre_marker_route_defs) != 1:
    raise RuntimeError(
        f"Expected exactly one pre-Phase38 retained core route() FunctionDef; found {len(pre_marker_route_defs)}"
    )

core_route = pre_marker_route_defs[0]
core_start, core_end = line_span(core_route)

# ---------------------------------------------------------------------
# Phase 38 live symbol surface
# ---------------------------------------------------------------------

phase38_src = "\n".join(lines[phase38_marker_line - 1:])
phase38_tree = ast.parse(phase38_src)

phase38_loaded_names = loaded_names(phase38_tree)
phase38_dynamic_names = extract_dynamic_lookup_names(phase38_src)
phase38_required_names = phase38_loaded_names | phase38_dynamic_names

(out / "01_phase38_required_symbol_surface.txt").write_text(
    "=== PHASE 38 REQUIRED SYMBOL SURFACE ===\n"
    f"PHASE38_MARKER_LINE={phase38_marker_line}\n"
    f"PHASE38_AST_LOAD_NAME_COUNT={len(phase38_loaded_names)}\n"
    f"PHASE38_DYNAMIC_LOOKUP_NAME_COUNT={len(phase38_dynamic_names)}\n"
    f"PHASE38_TOTAL_REQUIRED_SYMBOL_COUNT={len(phase38_required_names)}\n\n"
    + "\n".join(sorted(phase38_required_names))
    + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Statement inventory after retained core route() and before Phase 38
# ---------------------------------------------------------------------

statement_records: list[dict[str, Any]] = []

for index, node in enumerate(tree.body):
    start, end = line_span(node)

    if start <= core_end:
        continue
    if start >= phase38_marker_line:
        continue

    text = source_window(start, end)
    binds = module_scope_bindings(node)
    loads = loaded_names(node)
    funcs = nested_function_defs(node)

    capture_hits = []
    alias_hits = []

    for line_no in range(start, end + 1):
        text_line = lines[line_no - 1]
        if CAPTURE_RE.search(text_line):
            capture_hits.append((line_no, text_line))
        if ALIAS_REBIND_RE.search(text_line):
            alias_hits.append((line_no, text_line))

    phase38_live_defs = sorted(binds & phase38_required_names)
    public_bound_names = sorted(binds & PUBLIC_SURFACE_NAMES)

    contains_residual_shell = bool(capture_hits or alias_hits)
    contains_live_phase38_defs = bool(phase38_live_defs)

    if contains_residual_shell and not contains_live_phase38_defs and not funcs:
        initial_class = "PURE_SHELL_OR_REBINDING_ONLY"
    elif contains_residual_shell and contains_live_phase38_defs:
        initial_class = "MIXED_PHASE38_LIVE_SYMBOL_PLUS_SHELL"
    elif contains_residual_shell and funcs:
        initial_class = "MIXED_HELPER_FUNCTION_PLUS_SHELL"
    elif contains_live_phase38_defs:
        initial_class = "PHASE38_LIVE_NON_SHELL"
    else:
        initial_class = "NON_SHELL_OR_AUXILIARY"

    statement_records.append({
        "index": index,
        "kind": type(node).__name__,
        "start": start,
        "end": end,
        "span": end - start + 1,
        "binds": sorted(binds),
        "loads": sorted(loads),
        "functions": funcs,
        "capture_hits": capture_hits,
        "alias_hits": alias_hits,
        "phase38_live_defs": phase38_live_defs,
        "public_bound_names": public_bound_names,
        "contains_residual_shell": contains_residual_shell,
        "contains_live_phase38_defs": contains_live_phase38_defs,
        "initial_class": initial_class,
        "text": text,
    })

# ---------------------------------------------------------------------
# Read/write liveness over statement order
# ---------------------------------------------------------------------

records_by_position = sorted(statement_records, key=lambda r: r["start"])

write_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
read_events: dict[str, list[dict[str, Any]]] = defaultdict(list)

for pos, rec in enumerate(records_by_position):
    for name in rec["binds"]:
        write_events[name].append({
            "pos": pos,
            "statement_index": rec["index"],
            "line": rec["start"],
            "end": rec["end"],
            "kind": rec["kind"],
        })
    for name in rec["loads"]:
        read_events[name].append({
            "pos": pos,
            "statement_index": rec["index"],
            "line": rec["start"],
            "end": rec["end"],
            "kind": rec["kind"],
        })

def external_read_before_next_write(name: str, rec: dict[str, Any]) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
    writes = write_events.get(name, [])
    current_write = None
    for item in writes:
        if item["statement_index"] == rec["index"]:
            current_write = item
            break

    if current_write is None:
        return False, [], None

    current_pos = current_write["pos"]
    future_writes = [w for w in writes if w["pos"] > current_pos]
    next_write = future_writes[0] if future_writes else None
    next_write_pos = next_write["pos"] if next_write else None

    reads = []
    for read in read_events.get(name, []):
        if read["statement_index"] == rec["index"]:
            continue
        if read["pos"] <= current_pos:
            continue
        if next_write_pos is not None and read["pos"] >= next_write_pos:
            continue
        reads.append(read)

    phase38_uses_name = name in phase38_required_names and next_write is None

    return bool(reads or phase38_uses_name), reads, next_write

# Enrich each residual-shell statement with symbol liveness.
for rec in records_by_position:
    symbol_liveness: dict[str, Any] = {}
    bound_names_to_check = set(rec["binds"])

    for name in sorted(bound_names_to_check):
        live, reads, next_write = external_read_before_next_write(name, rec)
        symbol_liveness[name] = {
            "live_before_overwrite_or_marker": live,
            "external_reads_before_next_write": reads,
            "next_write": next_write,
            "phase38_directly_requires_name": name in phase38_required_names,
        }

    rec["symbol_liveness"] = symbol_liveness

# ---------------------------------------------------------------------
# Refined statement classification
# ---------------------------------------------------------------------

for rec in records_by_position:
    if not rec["contains_residual_shell"]:
        rec["phase43_classification"] = "NOT_RESIDUAL_SHELL"
        continue

    bound_names = rec["binds"]
    liveness_map = rec["symbol_liveness"]

    any_bound_name_live = any(
        detail["live_before_overwrite_or_marker"]
        for detail in liveness_map.values()
    )

    has_phase38_live_defs = bool(rec["phase38_live_defs"])
    has_functions = bool(rec["functions"])

    if not any_bound_name_live and not has_phase38_live_defs and not has_functions:
        rec["phase43_classification"] = "LIKELY_PHASE44_DELETE_CANDIDATE__PURE_DEAD_SHELL"
    elif not any_bound_name_live and has_functions:
        rec["phase43_classification"] = "LIKELY_PHASE44_SPLIT_CANDIDATE__HELPER_LIVE_SHELL_DEAD"
    elif not any_bound_name_live and has_phase38_live_defs:
        rec["phase43_classification"] = "LIKELY_PHASE44_SPLIT_CANDIDATE__PHASE38_SYMBOL_LIVE_SHELL_DEAD"
    elif any_bound_name_live and (has_functions or has_phase38_live_defs):
        rec["phase43_classification"] = "MIXED_LIVE_BLOCK__MANUAL_SPLIT_OR_RETAIN"
    elif any_bound_name_live:
        rec["phase43_classification"] = "RESIDUAL_SHELL_WRITE_READ_BEFORE_OVERWRITE__RETAIN_OR_DEEPER_REVIEW"
    else:
        rec["phase43_classification"] = "UNCLASSIFIED_REVIEW"

# ---------------------------------------------------------------------
# Report files
# ---------------------------------------------------------------------

residual_records = [r for r in records_by_position if r["contains_residual_shell"]]

matrix_lines = [
    "=== PHASE 43 RESIDUAL SHELL STATEMENT MATRIX ===",
    f"PHASE38_MARKER_LINE={phase38_marker_line}",
    f"CORE_ROUTE_LINES={core_start}-{core_end}",
    f"RESIDUAL_SHELL_STATEMENT_COUNT={len(residual_records)}",
    "",
    "idx | kind | lines | span | classification | binds | phase38_live_defs | nested_function_defs",
    "-" * 260,
]

for rec in residual_records:
    matrix_lines.append(
        f"{rec['index']} | {rec['kind']} | {rec['start']}-{rec['end']} | {rec['span']} | "
        f"{rec['phase43_classification']} | "
        f"{', '.join(rec['binds']) or '-'} | "
        f"{', '.join(rec['phase38_live_defs']) or '-'} | "
        f"{', '.join(rec['functions']) or '-'}"
    )

(out / "02_residual_shell_statement_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

liveness_lines = [
    "=== PHASE 43 SYMBOL WRITE-LIVENESS TABLE ===",
    "statement_idx | lines | symbol | live_before_overwrite_or_marker | phase38_direct_requirement | next_write | external_reads_before_next_write",
    "-" * 280,
]

for rec in residual_records:
    for name, detail in rec["symbol_liveness"].items():
        next_write = detail["next_write"]
        next_write_text = (
            f"{next_write['line']}-{next_write['end']} idx={next_write['statement_index']}"
            if next_write else "NONE"
        )
        reads = detail["external_reads_before_next_write"]
        read_text = (
            ", ".join(f"{r['line']}-{r['end']} idx={r['statement_index']}" for r in reads)
            if reads else "NONE"
        )
        liveness_lines.append(
            f"{rec['index']} | {rec['start']}-{rec['end']} | {name} | "
            f"{detail['live_before_overwrite_or_marker']} | "
            f"{detail['phase38_directly_requires_name']} | "
            f"{next_write_text} | {read_text}"
        )

(out / "03_symbol_write_liveness_table.txt").write_text(
    "\n".join(liveness_lines) + "\n",
    encoding="utf-8",
)

alias_timeline_lines = [
    "=== PHASE 43 PUBLIC ALIAS REBIND TIMELINE ===",
    "symbol | write_order",
    "-" * 200,
]

for symbol in ["route_intent", "route_command", "parse_command", "classify"]:
    writes = write_events.get(symbol, [])
    if not writes:
        alias_timeline_lines.append(f"{symbol} | NONE")
        continue
    chain = " -> ".join(
        f"idx={w['statement_index']}@{w['line']}-{w['end']}"
        for w in writes
    )
    alias_timeline_lines.append(f"{symbol} | {chain}")

(out / "04_public_alias_rebind_timeline.txt").write_text(
    "\n".join(alias_timeline_lines) + "\n",
    encoding="utf-8",
)

capture_name_set = set()
for rec in residual_records:
    for name in rec["binds"]:
        if CAPTURE_RE.search(name):
            capture_name_set.add(name)

capture_timeline_lines = [
    "=== PHASE 43 CAPTURE SYMBOL WRITE / READ TIMELINE ===",
    "symbol | writes | reads",
    "-" * 260,
]

for symbol in sorted(capture_name_set):
    writes = write_events.get(symbol, [])
    reads = read_events.get(symbol, [])

    writes_text = (
        " -> ".join(f"idx={w['statement_index']}@{w['line']}-{w['end']}" for w in writes)
        if writes else "NONE"
    )
    reads_text = (
        " -> ".join(f"idx={r['statement_index']}@{r['line']}-{r['end']}" for r in reads)
        if reads else "NONE"
    )
    capture_timeline_lines.append(f"{symbol} | {writes_text} | {reads_text}")

(out / "05_capture_symbol_timeline.txt").write_text(
    "\n".join(capture_timeline_lines) + "\n",
    encoding="utf-8",
)

split_candidates = [
    r for r in residual_records
    if "SPLIT_CANDIDATE" in r["phase43_classification"]
    or r["phase43_classification"] == "MIXED_LIVE_BLOCK__MANUAL_SPLIT_OR_RETAIN"
]

delete_candidates = [
    r for r in residual_records
    if r["phase43_classification"] == "LIKELY_PHASE44_DELETE_CANDIDATE__PURE_DEAD_SHELL"
]

split_windows = []
for rec in split_candidates:
    split_windows.append("=" * 120)
    split_windows.append(
        f"{rec['phase43_classification']} | idx={rec['index']} | "
        f"{rec['kind']} | lines={rec['start']}-{rec['end']}"
    )
    split_windows.append("=" * 120)
    split_windows.append(rec["text"])
    split_windows.append("")

(out / "06_split_candidate_source_windows.txt").write_text(
    "\n".join(split_windows) + "\n" if split_windows else "NONE\n",
    encoding="utf-8",
)

delete_windows = []
for rec in delete_candidates:
    delete_windows.append("=" * 120)
    delete_windows.append(
        f"{rec['phase43_classification']} | idx={rec['index']} | "
        f"{rec['kind']} | lines={rec['start']}-{rec['end']}"
    )
    delete_windows.append("=" * 120)
    delete_windows.append(rec["text"])
    delete_windows.append("")

(out / "07_delete_candidate_source_windows.txt").write_text(
    "\n".join(delete_windows) + "\n" if delete_windows else "NONE\n",
    encoding="utf-8",
)

json_payload = []
for rec in residual_records:
    json_payload.append({
        "index": rec["index"],
        "kind": rec["kind"],
        "start": rec["start"],
        "end": rec["end"],
        "span": rec["span"],
        "binds": rec["binds"],
        "loads": rec["loads"],
        "functions": rec["functions"],
        "phase38_live_defs": rec["phase38_live_defs"],
        "capture_hit_count": len(rec["capture_hits"]),
        "alias_hit_count": len(rec["alias_hits"]),
        "phase43_classification": rec["phase43_classification"],
        "symbol_liveness": rec["symbol_liveness"],
    })

(out / "08_residual_shell_audit.json").write_text(
    json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Runtime public surface identity probe
# ---------------------------------------------------------------------

import eli.execution.router_enhanced as router

names = ["route", "route_intent", "route_command", "parse_command", "classify"]
base = getattr(router, "route")

identity_lines = [
    "=== PHASE 43 RUNTIME PUBLIC SURFACE IDENTITY PROBE ===",
]

for name in names:
    fn = getattr(router, name, None)
    identity_lines.append(
        f"{name}: callable={callable(fn)} "
        f"same_as_route={fn is base} "
        f"id={id(fn) if callable(fn) else None} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else None}"
    )

identity_lines.append("")
identity_lines.append(
    "ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT="
    f"{all(getattr(router, name, None) is base for name in names)}"
)

(out / "09_runtime_public_surface_identity_probe.txt").write_text(
    "\n".join(identity_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Conclusion digest
# ---------------------------------------------------------------------

classification_counts: dict[str, int] = defaultdict(int)
for rec in residual_records:
    classification_counts[rec["phase43_classification"]] += 1

conclusion_lines = [
    "=== PHASE 43 CONCLUSION ===",
    f"PHASE38_MARKER_LINE={phase38_marker_line}",
    f"CORE_ROUTE_LINES={core_start}-{core_end}",
    "",
    f"Residual shell statements audited: {len(residual_records)}",
    f"Likely Phase44 pure delete candidates: {len(delete_candidates)}",
    f"Likely Phase44 split/manual candidates: {len(split_candidates)}",
    "",
    "Classification counts:",
]

for key in sorted(classification_counts):
    conclusion_lines.append(f"- {key}: {classification_counts[key]}")

conclusion_lines.extend([
    "",
    "Interpretation:",
    "- Phase 42 proved coarse dependency closure is safe but conservative.",
    "- Phase 43 now isolates the residual shell statements by execution/liveness shape.",
    "- Pure dead shells can be considered for Phase 44 deletion.",
    "- Mixed helper+shell statements should not be deleted wholesale; they require source splitting.",
    "- No source files were modified in Phase 43.",
])

(out / "10_phase43_liveness_split_eligibility_conclusion.txt").write_text(
    "\n".join(conclusion_lines) + "\n",
    encoding="utf-8",
)

console_digest = "\n".join([
    "=== PHASE 43 DIGEST ===",
    "Router compile: PASS",
    "Audit mode: PASS",
    "No source files modified: PASS",
    "",
    f"Residual shell statements audited: {len(residual_records)}",
    f"Likely Phase44 pure delete candidates: {len(delete_candidates)}",
    f"Likely Phase44 split/manual candidates: {len(split_candidates)}",
    "",
    "What Phase 43 provides:",
    "- a statement-by-statement residual shell matrix;",
    "- per-symbol read/write liveness before Phase 38;",
    "- public alias rebinding timelines;",
    "- capture-symbol timelines;",
    "- exact source windows for probable Phase 44 delete/split targets.",
    "",
    "Review:",
    "- 02_residual_shell_statement_matrix.txt",
    "- 03_symbol_write_liveness_table.txt",
    "- 04_public_alias_rebind_timeline.txt",
    "- 05_capture_symbol_timeline.txt",
    "- 06_split_candidate_source_windows.txt",
    "- 07_delete_candidate_source_windows.txt",
    "- 09_runtime_public_surface_identity_probe.txt",
    "- 10_phase43_liveness_split_eligibility_conclusion.txt",
    "",
    f"PHASE43_OUT={out}",
])

(out / "11_console_digest.txt").write_text(
    console_digest + "\n",
    encoding="utf-8",
)

print(console_digest)
PY

{
  echo
  echo "## Phase 43 artifacts"
  echo "- \`00_compile.txt\`"
  echo "- \`01_phase38_required_symbol_surface.txt\`"
  echo "- \`02_residual_shell_statement_matrix.txt\`"
  echo "- \`03_symbol_write_liveness_table.txt\`"
  echo "- \`04_public_alias_rebind_timeline.txt\`"
  echo "- \`05_capture_symbol_timeline.txt\`"
  echo "- \`06_split_candidate_source_windows.txt\`"
  echo "- \`07_delete_candidate_source_windows.txt\`"
  echo "- \`08_residual_shell_audit.json\`"
  echo "- \`09_runtime_public_surface_identity_probe.txt\`"
  echo "- \`10_phase43_liveness_split_eligibility_conclusion.txt\`"
  echo "- \`11_console_digest.txt\`"
  echo
  echo "PHASE43_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE43_OUT=$OUT"
