#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase61_grounded_synthesis_contract_consumption_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

cat > "$OUT/SUMMARY.md" <<EOF
# Phase61 — Grounded Synthesis Contract Consumption Audit

Generated: $(date -Is)  
Root: $ROOT  
Router: $ROUTER  
Mode: audit only — no source files modified

## Purpose

Phase60 closed the router consolidation campaign.

Phase61 asks the next necessary question:

> The router emits the right high-priority route contracts.  
> Does the downstream ELI runtime actually consume those contracts?

This audit checks:

1. Canonical high-risk route outputs after Phase60
2. Emitted contract metadata for grounded/non-Quick synthesis
3. Non-router source references for each high-risk routed action
4. Non-router source references for synthesis-control contract keys
5. Non-router source references for special response_contract values
6. Whether any emitted contract appears router-local only, meaning it may be declarative rather than enforced

This phase does not patch anything.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import importlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])
root = Path.cwd()
router_path = root / "eli/execution/router_enhanced.py"

router = importlib.import_module("eli.execution.router_enhanced")

# ---------------------------------------------------------------------
# 1. High-risk route probes
# ---------------------------------------------------------------------

CASES: list[tuple[str, str]] = [
    (
        "runtime_status_full",
        "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
    ),
    (
        "memory_runtime_exact",
        "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    ),
    (
        "personal_memory_summary",
        "What do you know about me from memory?",
    ),
    (
        "memory_count",
        "How many memories do you have?",
    ),
    (
        "recent_memory_processing",
        "What memories have you been processing lately?",
    ),
    (
        "self_report_recent_updates",
        "What have you been working on recently?",
    ),
    (
        "gui_actual_scan_proof",
        "Did you actually scan the GUI file in full?",
    ),
    (
        "pdf_multi",
        "analyze /tmp/a.pdf and /tmp/b.pdf",
    ),
]

probe_results: dict[str, dict[str, Any]] = {}

for case_id, prompt in CASES:
    result = router.route(prompt)
    if not isinstance(result, dict):
        result = {
            "__non_dict_result__": repr(result),
        }
    probe_results[case_id] = {
        "prompt": prompt,
        "result": result,
    }

(out / "01_route_probe_results.json").write_text(
    json.dumps(probe_results, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

probe_lines = ["=== PHASE61 HIGH-RISK ROUTE PROBE MATRIX ==="]
for case_id, payload in probe_results.items():
    result = payload["result"]
    action = result.get("action")
    args = result.get("args") or {}
    meta = result.get("meta") or {}
    probe_lines.extend([
        "",
        f"[{case_id}]",
        f"prompt={payload['prompt']}",
        f"action={action}",
        f"args={json.dumps(args, sort_keys=True, ensure_ascii=False)}",
        f"meta={json.dumps(meta, sort_keys=True, ensure_ascii=False)}",
    ])

(out / "02_route_probe_matrix.txt").write_text(
    "\n".join(probe_lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 2. Extract emitted actions and contract metadata
# ---------------------------------------------------------------------

actions: set[str] = set()
meta_keys: set[str] = set()
meta_values: set[str] = set()

for payload in probe_results.values():
    result = payload["result"]
    action = str(result.get("action") or "").strip()
    if action:
        actions.add(action)

    meta = result.get("meta") or {}
    if isinstance(meta, dict):
        for key, value in meta.items():
            meta_keys.add(str(key))
            if isinstance(value, str) and value.strip():
                meta_values.add(value.strip())

# Focused contract keys that matter for your non-Quick enforcement rule.
CONTRACT_KEYS = [
    "need_grounding",
    "grounded_required",
    "allow_chat_without_evidence",
    "forbid_chat_fallback",
    "forbid_unverified_generation",
    "requires_grounded_synthesis",
    "requires_output_validation",
    "quick_direct_allowed",
    "response_contract",
    "task_family",
]

# Known high-value response contract values currently emitted in the router.
CONTRACT_VALUES = [
    "quick_direct_nonquick_persona_synthesis",
    "canonical_grounded_memory_runtime_no_raw_gguf",
]

# Add any actual emitted response_contract values so the audit adapts to the source.
for payload in probe_results.values():
    result = payload["result"]
    meta = result.get("meta") or {}
    if isinstance(meta, dict):
        rv = meta.get("response_contract")
        if isinstance(rv, str) and rv.strip() and rv.strip() not in CONTRACT_VALUES:
            CONTRACT_VALUES.append(rv.strip())

(out / "03_emitted_contract_inventory.txt").write_text(
    "\n".join([
        "=== EMITTED ROUTE ACTIONS ===",
        *sorted(actions),
        "",
        "=== FOCUSED CONTRACT KEYS AUDITED ===",
        *CONTRACT_KEYS,
        "",
        "=== RESPONSE CONTRACT VALUES AUDITED ===",
        *CONTRACT_VALUES,
        "",
        "=== ALL META KEYS EMITTED BY THE PROBES ===",
        *sorted(meta_keys),
        "",
        "=== ALL STRING META VALUES EMITTED BY THE PROBES ===",
        *sorted(meta_values),
    ]) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 3. Search ELI/config source for downstream references
# ---------------------------------------------------------------------

SEARCH_ROOTS = [
    root / "eli",
    root / "config",
]

TEXT_SUFFIXES = {
    ".py", ".json", ".md", ".txt", ".toml", ".yaml", ".yml",
}

EXCLUDED_FILES = {
    router_path.resolve(),
}

source_files: list[Path] = []
for base in SEARCH_ROOTS:
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in EXCLUDED_FILES:
            continue
        source_files.append(path)

def text_of(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

def grep_exact(needle: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for path in source_files:
        text = text_of(path)
        if not text:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            if needle in line:
                hits.append({
                    "path": str(path.relative_to(root)),
                    "line": idx,
                    "text": line.rstrip(),
                })
    return hits

action_hits: dict[str, list[dict[str, Any]]] = {}
for action in sorted(actions):
    action_hits[action] = grep_exact(action)

key_hits: dict[str, list[dict[str, Any]]] = {}
for key in CONTRACT_KEYS:
    key_hits[key] = grep_exact(key)

value_hits: dict[str, list[dict[str, Any]]] = {}
for value in CONTRACT_VALUES:
    value_hits[value] = grep_exact(value)

(out / "04_action_downstream_reference_inventory.json").write_text(
    json.dumps(action_hits, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

(out / "05_contract_key_downstream_reference_inventory.json").write_text(
    json.dumps(key_hits, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

(out / "06_contract_value_downstream_reference_inventory.json").write_text(
    json.dumps(value_hits, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

def render_hits(title: str, mapping: dict[str, list[dict[str, Any]]]) -> str:
    lines = [title]
    for key in sorted(mapping):
        hits = mapping[key]
        lines.append("")
        lines.append(f"[{key}] downstream_hit_count={len(hits)}")
        if not hits:
            lines.append("NO_DOWNSTREAM_HITS")
            continue
        for hit in hits[:80]:
            lines.append(f"{hit['path']}:{hit['line']}: {hit['text']}")
        if len(hits) > 80:
            lines.append(f"... truncated {len(hits) - 80} additional hit(s)")
    return "\n".join(lines) + "\n"

(out / "07_action_downstream_reference_inventory.txt").write_text(
    render_hits("=== ACTION DOWNSTREAM REFERENCE INVENTORY ===", action_hits),
    encoding="utf-8",
)

(out / "08_contract_key_downstream_reference_inventory.txt").write_text(
    render_hits("=== CONTRACT KEY DOWNSTREAM REFERENCE INVENTORY ===", key_hits),
    encoding="utf-8",
)

(out / "09_contract_value_downstream_reference_inventory.txt").write_text(
    render_hits("=== CONTRACT VALUE DOWNSTREAM REFERENCE INVENTORY ===", value_hits),
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 4. Closure assertions
# ---------------------------------------------------------------------

assertions: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, failure_detail: str) -> None:
    assertions.append((label, ok, failure_detail))

# Router probes should all yield dictionaries with actions.
for case_id, payload in probe_results.items():
    result = payload["result"]
    check(
        f"{case_id} emits an action-bearing route result",
        isinstance(result, dict) and bool(str(result.get("action") or "").strip()),
        f"route result did not expose a usable action: {result!r}",
    )

# Every emitted high-risk action should exist somewhere outside router.py.
for action in sorted(actions):
    check(
        f"action {action} has at least one non-router downstream source reference",
        len(action_hits.get(action, [])) > 0,
        f"no non-router reference found for emitted action {action}",
    )

# Focused contract keys should be downstream-visible, otherwise they may be inert declarations.
for key in CONTRACT_KEYS:
    emitted = key in meta_keys
    if not emitted:
        # Do not fail for keys not emitted by current probes.
        continue
    check(
        f"emitted contract key {key} has at least one non-router downstream reference",
        len(key_hits.get(key, [])) > 0,
        f"contract key {key} is emitted by router probes but no non-router consumer/reference was found",
    )

# High-value response_contract values should not be router-local only if they are emitted.
for value in CONTRACT_VALUES:
    actually_emitted = value in meta_values
    if not actually_emitted:
        continue
    check(
        f"emitted response_contract value {value} has at least one non-router downstream reference",
        len(value_hits.get(value, [])) > 0,
        f"response_contract value {value} is emitted but no non-router consumer/reference was found",
    )

failed = 0
lines = ["=== PHASE61 TARGETED CONTRACT-CONSUMPTION ASSERTIONS ==="]

for label, ok, detail in assertions:
    if ok:
        lines.append(f"PASS: {label}")
    else:
        failed += 1
        lines.append(f"FAIL: {label} — {detail}")

lines.append("")
lines.append(f"TARGETED_ASSERTION_FAILURES={failed}")

(out / "10_targeted_contract_consumption_assertions.txt").write_text(
    "\n".join(lines) + "\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# 5. Final interpretation
# ---------------------------------------------------------------------

closed = failed == 0

verdict = [
    "=== PHASE61 GROUNDED SYNTHESIS CONTRACT CONSUMPTION VERDICT ===",
    f"GROUNDED_SYNTHESIS_CONTRACT_CONSUMPTION_CLOSED={'TRUE' if closed else 'FALSE'}",
    f"TARGETED_ASSERTION_FAILURES={failed}",
    "",
]

if closed:
    verdict.extend([
        "Conclusion:",
        "- The sampled high-risk router contracts are not merely router-local declarations.",
        "- Their emitted actions and contract markers have non-router source references.",
        "- The next warranted step is a live runtime behavioural probe through ELI itself.",
    ])
else:
    verdict.extend([
        "Conclusion:",
        "- Router consolidation is closed, but downstream contract consumption is not yet proven clean.",
        "- At least one emitted action, contract key, or response_contract value appears router-local only.",
        "- Do not patch blindly. Inspect the failed entries in the targeted assertion report and the downstream reference inventories.",
        "- If the missing hits are genuine, the next repair belongs downstream in the cognition/execution/output-governance path, not in the router.",
    ])

verdict.extend([
    "",
    "Review:",
    "- 02_route_probe_matrix.txt",
    "- 03_emitted_contract_inventory.txt",
    "- 07_action_downstream_reference_inventory.txt",
    "- 08_contract_key_downstream_reference_inventory.txt",
    "- 09_contract_value_downstream_reference_inventory.txt",
    "- 10_targeted_contract_consumption_assertions.txt",
])

(out / "11_contract_consumption_verdict.txt").write_text(
    "\n".join(verdict) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict))
print()
print(f"PHASE61_OUT={out}")

if not closed:
    raise SystemExit(1)
PY
