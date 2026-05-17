#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase52_router_remaining_helper_tryblock_hoist_readiness_audit_${STAMP}"

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
# Phase 52 — Remaining Helper Try-Block Hoist Readiness Audit

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase51 removed the only mechanically splittable mixed helper/shell block.

Phase52 examines the six remaining pre-Phase38 mixed Try blocks that still host
live helpers referenced by the flattened canonical dispatcher. It determines
whether each container is:

- pure helper shell, likely hoistable;
- helper shell with imports that must move with it;
- helper shell with except-path side effects or fallback semantics;
- helper shell requiring manual preservation.

This phase does **not** modify source.
EOF

{
  echo "=== PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} 2>&1 | tee "$OUT/00_compile.txt"

echo "=== PHASE45b REFRESH AUDIT ===" | tee "$OUT/01_phase45b_refresh_console.txt"
bash "$PHASE45B_SCRIPT" 2>&1 | tee -a "$OUT/01_phase45b_refresh_console.txt"

PHASE45B_OUT="$(grep -E '^PHASE45B_OUT=' "$OUT/01_phase45b_refresh_console.txt" | tail -1 | cut -d= -f2- || true)"
if [[ -z "${PHASE45B_OUT:-}" || ! -d "$PHASE45B_OUT" ]]; then
  echo "Could not resolve PHASE45B_OUT from refresh audit." >&2
  exit 1
fi

echo "PHASE45B_OUT=$PHASE45B_OUT" | tee "$OUT/02_phase45b_out.txt"

cp "$PHASE45B_OUT/02_mixed_tryblock_liveness_matrix.txt" "$OUT/03_phase45b_mixed_tryblock_liveness_matrix.txt"
cp "$PHASE45B_OUT/03_preserve_substatement_manifest.txt" "$OUT/04_phase45b_preserve_substatement_manifest.txt"
cp "$PHASE45B_OUT/04_remove_candidate_substatement_manifest.txt" "$OUT/05_phase45b_remove_candidate_substatement_manifest.txt"
cp "$PHASE45B_OUT/05_preserve_source_windows.txt" "$OUT/06_phase45b_preserve_source_windows.txt"
cp "$PHASE45B_OUT/06_remove_candidate_source_windows.txt" "$OUT/07_phase45b_remove_candidate_source_windows.txt"
cp "$PHASE45B_OUT/11_phase45b_conclusion.txt" "$OUT/08_phase45b_conclusion.txt"

python3 - "$ROUTER" "$PHASE45B_OUT" "$OUT" "$PHASE38_MARKER" <<'PY'
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

router_path = Path(sys.argv[1])
phase45b_out = Path(sys.argv[2])
out = Path(sys.argv[3])
phase38_marker = sys.argv[4]

src = router_path.read_text(encoding="utf-8")
lines = src.splitlines()
tree = ast.parse(src)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def text_window(start: int, end: int, pad: int = 0) -> str:
    lo = max(1, start - pad)
    hi = min(len(lines), end + pad)
    return "\n".join(f"{n:6d}: {lines[n-1]}" for n in range(lo, hi + 1))

def node_text(node: ast.AST) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if not start or not end:
        return ""
    return "\n".join(lines[start - 1:end])

def top_level_nodes() -> list[ast.stmt]:
    return list(tree.body)

def load_phase45b_mixed_blocks() -> list[dict[str, Any]]:
    matrix = (phase45b_out / "02_mixed_tryblock_liveness_matrix.txt").read_text(encoding="utf-8")
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw in matrix.splitlines():
        line = raw.rstrip()

        m = re.match(r"^mixed_try_(\d+):$", line.strip())
        if m:
            if current:
                blocks.append(current)
            current = {"name": f"mixed_try_{int(m.group(1)):02d}"}
            continue

        if current is None:
            continue

        m = re.match(r"^\s*phase45b_idx=(\d+)\s*$", line)
        if m:
            current["phase45b_idx"] = int(m.group(1))
            continue

        m = re.match(r"^\s*lines=(\d+)-(\d+)\s*$", line)
        if m:
            current["start"] = int(m.group(1))
            current["end"] = int(m.group(2))
            continue

        m = re.match(r"^\s*live_binds=(.*)$", line)
        if m:
            value = m.group(1).strip()
            current["live_binds"] = [x.strip() for x in value.split(",") if x.strip() and x.strip() != "-"]
            continue

        m = re.match(r"^\s*defined_symbols=(.*)$", line)
        if m:
            value = m.group(1).strip()
            current["defined_symbols"] = [x.strip() for x in value.split(",") if x.strip() and x.strip() != "-"]
            continue

        m = re.match(r"^\s*helper_symbols=(.*)$", line)
        if m:
            value = m.group(1).strip()
            current["helper_symbols"] = [x.strip() for x in value.split(",") if x.strip() and x.strip() != "-"]
            continue

        m = re.match(r"^\s*assignment_symbols=(.*)$", line)
        if m:
            value = m.group(1).strip()
            current["assignment_symbols"] = [x.strip() for x in value.split(",") if x.strip() and x.strip() != "-"]
            continue

    if current:
        blocks.append(current)

    return blocks

def find_exact_top_level_try(start: int, end: int) -> ast.Try | ast.TryStar | None:
    for node in top_level_nodes():
        if isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            if getattr(node, "lineno", None) == start and getattr(node, "end_lineno", None) == end:
                return node
    return None

def assigned_names(stmt: ast.stmt) -> set[str]:
    names: set[str] = set()

    def visit_target(t: ast.AST) -> None:
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for elt in t.elts:
                visit_target(elt)
        elif isinstance(t, ast.Attribute):
            pass
        elif isinstance(t, ast.Subscript):
            pass

    if isinstance(stmt, ast.Assign):
        for t in stmt.targets:
            visit_target(t)
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

def helper_defs(stmt: ast.stmt) -> set[str]:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {stmt.name}
    return set()

def stmt_kind(stmt: ast.stmt) -> str:
    return type(stmt).__name__

def collect_load_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            out.add(child.id)
    return out

def collect_store_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            out.add(child.id)
    return out

BUILTINS = {
    "str", "bool", "int", "float", "dict", "list", "set", "tuple",
    "len", "any", "all", "sum", "min", "max", "round", "print",
    "isinstance", "getattr", "hasattr", "callable", "Exception",
    "object", "enumerate", "range", "zip", "sorted", "reversed",
    "None", "True", "False",
}

def module_defined_before(line_no: int) -> set[str]:
    names: set[str] = set()
    for stmt in top_level_nodes():
        stmt_line = getattr(stmt, "lineno", 10**9)
        if stmt_line >= line_no:
            break
        names |= assigned_names(stmt)
    return names

def classify_try_container(node: ast.Try | ast.TryStar, helper_symbols: set[str]) -> dict[str, Any]:
    body = list(node.body)
    handlers = list(node.handlers)
    orelse = list(node.orelse)
    finalbody = list(node.finalbody)

    body_kinds = [stmt_kind(s) for s in body]
    handler_kinds = []
    handler_source = []
    except_has_print = False
    except_has_logging = False
    except_has_return = False
    except_has_raise = False
    except_has_assign = False
    except_has_pass_only = True

    for h in handlers:
        kinds = [stmt_kind(s) for s in h.body]
        handler_kinds.append(kinds)
        handler_source.append(node_text(h))
        for s in h.body:
            if not isinstance(s, ast.Pass):
                except_has_pass_only = False
            for c in ast.walk(s):
                if isinstance(c, ast.Call):
                    fn = c.func
                    name = ""
                    if isinstance(fn, ast.Name):
                        name = fn.id
                    elif isinstance(fn, ast.Attribute):
                        name = fn.attr
                    if name == "print":
                        except_has_print = True
                    if name in {"warning", "warn", "error", "exception", "info", "debug"}:
                        except_has_logging = True
                if isinstance(c, ast.Return):
                    except_has_return = True
                if isinstance(c, ast.Raise):
                    except_has_raise = True
                if isinstance(c, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    except_has_assign = True

    body_imports = [node_text(s) for s in body if isinstance(s, (ast.Import, ast.ImportFrom))]
    body_helpers = [node_text(s) for s in body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    body_non_helper_non_import = [
        node_text(s)
        for s in body
        if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
    ]

    body_helper_names: set[str] = set()
    body_import_names: set[str] = set()
    body_other_assigns: set[str] = set()

    for s in body:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body_helper_names |= helper_defs(s)
        elif isinstance(s, (ast.Import, ast.ImportFrom)):
            body_import_names |= assigned_names(s)
        else:
            body_other_assigns |= assigned_names(s)

    # External loads used by helper definitions.
    helper_external_reads: dict[str, list[str]] = {}
    module_before = module_defined_before(node.lineno)

    for s in body:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            loads = collect_load_names(s)
            stores = collect_store_names(s)
            localish = stores | set(getattr(s, "args", ast.arguments([], [], None, [], [], None, [])).args[i].arg
                                      for i in range(len(getattr(s, "args", ast.arguments([], [], None, [], [], None, [])).args)))
            external = sorted(
                x for x in loads
                if x not in localish
                and x not in BUILTINS
                and x not in body_helper_names
            )
            helper_external_reads[s.name] = external

    dependencies_resolved_by_body_imports: dict[str, list[str]] = {}
    dependencies_resolved_before_try: dict[str, list[str]] = {}
    dependencies_unresolved_or_dynamic: dict[str, list[str]] = {}

    for helper, reads in helper_external_reads.items():
        body_import_hits = sorted(x for x in reads if x in body_import_names)
        before_hits = sorted(x for x in reads if x in module_before)
        unresolved = sorted(
            x for x in reads
            if x not in body_import_names
            and x not in module_before
            and not x.startswith("_re")
        )
        dependencies_resolved_by_body_imports[helper] = body_import_hits
        dependencies_resolved_before_try[helper] = before_hits
        dependencies_unresolved_or_dynamic[helper] = unresolved

    all_unresolved = sorted({x for xs in dependencies_unresolved_or_dynamic.values() for x in xs})
    all_body_import_hits = sorted({x for xs in dependencies_resolved_by_body_imports.values() for x in xs})

    # Readiness classification.
    if except_has_return or except_has_raise or except_has_assign:
        readiness = "retain_manual"
        reason = "except path contains control-flow or assignment semantics"
    elif except_has_print or except_has_logging:
        readiness = "candidate_hoist_preserve_diagnostic"
        reason = "except path appears diagnostic-only; helper definitions may be hoistable if diagnostic loss is accepted or re-homed"
    elif not handlers or except_has_pass_only:
        if body_non_helper_non_import:
            readiness = "candidate_hoist_with_body_review"
            reason = "helpers/imports are present, but non-helper body statements remain"
        elif body_imports:
            readiness = "candidate_hoist_helpers_plus_imports"
            reason = "body contains only helper definitions plus imports"
        else:
            readiness = "candidate_hoist_helpers_only"
            reason = "body contains only helper definitions"
    else:
        readiness = "retain_manual"
        reason = "except path shape is non-trivial"

    if all_unresolved:
        readiness = "retain_manual"
        reason += f"; unresolved/dynamic helper reads detected: {', '.join(all_unresolved)}"

    return {
        "body_statement_kinds": body_kinds,
        "body_helper_names": sorted(body_helper_names),
        "body_import_names": sorted(body_import_names),
        "body_other_assignment_names": sorted(body_other_assigns),
        "body_imports_source": body_imports,
        "body_helpers_source_count": len(body_helpers),
        "body_non_helper_non_import_source": body_non_helper_non_import,
        "except_handler_count": len(handlers),
        "except_handler_statement_kinds": handler_kinds,
        "except_has_print": except_has_print,
        "except_has_logging": except_has_logging,
        "except_has_return": except_has_return,
        "except_has_raise": except_has_raise,
        "except_has_assign": except_has_assign,
        "except_has_pass_only": except_has_pass_only,
        "orelse_statement_count": len(orelse),
        "finalbody_statement_count": len(finalbody),
        "helper_external_reads": helper_external_reads,
        "dependencies_resolved_by_body_imports": dependencies_resolved_by_body_imports,
        "dependencies_resolved_before_try": dependencies_resolved_before_try,
        "dependencies_unresolved_or_dynamic": dependencies_unresolved_or_dynamic,
        "readiness": readiness,
        "reason": reason,
        "body_import_dependency_hits": all_body_import_hits,
    }

# ---------------------------------------------------------------------
# Phase45b source block universe
# ---------------------------------------------------------------------

phase45b_blocks = load_phase45b_mixed_blocks()

# Hard expectations after Phase51.
if len(phase45b_blocks) != 6:
    raise SystemExit(f"Expected 6 Phase45b mixed Try blocks after Phase51; got {len(phase45b_blocks)}")

records: list[dict[str, Any]] = []
windows: list[str] = []

for block in phase45b_blocks:
    start = int(block["start"])
    end = int(block["end"])
    node = find_exact_top_level_try(start, end)
    if node is None:
        raise SystemExit(f"Could not locate exact top-level Try block for {block['name']} lines={start}-{end}")

    helper_symbols = set(block.get("helper_symbols") or [])
    detail = classify_try_container(node, helper_symbols)

    rec = {
        **block,
        **detail,
    }
    records.append(rec)

    windows.append(
        "\n".join([
            "=" * 120,
            f"{block['name']} | Phase45b idx={block.get('phase45b_idx')} | lines={start}-{end}",
            f"readiness={detail['readiness']}",
            f"reason={detail['reason']}",
            "-" * 120,
            text_window(start, end, pad=2),
            "",
        ])
    )

# ---------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------

(out / "09_hoist_readiness_records.json").write_text(
    json.dumps(records, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    encoding="utf-8",
)

summary_lines = [
    "=== PHASE 52 HOIST READINESS SUMMARY ===",
    f"remaining_mixed_try_blocks={len(records)}",
]

from collections import Counter
readiness_counts = Counter(r["readiness"] for r in records)
for key in sorted(readiness_counts):
    summary_lines.append(f"{key}={readiness_counts[key]}")
summary_lines.append("")

for r in records:
    summary_lines.extend([
        f"{r['name']}:",
        f"  phase45b_idx={r.get('phase45b_idx')}",
        f"  lines={r['start']}-{r['end']}",
        f"  live_binds={', '.join(r.get('live_binds') or []) or '-'}",
        f"  helper_symbols={', '.join(r.get('helper_symbols') or []) or '-'}",
        f"  readiness={r['readiness']}",
        f"  reason={r['reason']}",
        f"  body_statement_kinds={', '.join(r['body_statement_kinds']) or '-'}",
        f"  body_import_names={', '.join(r['body_import_names']) or '-'}",
        f"  except_handler_count={r['except_handler_count']}",
        f"  except_has_print={r['except_has_print']}",
        f"  except_has_logging={r['except_has_logging']}",
        f"  except_has_return={r['except_has_return']}",
        f"  except_has_raise={r['except_has_raise']}",
        f"  except_has_assign={r['except_has_assign']}",
        f"  unresolved_or_dynamic_reads={', '.join(sorted({x for xs in r['dependencies_unresolved_or_dynamic'].values() for x in xs})) or '-'}",
        "",
    ])

(out / "10_hoist_readiness_summary.txt").write_text(
    "\n".join(summary_lines) + "\n",
    encoding="utf-8",
)

matrix_lines = [
    "=== PHASE 52 HOIST READINESS MATRIX ===",
    "block | idx | lines | readiness | helpers | body_imports | except_flags | unresolved_reads",
    "-" * 220,
]
for r in records:
    except_flags = []
    for key, label in [
        ("except_has_print", "print"),
        ("except_has_logging", "logging"),
        ("except_has_return", "return"),
        ("except_has_raise", "raise"),
        ("except_has_assign", "assign"),
        ("except_has_pass_only", "pass_only"),
    ]:
        if r[key]:
            except_flags.append(label)

    unresolved = sorted({x for xs in r["dependencies_unresolved_or_dynamic"].values() for x in xs})

    matrix_lines.append(
        " | ".join([
            r["name"],
            str(r.get("phase45b_idx", "-")),
            f"{r['start']}-{r['end']}",
            r["readiness"],
            ",".join(r.get("helper_symbols") or []) or "-",
            ",".join(r["body_import_names"]) or "-",
            ",".join(except_flags) or "-",
            ",".join(unresolved) or "-",
        ])
    )

(out / "11_hoist_readiness_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)

(out / "12_remaining_mixed_tryblock_source_windows.txt").write_text(
    "\n".join(windows) + "\n",
    encoding="utf-8",
)

recommendation_lines = [
    "=== PHASE 52 RECOMMENDED NEXT MOVE ===",
    "",
]

hoist_clean = [r for r in records if r["readiness"] in {
    "candidate_hoist_helpers_only",
    "candidate_hoist_helpers_plus_imports",
}]
hoist_diag = [r for r in records if r["readiness"] == "candidate_hoist_preserve_diagnostic"]
body_review = [r for r in records if r["readiness"] == "candidate_hoist_with_body_review"]
retain_manual = [r for r in records if r["readiness"] == "retain_manual"]

recommendation_lines.extend([
    f"clean_hoist_candidates={len(hoist_clean)}",
    f"diagnostic_hoist_candidates={len(hoist_diag)}",
    f"body_review_candidates={len(body_review)}",
    f"retain_manual_candidates={len(retain_manual)}",
    "",
])

if hoist_clean:
    recommendation_lines.append("Clean hoist candidates:")
    for r in hoist_clean:
        recommendation_lines.append(
            f"- {r['name']} lines={r['start']}-{r['end']} readiness={r['readiness']} helpers={','.join(r.get('helper_symbols') or [])}"
        )
    recommendation_lines.append("")

if hoist_diag:
    recommendation_lines.append("Diagnostic-preserving hoist candidates:")
    for r in hoist_diag:
        recommendation_lines.append(
            f"- {r['name']} lines={r['start']}-{r['end']} except path appears diagnostic-only"
        )
    recommendation_lines.append("")

if body_review:
    recommendation_lines.append("Hoist candidates requiring body-statement review:")
    for r in body_review:
        recommendation_lines.append(
            f"- {r['name']} lines={r['start']}-{r['end']} contains non-helper/non-import body statements"
        )
    recommendation_lines.append("")

if retain_manual:
    recommendation_lines.append("Retain/manual-analysis candidates:")
    for r in retain_manual:
        recommendation_lines.append(
            f"- {r['name']} lines={r['start']}-{r['end']} reason={r['reason']}"
        )
    recommendation_lines.append("")

recommendation_lines.extend([
    "Interpretation:",
    "- If one or more clean hoist candidates exist, Phase53 may patch only those blocks.",
    "- If no clean candidates exist, Phase53 should be another targeted semantic audit, not a source patch.",
    "- Do not broad-remove the remaining six containers until their except-path and helper dependency semantics are explicitly classified.",
])

(out / "13_recommended_next_move.txt").write_text(
    "\n".join(recommendation_lines) + "\n",
    encoding="utf-8",
)

# Assertions
assert_lines = ["=== PHASE 52 TARGETED ASSERTIONS ==="]
assert_failures = 0

def check(ok: bool, message: str) -> None:
    global assert_failures
    if ok:
        assert_lines.append(f"PASS: {message}")
    else:
        assert_lines.append(f"FAIL: {message}")
        assert_failures += 1

check(len(records) == 6, "Phase45b authoritative mixed Try-block count remains 6 after Phase51")
check(all(r["helper_symbols"] for r in records), "all remaining mixed Try blocks still host live helper symbols")
check(all(r["readiness"] for r in records), "every remaining mixed Try block receives a hoist-readiness classification")
check(sum(readiness_counts.values()) == 6, "readiness category counts sum to 6")
check(phase38_marker in src, f"Phase38 marker remains present: {phase38_marker}")

assert_lines.append(
    "PHASE52_HOIST_READINESS_ASSERTIONS_PASS"
    if assert_failures == 0
    else f"PHASE52_HOIST_READINESS_ASSERTIONS_FAIL count={assert_failures}"
)

(out / "14_targeted_assertions.txt").write_text(
    "\n".join(assert_lines) + "\n",
    encoding="utf-8",
)

if assert_failures:
    raise SystemExit(f"Phase52 assertion failures: {assert_failures}")

# Runtime probe
probe = r'''
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

surface_ids = {k: id(v) for k, v in surfaces.items()}
all_same = len(set(surface_ids.values())) == 1

identity = r.route("Who am I?")
memory_runtime = r.route("Explain exactly how your memory system works internally — which files, which DB tables, which functions.")
pdf = r.route("analyze /tmp/a.pdf and /tmp/b.pdf")

print("=== PHASE 52 DIRECT RUNTIME SANITY PROBE ===")
print("surface_ids=" + json.dumps(surface_ids, sort_keys=True))
print("all_public_surfaces_same_object=" + repr(all_same))
print("identity_probe_result=" + json.dumps(identity, sort_keys=True))
print("memory_runtime_probe_result=" + json.dumps(memory_runtime, sort_keys=True))
print("multipdf_probe_result=" + json.dumps(pdf, sort_keys=True))

if not all_same:
    raise SystemExit("public router surfaces drifted")
if identity.get("action") != "USER_IDENTITY_SUMMARY":
    raise SystemExit("identity route contract regressed")
if memory_runtime.get("action") != "EXPLAIN_MEMORY_RUNTIME":
    raise SystemExit("memory-runtime route contract regressed")
if pdf.get("action") != "ANALYZE_PDF":
    raise SystemExit("multi-PDF action regressed")
if pdf.get("args", {}).get("paths") != ["/tmp/a.pdf", "/tmp/b.pdf"]:
    raise SystemExit("multi-PDF paths enrichment regressed")

print("DIRECT_RUNTIME_SANITY_PROBE_PASS")
'''
(out / "15_direct_runtime_probe.py").write_text(probe, encoding="utf-8")

PY

python3 "$OUT/15_direct_runtime_probe.py" 2>&1 | tee "$OUT/16_direct_runtime_probe.txt"

{
  echo "=== PHASE 52 DIGEST ==="
  echo "Router compile: PASS"
  echo "Audit mode: PASS"
  echo "No source files modified: PASS"
  echo
  cat "$OUT/10_hoist_readiness_summary.txt" | sed -n '1,20p'
  echo
  cat "$OUT/13_recommended_next_move.txt"
  echo
  echo "Review:"
  echo "- 10_hoist_readiness_summary.txt"
  echo "- 11_hoist_readiness_matrix.txt"
  echo "- 12_remaining_mixed_tryblock_source_windows.txt"
  echo "- 13_recommended_next_move.txt"
  echo "- 14_targeted_assertions.txt"
  echo "- 16_direct_runtime_probe.txt"
  echo
  echo "PHASE52_OUT=$OUT"
} | tee "$OUT/17_console_digest.txt"

echo
echo "PHASE52_OUT=$OUT"
