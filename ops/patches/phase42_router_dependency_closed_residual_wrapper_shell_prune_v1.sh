#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase42_router_dependency_closed_residual_wrapper_shell_prune_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT/backups"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if [[ ! -f "$PHASE36_SCRIPT" ]]; then
  echo "Missing Phase 36 baseline script: $PHASE36_SCRIPT" >&2
  exit 1
fi

if ! grep -q "$PHASE38_MARKER" "$ROUTER"; then
  echo "Phase 38 marker missing: $PHASE38_MARKER" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase42.bak"

PATCH_WRITTEN=0

rollback_on_error() {
  code=$?
  if [[ "$PATCH_WRITTEN" == "1" ]]; then
    cp "$OUT/backups/router_enhanced.py.before_phase42.bak" "$ROUTER"
    echo
    echo "[PHASE42][ROLLBACK] Router source restored from backup after failure." >&2
  fi
  exit "$code"
}

trap rollback_on_error ERR

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 42 — Router Dependency-Closed Residual Wrapper-Shell Prune

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase 40 removed obsolete public wrapper FunctionDefs.  
Phase 41 proved residual source debt remains:

- stale route-capture variables;
- dead wrapper-install shells;
- temporary alias rebindings;
- wrapper helper shells no longer needed by the flattened Phase 38 dispatcher.

Phase 42 removes only those residual statements that are proven unnecessary by
dependency closure. It does **not** blindly delete all Phase 41 preliminary candidates.

Safety contract:

1. Capture Phase 36 semantic baseline before patch.
2. Compute candidate deletion set.
3. Preserve every candidate statement still required by:
   - Phase 38 symbol usage;
   - retained pre-Phase38 statements;
   - transitive dependencies of retained candidate statements.
4. Delete only dependency-unreachable candidate statements.
5. Re-run Phase 36 semantic baseline.
6. Require raw and parsed JSON exact equality.
7. Roll back router source automatically if any verification fails.
EOF

echo "=== PRE-PATCH PY_COMPILE ===" | tee "$OUT/00_pre_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_pre_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_pre_compile.txt"

echo "=== PRE-PATCH PHASE 36 BASELINE ===" | tee "$OUT/01_pre_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/01_pre_phase36_console.txt"

PRE36_OUT="$(
  grep -E '^PHASE36_V2_OUT=' "$OUT/01_pre_phase36_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PRE36_OUT:-}" || ! -d "$PRE36_OUT" ]]; then
  echo "Could not resolve PRE Phase 36 output directory." >&2
  exit 1
fi

PRE_JSON="$PRE36_OUT/05_router_flattening_semantic_baseline.json"

if [[ ! -f "$PRE_JSON" ]]; then
  echo "Missing PRE semantic baseline JSON: $PRE_JSON" >&2
  exit 1
fi

cp "$PRE_JSON" "$OUT/02_pre_phase36_semantic_baseline.json"

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

router = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router.read_text(encoding="utf-8")
lines = src.splitlines()

PHASE38_MARKER = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

# ---------------------------------------------------------------------
# Basic source structure
# ---------------------------------------------------------------------

marker_line = None
for i, line in enumerate(lines, start=1):
    if PHASE38_MARKER in line:
        marker_line = i
        break

if marker_line is None:
    raise RuntimeError("Phase 38 marker not found")

tree = ast.parse(src)

def span(node: ast.AST) -> tuple[int, int]:
    return (
        getattr(node, "lineno", -1),
        getattr(node, "end_lineno", getattr(node, "lineno", -1)),
    )

def block_text(start: int, end: int) -> str:
    return "\n".join(lines[start - 1:end])

# Phase 40 should leave one retained core route() before Phase 38.
pre_marker_route_defs = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "route"
    and getattr(node, "lineno", -1) < marker_line
]

if len(pre_marker_route_defs) != 1:
    raise RuntimeError(
        f"Expected exactly one pre-Phase38 top-level core route() after Phase40; found {len(pre_marker_route_defs)}"
    )

core_route_node = pre_marker_route_defs[0]
core_route_start, core_route_end = span(core_route_node)

# ---------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------

def loaded_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            found.add(sub.id)
    return found

