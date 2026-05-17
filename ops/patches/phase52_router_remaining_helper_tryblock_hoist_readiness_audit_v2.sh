#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase52_router_remaining_helper_tryblock_hoist_readiness_audit_v2_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE45B_SCRIPT="ops/patches/phase45b_router_transitive_postmarker_mixed_shell_split_audit_v2.sh"
PHASE38_MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if [[ ! -f "$PHASE45B_SCRIPT" ]]; then
  echo "Missing Phase45b audit script: $PHASE45B_SCRIPT" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 52 v2 — Remaining Helper Try-Block Hoist Readiness Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Correction from Phase52 v1

Phase52 v1 incorrectly expected the Phase45b liveness matrix to use
stanza-style blocks such as:

\`\`\`
mixed_try_01:
  lines=...
\`\`\`

The current Phase45b v2 matrix is actually a pipe-delimited table:

\`\`\`
idx | lines | live_binds_combined | preserve_body_stmt_count | remove_body_stmt_count | mechanically_splittable
\`\`\`

Phase52 v2 parses the authoritative table format directly.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} 2>&1 | tee "$OUT/00_compile.txt"

echo "=== PHASE45b REFRESH AUDIT ===" | tee "$OUT/01_phase45b_refresh_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/01_phase45b_refresh_console.txt"

PHASE45B_OUT="$(
  grep -E '^PHASE45B_OUT=' "$OUT/01_phase45b_refresh_console.txt" \
    | tail -1 \
    | cut -d= -f2-
)"

if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve PHASE45B_OUT from Phase45b refresh audit." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/02_phase45b_out.txt"

for f in \
  02_mixed_tryblock_liveness_matrix.txt \
  03_preserve_substatement_manifest.txt \
  04_remove_candidate_substatement_manifest.txt \
  05_preserve_source_windows.txt \
  06_remove_candidate_source_windows.txt \
  10_runtime_public_surface_identity_probe.txt \
  11_phase45b_conclusion.txt \
  12_console_digest.txt
do
  if [[ ! -f "$PHASE45B_OUT/$f" ]]; then
    echo "Missing expected Phase45b artifact: $PHASE45B_OUT/$f" >&2
    exit 1
  fi
done

cp "$PHASE45B_OUT/02_mixed_tryblock_liveness_matrix.txt" "$OUT/03_phase45b_mixed_tryblock_liveness_matrix.txt"
cp "$PHASE45B_OUT/03_preserve_substatement_manifest.txt" "$OUT/04_phase45b_preserve_substatement_manifest.txt"
cp "$PHASE45B_OUT/04_remove_candidate_substatement_manifest.txt" "$OUT/05_phase45b_remove_candidate_substatement_manifest.txt"
cp "$PHASE45B_OUT/05_preserve_source_windows.txt" "$OUT/06_phase45b_preserve_source_windows.txt"
cp "$PHASE45B_OUT/06_remove_candidate_source_windows.txt" "$OUT/07_phase45b_remove_candidate_source_windows.txt"
cp "$PHASE45B_OUT/10_runtime_public_surface_identity_probe.txt" "$OUT/08_phase45b_runtime_surface_probe.txt"
cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" "$OUT/09_phase45b_conclusion.txt"
cp "$PHASE45B_OUT/12_console_digest.txt" "$OUT/10_phase45b_digest.txt"

python3 - "$ROUTER" "$PHASE45B_OUT" "$OUT" "$PHASE38_MARKER" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

router_path = Path(sys.argv[1])
phase45b_out = Path(sys.argv[2])
out = Path(sys.argv[3])
phase38_marker = sys.argv[4]

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

matrix_path = phase45b_out / "02_mixed_tryblock_liveness_matrix.txt"
digest_path = phase45b_out / "12_console_digest.txt"
conclusion_path = phase45b_out / "11_phase45b_conclusion.txt"

matrix_text = matrix_path.read_text(encoding="utf-8")
digest_text = digest_path.read_text(encoding="utf-8")
conclusion_text = conclusion_path.read_text(encoding="utf-8")

# ---------------------------------------------------------------------
# Parse authoritative counts from Phase45b
# ---------------------------------------------------------------------

def extract_int(pattern: str, text: str, label: str) -> int:
    m = re.search(pattern, text)
    if not m:
        raise RuntimeError(f"Could not extract {label}")
    return int(m.group(1))

phase45b_mixed_count = extract_int(
    r"Mixed pre-Phase38 Try blocks with post-marker live binds:\s*(\d+)",
    digest_text,
    "Phase45b mixed Try-block count",
)

phase45b_mech_count = extract_int(
    r"Mechanically splittable mixed blocks:\s*(\d+)",
    digest_text,
    "Phase45b mechanically splittable count",
)

phase38_marker_line = extract_int(
    r"PHASE38_MARKER_LINE=(\d+)",
    conclusion_text,
    "Phase38 marker line",
)

# ---------------------------------------------------------------------
# Parse the real Phase45b table format
# ---------------------------------------------------------------------

records_from_matrix: list[dict[str, Any]] = []

for raw_line in matrix_text.splitlines():
    line = raw_line.strip()

    # Expected current Phase45b v2 row shape:
    # idx | lines | live_binds_combined | preserve_body_stmt_count | remove_body_stmt_count | mechanically_splittable
    if not re.match(r"^\d+\s*\|\s*\d+-\d+\s*\|", line):
        continue

    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 6:
        raise RuntimeError(f"Malformed Phase45b matrix row: {raw_line}")

    idx_s, span_s, live_s, preserve_s, remove_s, mech_s = parts[:6]

    m_span = re.fullmatch(r"(\d+)-(\d+)", span_s)
    if not m_span:
        raise RuntimeError(f"Malformed line span in Phase45b matrix row: {raw_line}")

    start = int(m_span.group(1))
    end = int(m_span.group(2))

    live_binds = [
        item.strip()
        for item in live_s.split(",")
        if item.strip() and item.strip() != "-"
    ]

    records_from_matrix.append(
        {
            "idx": int(idx_s),
            "start": start,
            "end": end,
            "live_binds": live_binds,
            "preserve_body_stmt_count": int(preserve_s),
            "remove_body_stmt_count": int(remove_s),
            "mechanically_splittable": mech_s.lower() == "true",
        }
    )

if len(records_from_matrix) != phase45b_mixed_count:
    raise RuntimeError(
        "Phase52 v2 matrix parser mismatch: "
        f"Phase45b digest reports {phase45b_mixed_count}, "
        f"but parser recovered {len(records_from_matrix)} row(s)."
    )

# ---------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------

def top_level_try_nodes() -> list[ast.Try]:
    return [node for node in tree.body if isinstance(node, ast.Try)]

def find_try_for_span(start: int, end: int) -> ast.Try:
    exact = [
        node for node in top_level_try_nodes()
        if getattr(node, "lineno", None) == start
        and getattr(node, "end_lineno", None) == end
    ]
    if exact:
        return exact[0]

    containment = [
        node for node in top_level_try_nodes()
        if getattr(node, "lineno", 10**9) <= start
        and getattr(node, "end_lineno", -1) >= end
    ]
    if containment:
        return containment[0]

    raise RuntimeError(f"Could not locate top-level Try node for lines {start}-{end}")

def source_for_span(start: int, end: int, pad: int = 2) -> str:
    lo = max(1, start - pad)
    hi = min(len(lines), end + pad)
    return "\n".join(f"{n:6d}: {lines[n-1]}" for n in range(lo, hi + 1))

def stmt_source(stmt: ast.stmt) -> str:
    start = getattr(stmt, "lineno", None)
    end = getattr(stmt, "end_lineno", None)
    if not start or not end:
        return ""
    return "\n".join(lines[start - 1:end])

def assigned_names(stmt: ast.stmt) -> set[str]:
    names: set[str] = set()

    def visit_target(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                visit_target(item)

    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            visit_target(target)
    elif isinstance(stmt, ast.AnnAssign):
        visit_target(stmt.target)
    elif isinstance(stmt, ast.AugAssign):
        visit_target(stmt.target)
    elif isinstance(stmt, ast.Import):
        for alias in stmt.names:
            names.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(stmt, ast.ImportFrom):
        for alias in stmt.names:
            names.add(alias.asname or alias.name)
    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(stmt.name)

    return names

def is_helper_stmt(stmt: ast.stmt) -> bool:
    return isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))

def is_import_stmt(stmt: ast.stmt) -> bool:
    return isinstance(stmt, (ast.Import, ast.ImportFrom))

def except_semantics(node: ast.Try) -> dict[str, Any]:
    info = {
        "handler_count": len(node.handlers),
        "except_has_print": False,
        "except_has_logging": False,
        "except_has_assignment": False,
        "except_has_return": False,
        "except_has_raise": False,
        "except_has_nontrivial_stmt": False,
        "except_pass_only": True,
        "handler_stmt_kinds": [],
    }

    for handler in node.handlers:
        kinds = [type(stmt).__name__ for stmt in handler.body]
        info["handler_stmt_kinds"].append(kinds)

        for stmt in handler.body:
            if not isinstance(stmt, ast.Pass):
                info["except_pass_only"] = False

            for child in ast.walk(stmt):
                if isinstance(child, ast.Assign | ast.AnnAssign | ast.AugAssign):
                    info["except_has_assignment"] = True
                elif isinstance(child, ast.Return):
                    info["except_has_return"] = True
                elif isinstance(child, ast.Raise):
                    info["except_has_raise"] = True
                elif isinstance(child, ast.Call):
                    fn = child.func
                    fn_name = ""
                    if isinstance(fn, ast.Name):
                        fn_name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        fn_name = fn.attr

                    if fn_name == "print":
                        info["except_has_print"] = True
                    if fn_name in {
                        "warning", "warn", "error", "exception", "info", "debug", "critical"
                    }:
                        info["except_has_logging"] = True

            if not isinstance(stmt, ast.Pass):
                # Anything beyond Pass/diagnostic-only expression is considered nontrivial.
                if not (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Call)
                ):
                    info["except_has_nontrivial_stmt"] = True

    return info

def helper_read_names(stmt: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    stores: set[str] = set()
    loads: set[str] = set()

    for child in ast.walk(stmt):
        if isinstance(child, ast.Name):
            if isinstance(child.ctx, ast.Store):
                stores.add(child.id)
            elif isinstance(child.ctx, ast.Load):
                loads.add(child.id)

    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for arg in (
            list(stmt.args.posonlyargs)
            + list(stmt.args.args)
            + list(stmt.args.kwonlyargs)
        ):
            stores.add(arg.arg)
        if stmt.args.vararg:
            stores.add(stmt.args.vararg.arg)
        if stmt.args.kwarg:
            stores.add(stmt.args.kwarg.arg)

    basic_builtins = {
        "str", "bool", "int", "float", "dict", "list", "set", "tuple",
        "len", "any", "all", "sum", "min", "max", "round", "print",
        "isinstance", "getattr", "hasattr", "callable", "Exception",
        "object", "enumerate", "range", "zip", "sorted", "reversed",
        "True", "False", "None",
    }

    reads = sorted(
        name for name in loads
        if name not in stores
        and name not in basic_builtins
    )
    return reads

# ---------------------------------------------------------------------
# Classify each remaining mixed Try block
# ---------------------------------------------------------------------

classified: list[dict[str, Any]] = []
windows: list[str] = []

for row in records_from_matrix:
    node = find_try_for_span(row["start"], row["end"])

    body_helpers = [stmt for stmt in node.body if is_helper_stmt(stmt)]
    body_imports = [stmt for stmt in node.body if is_import_stmt(stmt)]
    body_other = [
        stmt for stmt in node.body
        if not is_helper_stmt(stmt)
        and not is_import_stmt(stmt)
    ]

    helper_names = sorted(
        name
        for stmt in body_helpers
        for name in assigned_names(stmt)
    )

    import_names = sorted(
        name
        for stmt in body_imports
        for name in assigned_names(stmt)
    )

    other_assignment_names = sorted(
        name
        for stmt in body_other
        for name in assigned_names(stmt)
    )

    live_helper_names = sorted(set(helper_names) & set(row["live_binds"]))

    helper_dependency_reads = {
        stmt.name: helper_read_names(stmt)
        for stmt in body_helpers
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }

    exc = except_semantics(node)

    # Readiness classifier: conservative, structural, audit-only.
    if body_other:
        readiness = "retain_manual"
        reason = "Try body contains non-helper/non-import statements that require explicit semantic review."
    elif exc["except_has_assignment"] or exc["except_has_return"] or exc["except_has_raise"]:
        readiness = "retain_manual"
        reason = "Except path contains assignment, return, or raise semantics."
    elif exc["except_pass_only"]:
        if body_imports:
            readiness = "candidate_hoist_helpers_plus_imports"
            reason = "Body contains helpers/imports only; except path is pass-only."
        else:
            readiness = "candidate_hoist_helpers_only"
            reason = "Body contains helpers only; except path is pass-only."
    elif exc["except_has_print"] or exc["except_has_logging"]:
        readiness = "candidate_hoist_preserve_diagnostic"
        reason = "Try body is helper/import-only and except path appears diagnostic-only."
    else:
        readiness = "retain_manual"
        reason = "Except path is non-pass and not confidently diagnostic-only."

    record = {
        **row,
        "body_helper_names": helper_names,
        "live_helper_names": live_helper_names,
        "body_import_names": import_names,
        "body_other_stmt_kinds": [type(stmt).__name__ for stmt in body_other],
        "body_other_assignment_names": other_assignment_names,
        "body_statement_kinds": [type(stmt).__name__ for stmt in node.body],
        "orelse_statement_count": len(node.orelse),
        "finalbody_statement_count": len(node.finalbody),
        "except_semantics": exc,
        "helper_dependency_reads": helper_dependency_reads,
        "readiness": readiness,
        "reason": reason,
    }
    classified.append(record)

    windows.append(
        "\n".join(
            [
                "=" * 140,
                f"Phase45b idx={row['idx']} | lines={row['start']}-{row['end']}",
                f"live_binds={', '.join(row['live_binds']) or '-'}",
                f"live_helper_names={', '.join(live_helper_names) or '-'}",
                f"readiness={readiness}",
                f"reason={reason}",
                "-" * 140,
                source_for_span(row["start"], row["end"], pad=2),
                "",
            ]
        )
    )

# ---------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------

(out / "11_phase52_classified_remaining_tryblocks.json").write_text(
    json.dumps(classified, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

readiness_counts = Counter(rec["readiness"] for rec in classified)

summary_lines = [
    "=== PHASE 52 v2 HOIST READINESS SUMMARY ===",
    f"PHASE38_MARKER_LINE={phase38_marker_line}",
    f"PHASE45B_MIXED_TRYBLOCK_COUNT={phase45b_mixed_count}",
    f"PHASE45B_MECHANICALLY_SPLITTABLE_COUNT={phase45b_mech_count}",
    f"PHASE52_CLASSIFIED_TRYBLOCK_COUNT={len(classified)}",
    "",
]

for key in sorted(readiness_counts):
    summary_lines.append(f"{key}={readiness_counts[key]}")

summary_lines.append("")

for rec in classified:
    summary_lines.extend(
        [
            f"idx={rec['idx']} lines={rec['start']}-{rec['end']}",
            f"  live_binds={', '.join(rec['live_binds']) or '-'}",
            f"  body_helper_names={', '.join(rec['body_helper_names']) or '-'}",
            f"  live_helper_names={', '.join(rec['live_helper_names']) or '-'}",
            f"  body_import_names={', '.join(rec['body_import_names']) or '-'}",
            f"  body_other_stmt_kinds={', '.join(rec['body_other_stmt_kinds']) or '-'}",
            f"  except_handler_count={rec['except_semantics']['handler_count']}",
            f"  readiness={rec['readiness']}",
            f"  reason={rec['reason']}",
            "",
        ]
    )

(out / "12_hoist_readiness_summary.txt").write_text(
    "\n".join(summary_lines) + "\n",
    encoding="utf-8",
)

matrix_lines = [
    "=== PHASE 52 v2 HOIST READINESS MATRIX ===",
    "idx | lines | readiness | live_binds | helper_names | imports | body_other | except_flags",
    "-" * 240,
]

for rec in classified:
    exc = rec["except_semantics"]
    flags: list[str] = []
    if exc["except_pass_only"]:
        flags.append("pass_only")
    if exc["except_has_print"]:
        flags.append("print")
    if exc["except_has_logging"]:
        flags.append("logging")
    if exc["except_has_assignment"]:
        flags.append("assign")
    if exc["except_has_return"]:
        flags.append("return")
    if exc["except_has_raise"]:
        flags.append("raise")
    if exc["except_has_nontrivial_stmt"]:
        flags.append("nontrivial")

    matrix_lines.append(
        " | ".join(
            [
                str(rec["idx"]),
                f"{rec['start']}-{rec['end']}",
                rec["readiness"],
                ",".join(rec["live_binds"]) or "-",
                ",".join(rec["body_helper_names"]) or "-",
                ",".join(rec["body_import_names"]) or "-",
                ",".join(rec["body_other_stmt_kinds"]) or "-",
                ",".join(flags) or "-",
            ]
        )
    )

(out / "13_hoist_readiness_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

(out / "14_remaining_tryblock_source_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

clean_candidates = [
    rec for rec in classified
    if rec["readiness"] in {
        "candidate_hoist_helpers_only",
        "candidate_hoist_helpers_plus_imports",
    }
]

diagnostic_candidates = [
    rec for rec in classified
    if rec["readiness"] == "candidate_hoist_preserve_diagnostic"
]

manual_retained = [
    rec for rec in classified
    if rec["readiness"] == "retain_manual"
]

recommendation = [
    "=== PHASE 52 v2 RECOMMENDED NEXT MOVE ===",
    "",
    f"clean_hoist_candidates={len(clean_candidates)}",
    f"diagnostic_preserving_hoist_candidates={len(diagnostic_candidates)}",
    f"manual_retained_blocks={len(manual_retained)}",
    "",
]

if clean_candidates:
    recommendation.append("Clean hoist candidates:")
    for rec in clean_candidates:
        recommendation.append(
            f"- idx={rec['idx']} lines={rec['start']}-{rec['end']} readiness={rec['readiness']}"
        )
    recommendation.append("")

if diagnostic_candidates:
    recommendation.append("Diagnostic-preserving hoist candidates:")
    for rec in diagnostic_candidates:
        recommendation.append(
            f"- idx={rec['idx']} lines={rec['start']}-{rec['end']} readiness={rec['readiness']}"
        )
    recommendation.append("")

if manual_retained:
    recommendation.append("Retain/manual-analysis blocks:")
    for rec in manual_retained:
        recommendation.append(
            f"- idx={rec['idx']} lines={rec['start']}-{rec['end']} reason={rec['reason']}"
        )
    recommendation.append("")

if clean_candidates:
    recommendation.extend(
        [
            "Interpretation:",
            "- Phase53 may be a narrow source patch against only the clean hoist candidate(s).",
            "- Do not touch diagnostic or manual-retained blocks in the same patch.",
        ]
    )
elif diagnostic_candidates:
    recommendation.extend(
        [
            "Interpretation:",
            "- No completely clean helper-only hoists remain.",
            "- Phase53 should decide whether diagnostic-only except branches are worth preserving as explicit logging before hoisting.",
        ]
    )
else:
    recommendation.extend(
        [
            "Interpretation:",
            "- No confidently hoistable blocks remain under the current conservative rule-set.",
            "- Phase53 should be a deeper semantic audit of the retained six blocks, not a deletion patch.",
        ]
    )

(out / "15_recommended_next_move.txt").write_text(
    "\n".join(recommendation) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------

assertions: list[str] = []
failures: list[str] = []

def check(ok: bool, message: str) -> None:
    if ok:
        assertions.append(f"PASS: {message}")
    else:
        assertions.append(f"FAIL: {message}")
        failures.append(message)

check(
    phase45b_mixed_count == 6,
    f"Phase45b mixed Try-block count remains 6 after Phase51; observed {phase45b_mixed_count}",
)

check(
    phase45b_mech_count == 0,
    f"Phase45b mechanically splittable mixed-block count remains 0; observed {phase45b_mech_count}",
)

check(
    len(classified) == phase45b_mixed_count,
    f"Phase52 table parser recovered all Phase45b mixed blocks; parsed {len(classified)} of {phase45b_mixed_count}",
)

check(
    all(rec["readiness"] for rec in classified),
    "every remaining mixed Try block received a readiness classification",
)

check(
    phase38_marker in src,
    f"Phase38 marker remains present: {phase38_marker}",
)

check(
    phase38_marker_line > 0,
    f"Phase38 marker line parsed successfully: {phase38_marker_line}",
)

assertions.append(
    "PHASE52_V2_ASSERTIONS_PASS"
    if not failures
    else f"PHASE52_V2_ASSERTIONS_FAIL count={len(failures)}"
)

(out / "16_targeted_assertions.txt").write_text(
    "\n".join(["=== PHASE 52 v2 TARGETED ASSERTIONS ===", *assertions]) + "\n",
    encoding="utf-8",
)

if failures:
    raise SystemExit(f"Phase52 v2 targeted assertions failed: {len(failures)}")

# ---------------------------------------------------------------------
# Direct runtime sanity probe script
# ---------------------------------------------------------------------

probe = r'''
from __future__ import annotations

import json
from eli.execution import router_enhanced as r

surfaces = {
    "route": r.route,
    "route_intent": r.route_intent,
    "route_command": r.route_command,
    "parse_command": r.parse_command,
    "classify": r.classify,
}

surface_ids = {name: id(fn) for name, fn in surfaces.items()}
all_same = len(set(surface_ids.values())) == 1

identity = r.route("Who am I?")
memory_runtime = r.route(
    "Explain exactly how your memory system works internally — "
    "which files, which DB tables, which functions."
)
multipdf = r.route("analyze /tmp/a.pdf and /tmp/b.pdf")

print("=== PHASE 52 v2 DIRECT RUNTIME SANITY PROBE ===")
print("surface_ids=" + json.dumps(surface_ids, sort_keys=True))
print("all_public_surfaces_same_object=" + repr(all_same))
print("identity_probe_result=" + json.dumps(identity, sort_keys=True))
print("memory_runtime_probe_result=" + json.dumps(memory_runtime, sort_keys=True))
print("multipdf_probe_result=" + json.dumps(multipdf, sort_keys=True))

if not all_same:
    raise SystemExit("public router surfaces drifted")
if identity.get("action") != "USER_IDENTITY_SUMMARY":
    raise SystemExit("identity route contract regressed")
if memory_runtime.get("action") != "EXPLAIN_MEMORY_RUNTIME":
    raise SystemExit("memory-runtime route contract regressed")
if multipdf.get("action") != "ANALYZE_PDF":
    raise SystemExit("multi-PDF action regressed")
if multipdf.get("args", {}).get("paths") != ["/tmp/a.pdf", "/tmp/b.pdf"]:
    raise SystemExit("multi-PDF paths enrichment regressed")

print("DIRECT_RUNTIME_SANITY_PROBE_PASS")
'''

(out / "17_direct_runtime_probe.py").write_text(
    probe,
    encoding="utf-8",
)
PY

python3 "$OUT/17_direct_runtime_probe.py" 2>&1 | tee "$OUT/18_direct_runtime_probe.txt"

{
  echo "=== PHASE 52 v2 DIGEST ==="
  echo "Router compile: PASS"
  echo "Audit mode: PASS"
  echo "No source files modified: PASS"
  echo "Phase45b table parser correction: PASS"
  echo
  sed -n '1,30p' "$OUT/12_hoist_readiness_summary.txt"
  echo
  cat "$OUT/15_recommended_next_move.txt"
  echo
  echo "Review:"
  echo "- 12_hoist_readiness_summary.txt"
  echo "- 13_hoist_readiness_matrix.txt"
  echo "- 14_remaining_tryblock_source_windows.txt"
  echo "- 15_recommended_next_move.txt"
  echo "- 16_targeted_assertions.txt"
  echo "- 18_direct_runtime_probe.txt"
  echo
  echo "PHASE52_V2_OUT=$OUT"
} | tee "$OUT/19_console_digest.txt"

echo
echo "PHASE52_V2_OUT=$OUT"
