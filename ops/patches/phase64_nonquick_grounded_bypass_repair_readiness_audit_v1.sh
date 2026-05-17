#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase64_nonquick_grounded_bypass_repair_readiness_audit_${STAMP}"

ENGINE="eli/kernel/engine.py"
EXECUTOR="eli/execution/executor_enhanced.py"
FINAL_PROVIDER="eli/runtime/final_response_provider.py"
RESPONSE_CONTRACTS="eli/runtime/response_contracts.py"
CONTROL_CONTRACTS="eli/runtime/control_contracts.py"

mkdir -p "$OUT"

for f in "$ENGINE" "$EXECUTOR" "$FINAL_PROVIDER" "$RESPONSE_CONTRACTS" "$CONTROL_CONTRACTS"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing required file: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase64 — Non-Quick Grounded Bypass Repair Readiness Audit

Purpose:

Phase63 proved two live engine middleware paths violate the non-Quick synthesis
contract:

- MEMORY_STATUS.recent_processing
- SELF_REPORT.recent_updates

Both currently return grounded evidence directly in non-Quick modes while
claiming synthesis validation.

This audit does not modify source. It determines the safest repair target by
inventorying:

1. Existing synthesis helper functions.
2. Generic grounded response/output providers.
3. Exact deterministic evidence object shapes for the two affected actions.
4. Which repair strategy is least invasive and semantically aligned with the
   already-correct EXPLAIN_MEMORY_RUNTIME non-Quick synthesis path.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile \
  "$ENGINE" \
  "$EXECUTOR" \
  "$FINAL_PROVIDER" \
  "$RESPONSE_CONTRACTS" \
  "$CONTROL_CONTRACTS" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])
root = Path.cwd()

paths = {
    "engine": root / "eli/kernel/engine.py",
    "executor": root / "eli/execution/executor_enhanced.py",
    "final_provider": root / "eli/runtime/final_response_provider.py",
    "response_contracts": root / "eli/runtime/response_contracts.py",
    "control_contracts": root / "eli/runtime/control_contracts.py",
}

texts = {
    name: path.read_text(encoding="utf-8", errors="replace")
    for name, path in paths.items()
}
lines = {
    name: text.splitlines()
    for name, text in texts.items()
}

# -----------------------------------------------------------------------------
# 1. Engine synthesis/helper inventory
# -----------------------------------------------------------------------------

engine_tree = ast.parse(texts["engine"])
engine_defs = []