def binding_names_from_target(target: ast.AST) -> set[str]:
    result: set[str] = set()
    if isinstance(target, ast.Name):
        result.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            result |= binding_names_from_target(elt)
    return result

def module_bindings(node: ast.AST) -> set[str]:
    """
    Return names this top-level statement can bind at module scope.

    This descends into control-flow suites because those execute at module level,
    but does NOT descend into function/class bodies for their local assignments.
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
            out |= binding_names_from_target(target)
        return out

    if isinstance(node, ast.AnnAssign):
        out |= binding_names_from_target(node.target)
        return out

    if isinstance(node, ast.AugAssign):
        out |= binding_names_from_target(node.target)
        return out

    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            out.add(alias.asname or alias.name.split(".")[0])
        return out

    if isinstance(node, ast.If):
        for stmt in node.body:
            out |= module_bindings(stmt)
        for stmt in node.orelse:
            out |= module_bindings(stmt)
        return out

    if isinstance(node, ast.Try):
        for stmt in node.body:
            out |= module_bindings(stmt)
        for handler in node.handlers:
            for stmt in handler.body:
                out |= module_bindings(stmt)
        for stmt in node.orelse:
            out |= module_bindings(stmt)
        for stmt in node.finalbody:
            out |= module_bindings(stmt)
        return out

    if isinstance(node, (ast.For, ast.AsyncFor)):
        out |= binding_names_from_target(node.target)
        for stmt in node.body:
            out |= module_bindings(stmt)
        for stmt in node.orelse:
            out |= module_bindings(stmt)
        return out

    if isinstance(node, ast.While):
        for stmt in node.body:
            out |= module_bindings(stmt)
        for stmt in node.orelse:
            out |= module_bindings(stmt)
        return out

    if hasattr(ast, "Match") and isinstance(node, ast.Match):
        for case in node.cases:
            for stmt in case.body:
                out |= module_bindings(stmt)
        return out

    return out

# ---------------------------------------------------------------------
# Phase 38 symbol usage
# ---------------------------------------------------------------------

phase38_src = "\n".join(lines[marker_line - 1:])
phase38_tree = ast.parse(phase38_src)

phase38_loaded = loaded_names(phase38_tree)

# Narrow string-symbol extraction: only dynamic symbol lookup patterns.
phase38_dynamic_lookup_names: set[str] = set()

lookup_patterns = [
    r'globals\(\)\.get\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']',
    r'globals\(\)\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']\s*\]',
    r'getattr\([^,\n]+,\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']',
]

for pattern in lookup_patterns:
    for match in re.finditer(pattern, phase38_src):
        phase38_dynamic_lookup_names.add(match.group(1))

phase38_required_names = set(phase38_loaded) | set(phase38_dynamic_lookup_names)

(out / "03_phase38_required_symbol_surface.txt").write_text(
    "=== PHASE 38 REQUIRED SYMBOL SURFACE ===\n"
    f"PHASE38_MARKER_LINE={marker_line}\n"
    f"AST_LOADED_NAME_COUNT={len(phase38_loaded)}\n"
    f"DYNAMIC_LOOKUP_NAME_COUNT={len(phase38_dynamic_lookup_names)}\n"
    f"TOTAL_REQUIRED_SYMBOL_COUNT={len(phase38_required_names)}\n\n"
    + "\n".join(sorted(phase38_required_names))
    + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Candidate identification
# ---------------------------------------------------------------------

capture_re = re.compile(
    r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)"
    r"|_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)"
)

alias_rebind_re = re.compile(
    r"^\s*(?:route_command|parse_command|classify|route_intent)\s*=\s*route\b",
    re.M,
)

public_surface_word_re = re.compile(
    r"\b(route|route_intent|route_command|parse_command|classify)\b"
)

records: list[dict[str, Any]] = []

for idx, node in enumerate(tree.body):
    start, end = span(node)

    if start < 1 or start >= marker_line:
        continue

    text = block_text(start, end)

    rec = {
        "index": idx,
        "kind": type(node).__name__,
        "start": start,
        "end": end,
        "span": end - start + 1,
        "stored": sorted(module_bindings(node)),
        "loaded": sorted(loaded_names(node)),
        "text": text,
        "contains_capture": bool(capture_re.search(text)),
        "contains_alias_rebind": bool(alias_rebind_re.search(text)),
        "contains_public_surface_word": bool(public_surface_word_re.search(text)),
        "candidate": False,
    }

    # Only post-core-route statements are eligible for shell pruning.
    if start > core_route_end and (
        rec["contains_capture"]
        or rec["contains_alias_rebind"]
        or rec["contains_public_surface_word"]
    ):
        rec["candidate"] = True

    records.append(rec)

candidates = [r for r in records if r["candidate"]]
non_candidates = [r for r in records if not r["candidate"]]

# ---------------------------------------------------------------------
# Dependency closure
# ---------------------------------------------------------------------

# Anything loaded by a non-candidate retained statement is a required name.
required_names = set(phase38_required_names)

for rec in non_candidates:
    required_names.update(rec["loaded"])

retained_candidate_ids: set[int] = set()

changed = True
while changed:
    changed = False

    for rec in candidates:
        idx = rec["index"]
        if idx in retained_candidate_ids:
            continue

        stored = set(rec["stored"])
        if stored & required_names:
            retained_candidate_ids.add(idx)
            required_names.update(rec["loaded"])
            changed = True

retained_candidates = [r for r in candidates if r["index"] in retained_candidate_ids]
prune_candidates = [r for r in candidates if r["index"] not in retained_candidate_ids]

if not prune_candidates:
    raise RuntimeError(
        "Dependency closure found no safe residual wrapper-shell statements to prune. "
        "Refusing to produce a no-op patch."
    )

# ---------------------------------------------------------------------
# Persist candidate analysis
# ---------------------------------------------------------------------

summary_rows = [
    "=== PHASE 42 DEPENDENCY-CLOSED CANDIDATE CLASSIFICATION ===",
    f"PHASE38_MARKER_LINE={marker_line}",
    f"CORE_ROUTE_LINES={core_route_start}-{core_route_end}",
    f"TOTAL_CANDIDATE_STATEMENTS={len(candidates)}",
    f"RETAINED_BY_DEPENDENCY_CLOSURE={len(retained_candidates)}",
    f"SAFE_TO_PRUNE_BY_DEPENDENCY_CLOSURE={len(prune_candidates)}",
    "",
    "idx | kind | lines | span | classification | stored_names",
    "-" * 240,
]

for rec in candidates:
    classification = (
        "RETAIN_DEPENDENCY_CLOSED"
        if rec["index"] in retained_candidate_ids
        else "PRUNE_DEPENDENCY_UNREACHABLE"
    )
    summary_rows.append(
        f"{rec['index']} | {rec['kind']} | {rec['start']}-{rec['end']} | {rec['span']} | "
        f"{classification} | {', '.join(rec['stored'])}"
    )

(out / "04_dependency_closed_candidate_classification.txt").write_text(
    "\n".join(summary_rows) + "\n",
    encoding="utf-8",
)

json_records = []
for rec in candidates:
    json_records.append({
        "index": rec["index"],
        "kind": rec["kind"],
        "start": rec["start"],
        "end": rec["end"],
        "span": rec["span"],
        "stored": rec["stored"],
        "loaded": rec["loaded"],
        "classification": (
            "RETAIN_DEPENDENCY_CLOSED"
            if rec["index"] in retained_candidate_ids
            else "PRUNE_DEPENDENCY_UNREACHABLE"
        ),
    })

(out / "05_dependency_closed_candidate_classification.json").write_text(
    json.dumps(json_records, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

retained_windows = []
for rec in retained_candidates:
    retained_windows.append("=" * 120)
    retained_windows.append(
        f"RETAIN idx={rec['index']} kind={rec['kind']} lines={rec['start']}-{rec['end']}"
    )
    retained_windows.append("=" * 120)
    retained_windows.append(rec["text"])
    retained_windows.append("")

(out / "06_retained_candidate_source_windows.txt").write_text(
    "\n".join(retained_windows) + "\n",
    encoding="utf-8",
)

pruned_windows = []
for rec in prune_candidates:
    pruned_windows.append("=" * 120)
    pruned_windows.append(
        f"PRUNE idx={rec['index']} kind={rec['kind']} lines={rec['start']}-{rec['end']}"
    )
    pruned_windows.append("=" * 120)
    pruned_windows.append(rec["text"])
    pruned_windows.append("")

(out / "07_pruned_candidate_source_windows.txt").write_text(
    "\n".join(pruned_windows) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Apply deletion
# ---------------------------------------------------------------------

remove_lines: set[int] = set()
for rec in prune_candidates:
    remove_lines.update(range(rec["start"], rec["end"] + 1))

new_lines = [
    line for i, line in enumerate(lines, start=1)
    if i not in remove_lines
]

new_src = "\n".join(new_lines) + ("\n" if src.endswith("\n") else "")

# Parse before write.
ast.parse(new_src)

router.write_text(new_src, encoding="utf-8")

(out / "08_phase42_patch_application_summary.txt").write_text(
    "=== PHASE 42 PATCH APPLICATION SUMMARY ===\n"
    f"Router source rewritten: YES\n"
    f"Deleted top-level stale-shell candidate statements: {len(prune_candidates)}\n"
    f"Deleted source lines: {len(remove_lines)}\n"
    f"Retained dependency-closed candidate statements: {len(retained_candidates)}\n"
    f"Original Phase38 marker line: {marker_line}\n",
    encoding="utf-8",
)

print("=== PHASE 42 PATCH APPLICATION SUMMARY ===")
print(f"Deleted top-level stale-shell candidate statements: {len(prune_candidates)}")
print(f"Deleted source lines: {len(remove_lines)}")
print(f"Retained dependency-closed candidate statements: {len(retained_candidates)}")
PY

PATCH_WRITTEN=1

echo "=== POST-PATCH PY_COMPILE ===" | tee "$OUT/09_post_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/09_post_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/09_post_compile.txt"

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/10_post_phase36_console.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/10_post_phase36_console.txt"

POST36_OUT="$(
  grep -E '^PHASE36_V2_OUT=' "$OUT/10_post_phase36_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${POST36_OUT:-}" || ! -d "$POST36_OUT" ]]; then
  echo "Could not resolve POST Phase 36 output directory." >&2
  exit 1
fi

POST_JSON="$POST36_OUT/05_router_flattening_semantic_baseline.json"

if [[ ! -f "$POST_JSON" ]]; then
  echo "Missing POST semantic baseline JSON: $POST_JSON" >&2
  exit 1
fi

cp "$POST_JSON" "$OUT/11_post_phase36_semantic_baseline.json"

python3 - "$OUT/02_pre_phase36_semantic_baseline.json" "$OUT/11_post_phase36_semantic_baseline.json" "$OUT" <<'PY'
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

pre_path = Path(sys.argv[1])
post_path = Path(sys.argv[2])
out = Path(sys.argv[3])

pre_raw = pre_path.read_text(encoding="utf-8")
post_raw = post_path.read_text(encoding="utf-8")

raw_equal = pre_raw == post_raw

pre_parsed = json.loads(pre_raw)
post_parsed = json.loads(post_raw)

parsed_equal = pre_parsed == post_parsed

diff_text = ""
if not raw_equal:
    diff_text = "\n".join(
        difflib.unified_diff(
            pre_raw.splitlines(),
            post_raw.splitlines(),
            fromfile=str(pre_path),
            tofile=str(post_path),
            lineterm="",
        )
    )
else:
    diff_text = "NO_DIFF"

(out / "12_phase36_semantic_baseline_exact_diff.txt").write_text(
    diff_text + ("\n" if not diff_text.endswith("\n") else ""),
    encoding="utf-8",
)

compare = f"""=== PHASE 42 EXACT SEMANTIC BASELINE COMPARISON ===
PRE_JSON={pre_path}
POST_JSON={post_path}
RAW_JSON_EQUAL={raw_equal}
PARSED_JSON_EQUAL={parsed_equal}
DIFF_WRITTEN=12_phase36_semantic_baseline_exact_diff.txt
"""

(out / "13_phase36_semantic_baseline_exact_compare.txt").write_text(
    compare,
    encoding="utf-8",
)

print(compare)

if not raw_equal or not parsed_equal:
    raise SystemExit(1)
PY

python3 - "$ROUTER" "$OUT" <<'PY'
from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

router_path = Path(sys.argv[1])
out = Path(sys.argv[2])

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()

marker = "ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"
marker_line = None
for i, line in enumerate(lines, start=1):
    if marker in line:
        marker_line = i
        break

if marker_line is None:
    raise RuntimeError("Phase 38 marker missing after patch")

capture_re = re.compile(
    r"_ELI_[A-Z0-9_]*(?:PREV|ORIG_ROUTE|ROUTE_PREV|PREVIOUS_ROUTE)"
    r"|_eli_[a-z0-9_]*(?:previous_route|prev_route|prev_route_intent)"
)

alias_rebind_re = re.compile(
    r"^\s*(?:route_command|parse_command|classify|route_intent)\s*=\s*route\b"
)

capture_hits = []
alias_hits = []

for i, line in enumerate(lines[: marker_line - 1], start=1):
    if capture_re.search(line):
        capture_hits.append(f"{i}: {line}")
    if alias_rebind_re.search(line):
        alias_hits.append(f"{i}: {line}")

(out / "14_post_patch_residual_route_capture_symbol_hits.txt").write_text(
    "=== POST-PATCH RESIDUAL PRE-PHASE38 ROUTE-CAPTURE SYMBOL HITS ===\n"
    + ("\n".join(capture_hits) + "\n" if capture_hits else "NONE\n"),
    encoding="utf-8",
)

(out / "15_post_patch_residual_public_surface_alias_rebindings.txt").write_text(
    "=== POST-PATCH RESIDUAL PRE-PHASE38 PUBLIC SURFACE ALIAS REBINDINGS ===\n"
    + ("\n".join(alias_hits) + "\n" if alias_hits else "NONE\n"),
    encoding="utf-8",
)

tree = ast.parse(src)

surface_counts = {
    "route": 0,
    "route_intent": 0,
    "route_command": 0,
    "parse_command": 0,
    "classify": 0,
}

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        ln = getattr(node, "lineno", -1)
        if 0 < ln < marker_line and node.name in surface_counts:
            surface_counts[node.name] += 1

surface_lines = [
    "=== POST-PATCH PRE-PHASE38 PUBLIC SURFACE FUNCTION DEF COUNTS ===",
    f"PHASE38_MARKER_LINE={marker_line}",
]
for name in ["route", "route_intent", "route_command", "parse_command", "classify"]:
    surface_lines.append(f"{name}={surface_counts[name]}")

(out / "16_post_patch_public_surface_function_def_counts.txt").write_text(
    "\n".join(surface_lines) + "\n",
    encoding="utf-8",
)

import eli.execution.router_enhanced as router

names = ["route", "route_intent", "route_command", "parse_command", "classify"]
base = getattr(router, "route")

rows = [
    "=== POST-PATCH RUNTIME PUBLIC SURFACE IDENTITY PROBE ===",
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
rows.append(
    f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT="
    f"{all(getattr(router, name, None) is base for name in names)}"
)

(out / "17_post_patch_runtime_public_surface_identity_probe.txt").write_text(
    "\n".join(rows) + "\n",
    encoding="utf-8",
)
PY

diff -u \
  "$OUT/backups/router_enhanced.py.before_phase42.bak" \
  "$ROUTER" \
  > "$OUT/18_router_source_diff.patch" || true

python3 - "$OUT" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys

out = Path(sys.argv[1])

application = (out / "08_phase42_patch_application_summary.txt").read_text(encoding="utf-8")
compare = (out / "13_phase36_semantic_baseline_exact_compare.txt").read_text(encoding="utf-8")
captures = (out / "14_post_patch_residual_route_capture_symbol_hits.txt").read_text(encoding="utf-8")
aliases = (out / "15_post_patch_residual_public_surface_alias_rebindings.txt").read_text(encoding="utf-8")
surfaces = (out / "16_post_patch_public_surface_function_def_counts.txt").read_text(encoding="utf-8")
identity = (out / "17_post_patch_runtime_public_surface_identity_probe.txt").read_text(encoding="utf-8")

def extract_int(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}:\s*(\d+)", text)
    return m.group(1) if m else "?"

deleted_statements = extract_int(application, "Deleted top-level stale-shell candidate statements")
deleted_lines = extract_int(application, "Deleted source lines")
retained_statements = extract_int(application, "Retained dependency-closed candidate statements")

capture_count = 0 if captures.strip().endswith("NONE") else len(
    [line for line in captures.splitlines() if re.match(r"^\d+:", line)]
)
alias_count = 0 if aliases.strip().endswith("NONE") else len(
    [line for line in aliases.splitlines() if re.match(r"^\d+:", line)]
)

raw_equal = "RAW_JSON_EQUAL=True" in compare
parsed_equal = "PARSED_JSON_EQUAL=True" in compare
public_identity_ok = "ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT=True" in identity

digest = f"""=== PHASE 42 DIGEST ===
Router compile: PASS
Dependency-closed residual stale-shell prune: PASS
Deleted stale-shell top-level statements: {deleted_statements}
Deleted source lines: {deleted_lines}
Retained dependency-required candidate statements: {retained_statements}

