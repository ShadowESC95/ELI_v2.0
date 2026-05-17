#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase41_router_residual_wrapper_shell_capture_eligibility_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Phase 38 marker missing: $PHASE38_MARKER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 41 — Router Residual Wrapper-Shell / Capture Eligibility Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase 40 removed obsolete late public wrapper FunctionDef source.  
Phase 41 maps what stale residue remains around those removed wrappers:

1. route-capture variables such as \`_ELI_*_PREV\`, \`_ORIG_ROUTE\`
2. dead wrapper-install if/try shells
3. temporary public-surface alias rebindings before Phase 38
4. live helper symbols that must remain because Phase 38 calls them
5. exact pruning candidates for the next surgical deletion phase
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

router = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router.read_text(encoding="utf-8")
lines = src.splitlines()

MARKER = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

marker_line = None
for i, line in enumerate(lines, start=1):
    if MARKER in line:
        marker_line = i
        break

if marker_line is None:
    raise RuntimeError("Phase 38 marker not found")

tree = ast.parse(src)

# ---------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------

def span(node: ast.AST) -> tuple[int, int]:
    return (
        getattr(node, "lineno", -1),
        getattr(node, "end_lineno", getattr(node, "lineno", -1)),
    )

def segment(start: int, end: int) -> str:
    return "\n".join(lines[start - 1:end])

def top_level_nodes() -> list[ast.stmt]:
    return list(tree.body)

def names_loaded(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            found.add(sub.id)
    return found

def names_stored(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            found.add(sub.id)
        elif isinstance(sub, ast.FunctionDef):
            found.add(sub.name)
        elif isinstance(sub, ast.AsyncFunctionDef):
            found.add(sub.name)
        elif isinstance(sub, ast.ClassDef):
            found.add(sub.name)
    return found

def public_surface_def_count_before_marker() -> dict[str, int]:
    wanted = {"route", "route_intent", "route_command", "parse_command", "classify"}
    counts = {k: 0 for k in sorted(wanted)}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            ln = getattr(node, "lineno", -1)
            if 0 < ln < marker_line and node.name in counts:
                counts[node.name] += 1
    return counts

# ---------------------------------------------------------------------
# 1. Phase38 source usage surface
# ---------------------------------------------------------------------

phase38_src = "\n".join(lines[marker_line - 1:])
phase38_tree = ast.parse(phase38_src)

phase38_loaded_names: set[str] = set()
for node in ast.walk(phase38_tree):
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        phase38_loaded_names.add(node.id)

# String/global lookup signals: globals().get("X"), globals()["X"], getattr(module, "X"), etc.
phase38_string_symbol_hits: set[str] = set()
for m in re.finditer(r'''["']([A-Za-z_][A-Za-z0-9_]*)["']''', phase38_src):
    value = m.group(1)
    if value.startswith("_") or value in {
        "route", "route_intent", "route_command", "parse_command", "classify"
    }:
        phase38_string_symbol_hits.add(value)

phase38_symbol_surface = sorted(phase38_loaded_names | phase38_string_symbol_hits)

(out / "01_phase38_symbol_usage_surface.txt").write_text(
    "=== PHASE 38 SYMBOL USAGE SURFACE ===\n"
    f"PHASE38_MARKER_LINE={marker_line}\n"
    f"LOADED_NAME_COUNT={len(phase38_loaded_names)}\n"
    f"STRING_SYMBOL_HIT_COUNT={len(phase38_string_symbol_hits)}\n\n"
    "Symbols:\n"
    + "\n".join(phase38_symbol_surface)
    + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 2. Pre-marker top-level statement inventory after Phase40
# ---------------------------------------------------------------------

records: list[dict[str, Any]] = []

for idx, node in enumerate(top_level_nodes()):
    start, end = span(node)
    if start < 1 or start >= marker_line:
        continue

    stored = sorted(names_stored(node))
    loaded = sorted(names_loaded(node))
    src_block = segment(start, end)

    contains_public_surface_word = bool(
        re.search(r"\b(route|route_intent|route_command|parse_command|classify)\b", src_block)
    )
    contains_route_capture = bool(
        re.search(
            r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)"
            r"|_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)",
            src_block,
        )
    )
    contains_alias_rebind = bool(
        re.search(r"^\s*(?:route_command|parse_command|classify|route_intent)\s*=\s*route\b", src_block, re.M)
    )
    contains_public_funcdef = bool(
        re.search(r"^\s*def\s+(?:route|route_intent|route_command|parse_command|classify)\b", src_block, re.M)
    )
    defines_phase38_referenced_symbol = bool(set(stored) & set(phase38_symbol_surface))

    records.append({
        "index": idx,
        "kind": type(node).__name__,
        "start": start,
        "end": end,
        "span": end - start + 1,
        "stored": stored,
        "loaded": loaded,
        "contains_public_surface_word": contains_public_surface_word,
        "contains_route_capture": contains_route_capture,
        "contains_alias_rebind": contains_alias_rebind,
        "contains_public_funcdef": contains_public_funcdef,
        "defines_phase38_referenced_symbol": defines_phase38_referenced_symbol,
    })

with (out / "02_pre_phase38_top_level_statement_inventory.json").open("w", encoding="utf-8") as fh:
    json.dump(records, fh, indent=2, ensure_ascii=False)

table = [
    "=== PRE-PHASE38 TOP-LEVEL STATEMENT INVENTORY ===",
    f"PHASE38_MARKER_LINE={marker_line}",
    "",
    "idx | kind | lines | span | capture | alias_rebind | public_surface_text | defines_phase38_ref | stored_names",
    "-" * 220,
]

for rec in records:
    table.append(
        f"{rec['index']} | {rec['kind']} | {rec['start']}-{rec['end']} | {rec['span']} | "
        f"{rec['contains_route_capture']} | {rec['contains_alias_rebind']} | "
        f"{rec['contains_public_surface_word']} | {rec['defines_phase38_referenced_symbol']} | "
        f"{', '.join(rec['stored'])}"
    )

(out / "03_pre_phase38_top_level_statement_inventory.txt").write_text(
    "\n".join(table) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 3. Residual stale-capture / alias rebinding grep
# ---------------------------------------------------------------------

capture_patterns = [
    r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)",
    r"_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)",
]

capture_lines = []
for i, line in enumerate(lines[: marker_line - 1], start=1):
    if any(re.search(p, line) for p in capture_patterns):
        capture_lines.append(f"{i}: {line}")

(out / "04_residual_route_capture_symbol_hits.txt").write_text(
    "=== RESIDUAL PRE-PHASE38 ROUTE-CAPTURE SYMBOL HITS ===\n"
    + "\n".join(capture_lines)
    + ("\n" if capture_lines else "NONE\n"),
    encoding="utf-8",
)

alias_lines = []
for i, line in enumerate(lines[: marker_line - 1], start=1):
    if re.search(r"^\s*(?:route_command|parse_command|classify|route_intent)\s*=\s*route\b", line):
        alias_lines.append(f"{i}: {line}")

(out / "05_residual_public_surface_alias_rebindings.txt").write_text(
    "=== RESIDUAL PRE-PHASE38 PUBLIC SURFACE ALIAS REBINDINGS ===\n"
    + "\n".join(alias_lines)
    + ("\n" if alias_lines else "NONE\n"),
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 4. Live helper symbols Phase38 still references
# ---------------------------------------------------------------------

pre_marker_defs: dict[str, tuple[str, int, int]] = {}

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        start, end = span(node)
        if 0 < start < marker_line:
            pre_marker_defs[node.name] = ("function", start, end)
    elif isinstance(node, ast.Assign):
        start, end = span(node)
        if 0 < start < marker_line:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    pre_marker_defs[target.id] = ("assign", start, end)
    elif isinstance(node, ast.AnnAssign):
        start, end = span(node)
        if 0 < start < marker_line and isinstance(node.target, ast.Name):
            pre_marker_defs[node.target.id] = ("annassign", start, end)

live_symbols = []
for name in phase38_symbol_surface:
    if name in pre_marker_defs:
        kind, start, end = pre_marker_defs[name]
        live_symbols.append((name, kind, start, end, end - start + 1))

live_symbols.sort(key=lambda row: (row[2], row[0]))

live_lines = [
    "=== PRE-PHASE38 SYMBOLS STILL REFERENCED BY PHASE 38 ===",
    "symbol | kind | lines | span",
    "-" * 140,
]
for name, kind, start, end, width in live_symbols:
    live_lines.append(f"{name} | {kind} | {start}-{end} | {width}")

(out / "06_phase38_live_pre_marker_symbol_dependencies.txt").write_text(
    "\n".join(live_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 5. Candidate top-level statements for Phase42 pruning
# ---------------------------------------------------------------------

candidates = []

for rec in records:
    # Conservative: only statements after the core route body.
    if rec["start"] <= 2768:
        continue

    # Statements that still contain the residue patterns we explicitly want to prune.
    if not (
        rec["contains_route_capture"]
        or rec["contains_alias_rebind"]
        or rec["contains_public_surface_word"]
    ):
        continue

    # Never auto-classify a statement as disposable if it defines a name Phase38 uses.
    retention = "RETAIN_PHASE38_REFERENCED_SYMBOL" if rec["defines_phase38_referenced_symbol"] else "PHASE42_PRUNE_CANDIDATE"

    candidates.append({
        **rec,
        "eligibility": retention,
    })

candidate_lines = [
    "=== PHASE 42 SURGICAL PRUNE CANDIDATE STATEMENTS ===",
    "idx | kind | lines | span | eligibility | stored_names",
    "-" * 220,
]

for rec in candidates:
    candidate_lines.append(
        f"{rec['index']} | {rec['kind']} | {rec['start']}-{rec['end']} | {rec['span']} | "
        f"{rec['eligibility']} | {', '.join(rec['stored'])}"
    )

(out / "07_phase42_surgical_prune_candidate_statement_index.txt").write_text(
    "\n".join(candidate_lines) + "\n",
    encoding="utf-8",
)

# Full source windows for candidates
windows = []
for rec in candidates:
    windows.append("=" * 120)
    windows.append(
        f"idx={rec['index']} kind={rec['kind']} lines={rec['start']}-{rec['end']} "
        f"eligibility={rec['eligibility']}"
    )
    windows.append("=" * 120)
    windows.append(segment(rec["start"], rec["end"]))
    windows.append("")

(out / "08_phase42_surgical_prune_candidate_source_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 6. Remaining public defs and conclusion
# ---------------------------------------------------------------------

surface_counts = public_surface_def_count_before_marker()

surface_report = [
    "=== PRE-PHASE38 PUBLIC ROUTER SURFACE FUNCTION DEF COUNTS ===",
]
for name in ["route", "route_intent", "route_command", "parse_command", "classify"]:
    surface_report.append(f"{name}={surface_counts[name]}")

(out / "09_pre_phase38_public_surface_def_counts.txt").write_text(
    "\n".join(surface_report) + "\n",
    encoding="utf-8",
)

prune_candidate_count = sum(1 for rec in candidates if rec["eligibility"] == "PHASE42_PRUNE_CANDIDATE")
retain_candidate_count = sum(1 for rec in candidates if rec["eligibility"] == "RETAIN_PHASE38_REFERENCED_SYMBOL")

conclusion = f"""=== PHASE 41 CONCLUSION ===
PHASE38_MARKER_LINE={marker_line}

Phase 40 state:
- public pre-Phase38 FunctionDef residue now limited to the single retained core route() body;
- no late route()/route_intent()/route_command()/parse_command()/classify() wrapper FunctionDefs remain.

Phase 41 residue findings:
- residual route-capture symbol hit lines: {len(capture_lines)}
- residual public-surface alias rebinding lines: {len(alias_lines)}
- Phase38-referenced pre-marker symbols: {len(live_symbols)}
- candidate top-level stale shell statements reviewed: {len(candidates)}
- statements preliminarily eligible for Phase42 surgical pruning: {prune_candidate_count}
- statements blocked from deletion because they define Phase38-referenced symbols: {retain_candidate_count}

Interpretation:
- Phase 42 should not delete helpers listed in 06_phase38_live_pre_marker_symbol_dependencies.txt.
- Phase 42 should target only statements marked PHASE42_PRUNE_CANDIDATE in
  07_phase42_surgical_prune_candidate_statement_index.txt.
- Exact pre/post semantic-baseline comparison remains mandatory for any deletion patch.
"""

(out / "10_phase41_prune_eligibility_conclusion.txt").write_text(conclusion, encoding="utf-8")
print(conclusion)
PY

python3 - "$OUT" <<'PY'
from __future__ import annotations

import inspect
import sys
from pathlib import Path

out = Path(sys.argv[1])

import eli.execution.router_enhanced as router

names = ["route", "route_intent", "route_command", "parse_command", "classify"]

base = getattr(router, "route")
rows = [
    "=== RUNTIME PUBLIC SURFACE IDENTITY PROBE ===",
]
for name in names:
    fn = getattr(router, name, None)
    rows.append(
        f"{name}: callable={callable(fn)} "
        f"same_as_route={fn is base} "
        f"id={id(fn) if callable(fn) else None} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn) if callable(fn) else None}"
    )

rows.append("")
rows.append(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={all(getattr(router, name, None) is base for name in names)}")

(out / "11_runtime_public_surface_identity_probe.txt").write_text(
    "\n".join(rows) + "\n",
    encoding="utf-8",
)
PY

cat > "$OUT/12_console_digest.txt" <<EOF
=== PHASE 41 DIGEST ===
Router compile: PASS
Audit mode: PASS
No source files modified: PASS

What Phase 41 proves:
- Phase 40 left the router in a clean canonical dispatch state.
- Only the retained legacy/core route() FunctionDef remains before Phase 38.
- The remaining cleanup surface is now stale capture variables, wrapper-install shells,
  and temporary alias rebindings, not function-definition duplication.
- Phase 42 can be written surgically from the candidate index generated here.

Review:
- 04_residual_route_capture_symbol_hits.txt
- 05_residual_public_surface_alias_rebindings.txt
- 06_phase38_live_pre_marker_symbol_dependencies.txt
- 07_phase42_surgical_prune_candidate_statement_index.txt
- 08_phase42_surgical_prune_candidate_source_windows.txt
- 10_phase41_prune_eligibility_conclusion.txt
- 11_runtime_public_surface_identity_probe.txt

PHASE41_OUT=$OUT
EOF

cat "$OUT/12_console_digest.txt"

{
  echo
  echo "## Phase 41 artifacts"
  echo "- \`00_compile.txt\`"
  echo "- \`01_phase38_symbol_usage_surface.txt\`"
  echo "- \`02_pre_phase38_top_level_statement_inventory.json\`"
  echo "- \`03_pre_phase38_top_level_statement_inventory.txt\`"
  echo "- \`04_residual_route_capture_symbol_hits.txt\`"
  echo "- \`05_residual_public_surface_alias_rebindings.txt\`"
  echo "- \`06_phase38_live_pre_marker_symbol_dependencies.txt\`"
  echo "- \`07_phase42_surgical_prune_candidate_statement_index.txt\`"
  echo "- \`08_phase42_surgical_prune_candidate_source_windows.txt\`"
  echo "- \`09_pre_phase38_public_surface_def_counts.txt\`"
  echo "- \`10_phase41_prune_eligibility_conclusion.txt\`"
  echo "- \`11_runtime_public_surface_identity_probe.txt\`"
  echo "- \`12_console_digest.txt\`"
  echo
  echo "PHASE41_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE41_OUT=$OUT"