for node in ast.walk(engine_tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = node.name
        low = name.lower()
        if any(token in low for token in (
            "synth",
            "ground",
            "response",
            "final",
            "control",
            "render",
        )):
            engine_defs.append({
                "name": name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
            })

engine_defs.sort(key=lambda x: x["lineno"])

(out / "01_engine_candidate_helper_inventory.json").write_text(
    json.dumps(engine_defs, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

helper_lines = ["=== ENGINE CANDIDATE HELPER INVENTORY ==="]
for row in engine_defs:
    helper_lines.append(
        f"{row['lineno']:>6}-{str(row['end_lineno'] or '?'):>6}  {row['name']}"
    )
(out / "02_engine_candidate_helper_inventory.txt").write_text(
    "\n".join(helper_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 2. High-value exact symbol searches
# -----------------------------------------------------------------------------

SEARCH_TERMS = [
    "_mw_rs_synthesize",
    "_mw_mem_runtime_strict_synthesize",
    "synthesis_validated",
    "quick_direct_allowed",
    "final_response",
    "contract_for_action",
    "ResponseContract",
    "grounded",
    "evidence_used",
    "gguf_used",
    "recent_memory_processing_nonquick_grounded_no_gguf_v4",
    "self_report_recent_updates_nonquick_grounded_no_gguf_v4",
]

search_report = ["=== FOCUSED SYMBOL SEARCH INVENTORY ==="]

for name, text in texts.items():
    file_lines = lines[name]
    search_report.append("")
    search_report.append("=" * 110)
    search_report.append(f"{name}: {paths[name]}")
    search_report.append("=" * 110)

    for term in SEARCH_TERMS:
        hits = []
        for i, line in enumerate(file_lines, start=1):
            if term in line:
                hits.append((i, line.rstrip()))

        search_report.append(f"\n[{term}] hit_count={len(hits)}")
        if hits:
            for i, line in hits[:80]:
                search_report.append(f"{i}: {line}")
        else:
            search_report.append("NO_HITS")

(out / "03_focused_symbol_search_inventory.txt").write_text(
    "\n".join(search_report) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 3. Extract exact source windows for key helper definitions
# -----------------------------------------------------------------------------

TARGET_HELPERS = [
    "_mw_rs_synthesize",
    "_mw_mem_runtime_strict_synthesize",
    "_mw_rs_quick_direct",
    "_mw_mem_runtime_strict_collect_evidence",
    "_mw_mem_runtime_strict_synthesize",
]

def find_function_window(text_lines: list[str], func_name: str) -> tuple[int | None, int | None]:
    start = None
    indent = None

    for i, line in enumerate(text_lines, start=1):
        if re.match(rf"^def\s+{re.escape(func_name)}\s*\(", line):
            start = i
            indent = len(line) - len(line.lstrip())
            break

    if start is None:
        return None, None

    end = len(text_lines)
    for j in range(start + 1, len(text_lines) + 1):
        line = text_lines[j - 1]
        stripped = line.strip()
        if not stripped:
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent and re.match(r"^(def|class)\s+", stripped):
            end = j - 1
            break

    return start, end

window_lines = ["=== KEY ENGINE HELPER SOURCE WINDOWS ==="]

for func in TARGET_HELPERS:
    start, end = find_function_window(lines["engine"], func)
    window_lines.append("")
    window_lines.append("=" * 110)
    window_lines.append(f"{func}  start={start} end={end}")
    window_lines.append("=" * 110)
    if start is None:
        window_lines.append("FUNCTION_NOT_FOUND")
        continue

    for ln in range(start, min(end or start, start + 220) + 1):
        window_lines.append(f"{ln:>6}: {lines['engine'][ln - 1]}")

(out / "04_key_engine_helper_source_windows.txt").write_text(
    "\n".join(window_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 4. Inspect runtime signatures of likely provider/contract functions
# -----------------------------------------------------------------------------

signature_rows = []

MODULE_FUNCS = [
    ("eli.runtime.final_response_provider", None),
    ("eli.runtime.response_contracts", None),
    ("eli.runtime.control_contracts", None),
]

for module_name, _ in MODULE_FUNCS:
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        signature_rows.append({
            "module": module_name,
            "import_error": f"{type(e).__name__}: {e}",
            "functions": [],
        })
        continue

    funcs = []
    for name in sorted(dir(mod)):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if callable(obj):
            low = name.lower()
            if any(k in low for k in ("response", "contract", "final", "render", "provide", "compose")):
                try:
                    sig = str(inspect.signature(obj))
                except Exception as e:
                    sig = f"<signature unavailable: {type(e).__name__}: {e}>"
                funcs.append({
                    "name": name,
                    "signature": sig,
                })

    signature_rows.append({
        "module": module_name,
        "functions": funcs,
    })

(out / "05_runtime_candidate_provider_signatures.json").write_text(
    json.dumps(signature_rows, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

sig_lines = ["=== RUNTIME CANDIDATE PROVIDER / CONTRACT SIGNATURES ==="]
for row in signature_rows:
    sig_lines.append("")
    sig_lines.append(f"[{row['module']}]")
    if row.get("import_error"):
        sig_lines.append(f"IMPORT_ERROR={row['import_error']}")
        continue
    funcs = row.get("functions") or []
    if not funcs:
        sig_lines.append("NO_MATCHING_PUBLIC_CALLABLES")
    for func in funcs:
        sig_lines.append(f"{func['name']}{func['signature']}")

(out / "06_runtime_candidate_provider_signatures.txt").write_text(
    "\n".join(sig_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 5. Executor evidence-shape probe for affected actions
# -----------------------------------------------------------------------------

evidence_probe_rows: list[dict[str, Any]] = []

try:
    executor = importlib.import_module("eli.execution.executor_enhanced")
    execute = getattr(executor, "execute")
except Exception as e:
    execute = None
    evidence_probe_rows.append({
        "probe": "__executor_import__",
        "error": f"{type(e).__name__}: {e}",
    })

if execute is not None:
    probes = [
        (
            "recent_memory_processing",
            "MEMORY_STATUS",
            {
                "memory_scope": "recent_processing",
                "question": "What memories have you been processing lately?",
            },
        ),
        (
            "self_report_recent_updates",
            "SELF_REPORT",
            {
                "self_report_scope": "recent_updates",
                "question": "What have you been working on recently?",
            },
        ),
    ]

    for probe_id, action, args in probes:
        try:
            result = execute(action, args)
            if isinstance(result, dict):
                compact = {
                    "probe": probe_id,
                    "action": action,
                    "args": args,
                    "result_type": "dict",
                    "top_level_keys": sorted(result.keys()),
                    "ok": result.get("ok"),
                    "result_action": result.get("action"),
                    "evidence_source": result.get("evidence_source"),
                    "content_preview": str(result.get("content") or result.get("response") or "")[:700],
                    "report_keys": sorted((result.get("report") or {}).keys()) if isinstance(result.get("report"), dict) else [],
                    "report_preview": {
                        k: (result.get("report") or {}).get(k)
                        for k in sorted((result.get("report") or {}).keys())[:40]
                    } if isinstance(result.get("report"), dict) else {},
                }
            else:
                compact = {
                    "probe": probe_id,
                    "action": action,
                    "args": args,
                    "result_type": type(result).__name__,
                    "repr_preview": repr(result)[:1500],
                }
            evidence_probe_rows.append(compact)
        except Exception as e:
            evidence_probe_rows.append({
                "probe": probe_id,
                "action": action,
                "args": args,
                "error": f"{type(e).__name__}: {e}",
            })

(out / "07_executor_evidence_shape_probe.json").write_text(
    json.dumps(evidence_probe_rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

probe_lines = ["=== EXECUTOR EVIDENCE SHAPE PROBE ==="]
for row in evidence_probe_rows:
    probe_lines.append("")
    probe_lines.append(f"[{row.get('probe')}]")
    for k, v in row.items():
        if k == "probe":
            continue
        probe_lines.append(f"{k}={json.dumps(v, sort_keys=True, ensure_ascii=False) if isinstance(v, (dict, list)) else v}")

(out / "08_executor_evidence_shape_probe.txt").write_text(
    "\n".join(probe_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 6. Readiness verdict
# -----------------------------------------------------------------------------

engine_helper_names = {row["name"] for row in engine_defs}
has_runtime_synth = "_mw_rs_synthesize" in engine_helper_names
has_memory_synth = "_mw_mem_runtime_strict_synthesize" in engine_helper_names

final_provider_hits = any(
    row.get("functions")
    for row in signature_rows
    if row.get("module") == "eli.runtime.final_response_provider"
)

verdict_lines = [
    "=== PHASE64 NON-QUICK GROUNDED BYPASS REPAIR READINESS VERDICT ===",
    f"HAS_RUNTIME_STATUS_SYNTH_HELPER={has_runtime_synth}",
    f"HAS_MEMORY_RUNTIME_SYNTH_HELPER={has_memory_synth}",
    f"HAS_FINAL_RESPONSE_PROVIDER_PUBLIC_CANDIDATES={bool(final_provider_hits)}",
    "",
    "Interpretation:",
]

if has_memory_synth and has_runtime_synth:
    verdict_lines.extend([
        "- The codebase already contains successful local precedents for the required pattern:",
        "  Quick direct evidence; Non-Quick evidence collection -> synthesis -> validated synthesized return.",
        "- Phase64 should not add a new architectural concept. The repair should mirror or reuse those existing synthesis conventions.",
    ])
else:
    verdict_lines.extend([
        "- One or more expected synthesis helper precedents were not detected.",
        "- Review helper windows before patching.",
    ])

verdict_lines.extend([
    "",
    "Patch planning rule:",
    "- Do not retain any non-Quick `*_no_gguf_*` path labels.",
    "- Do not set `synthesis_validated=True` unless an actual non-Quick synthesis function was called and validated.",
    "- Quick may still return direct compact evidence.",
    "- Non-Quick must return synthesized text generated from grounded evidence.",
    "",
    "Review:",
    "- 02_engine_candidate_helper_inventory.txt",
    "- 03_focused_symbol_search_inventory.txt",
    "- 04_key_engine_helper_source_windows.txt",
    "- 06_runtime_candidate_provider_signatures.txt",
    "- 08_executor_evidence_shape_probe.txt",
])

(out / "09_repair_readiness_verdict.txt").write_text(
    "\n".join(verdict_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict_lines))
print()
print(f"PHASE64_OUT={out}")
PY