Phase 36 pre/post raw semantic JSON exact equality: {'PASS' if raw_equal else 'FAIL'}
Phase 36 pre/post parsed semantic JSON equality: {'PASS' if parsed_equal else 'FAIL'}
Runtime public routing surfaces remain canonical: {'PASS' if public_identity_ok else 'FAIL'}

Post-patch residual debt:
- route-capture symbol hit lines remaining: {capture_count}
- public-surface alias rebinding lines remaining: {alias_count}

Interpretation:
- Phase 42 removed only dependency-unreachable stale wrapper-shell residue.
- Any shell/capture lines that remain are dependency-connected to the currently
  preserved flattened dispatch contract or to retained helper-hosting blocks.
- A future Phase 43 should inspect the remaining residue and determine whether
  retained mixed-purpose Try blocks can be split, rather than deleted wholesale.

Review:
- 04_dependency_closed_candidate_classification.txt
- 07_pruned_candidate_source_windows.txt
- 13_phase36_semantic_baseline_exact_compare.txt
- 12_phase36_semantic_baseline_exact_diff.txt
- 14_post_patch_residual_route_capture_symbol_hits.txt
- 15_post_patch_residual_public_surface_alias_rebindings.txt
- 16_post_patch_public_surface_function_def_counts.txt
- 17_post_patch_runtime_public_surface_identity_probe.txt
- 18_router_source_diff.patch

PHASE42_OUT={out}
"""

(out / "19_console_digest.txt").write_text(digest, encoding="utf-8")
print(digest)
PY

{
  echo
  echo "## Phase 42 artifacts"
  echo "- \`00_pre_compile.txt\`"
  echo "- \`01_pre_phase36_console.txt\`"
  echo "- \`02_pre_phase36_semantic_baseline.json\`"
  echo "- \`03_phase38_required_symbol_surface.txt\`"
  echo "- \`04_dependency_closed_candidate_classification.txt\`"
  echo "- \`05_dependency_closed_candidate_classification.json\`"
  echo "- \`06_retained_candidate_source_windows.txt\`"
  echo "- \`07_pruned_candidate_source_windows.txt\`"
  echo "- \`08_phase42_patch_application_summary.txt\`"
  echo "- \`09_post_compile.txt\`"
  echo "- \`10_post_phase36_console.txt\`"
  echo "- \`11_post_phase36_semantic_baseline.json\`"
  echo "- \`12_phase36_semantic_baseline_exact_diff.txt\`"
  echo "- \`13_phase36_semantic_baseline_exact_compare.txt\`"
  echo "- \`14_post_patch_residual_route_capture_symbol_hits.txt\`"
  echo "- \`15_post_patch_residual_public_surface_alias_rebindings.txt\`"
  echo "- \`16_post_patch_public_surface_function_def_counts.txt\`"
  echo "- \`17_post_patch_runtime_public_surface_identity_probe.txt\`"
  echo "- \`18_router_source_diff.patch\`"
  echo "- \`19_console_digest.txt\`"
  echo
  echo "PHASE42_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

trap - ERR
PATCH_WRITTEN=0

echo
echo "PHASE42_OUT=$OUT"
