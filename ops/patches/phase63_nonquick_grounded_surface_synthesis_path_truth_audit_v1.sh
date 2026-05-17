#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
ENGINE="eli/kernel/engine.py"
EXECUTOR="eli/execution/executor_enhanced.py"

mkdir -p "$OUT"

for f in "$ROUTER" "$ENGINE" "$EXECUTOR"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing required file: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase63 — Non-Quick Grounded Surface Synthesis Path Truth Audit

Generated: $(date -Is)  
Root: $ROOT  

## Purpose

Phase62 proved the Phase61 contract-marker failures were mostly vocabulary
drift / semantic ambiguity rather than missing downstream action plumbing.

However, the Phase62 enforcement windows exposed a higher-risk possibility:

- `recent_memory_processing`
- `self_report_recent_updates`

may be returning deterministic grounded evidence directly in non-Quick modes,
instead of passing that evidence through the required synthesis pipeline.

This audit inspects the live engine source blocks that control those surfaces
and determines whether they contain direct early-return bypasses in non-Quick
paths.

No source files are modified.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ROUTER" "$ENGINE" "$EXECUTOR" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import importlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

out = Path(sys.argv[1])
root = Path.cwd()

engine_path = root / "eli/kernel/engine.py"
executor_path = root / "eli/execution/executor_enhanced.py"

engine_text = engine_path.read_text(encoding="utf-8", errors="replace")
executor_text = executor_path.read_text(encoding="utf-8", errors="replace")
engine_lines = engine_text.splitlines()
executor_lines = executor_text.splitlines()

router = importlib.import_module("eli.execution.router_enhanced")

# -----------------------------------------------------------------------------
# 1. Live router route probes for affected surfaces
# -----------------------------------------------------------------------------

ROUTE_CASES = [
    (
        "memory_runtime_exact",
        "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
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
        "memory_count",
        "How many memories do you have?",
    ),
    (
        "gui_actual_scan_proof",
        "Did you actually scan the GUI file in full?",
    ),
]

route_probe_rows: list[dict[str, Any]] = []

for case_id, prompt in ROUTE_CASES:
    result = router.route(prompt)
    if not isinstance(result, dict):
        result = {"__non_dict__": repr(result)}

    route_probe_rows.append({
        "case_id": case_id,
        "prompt": prompt,
        "action": result.get("action"),
        "args": result.get("args") or {},
        "meta": result.get("meta") or {},
    })

(out / "01_route_probe_matrix.json").write_text(
    json.dumps(route_probe_rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

txt = ["=== PHASE63 ROUTE PROBE MATRIX ==="]
for row in route_probe_rows:
    txt.extend([
        "",
        f"[{row['case_id']}]",
        f"prompt={row['prompt']}",
        f"action={row['action']}",
        f"args={json.dumps(row['args'], sort_keys=True, ensure_ascii=False)}",
        f"meta={json.dumps(row['meta'], sort_keys=True, ensure_ascii=False)}",
    ])
(out / "02_route_probe_matrix.txt").write_text("\n".join(txt) + "\n", encoding="utf-8")

# -----------------------------------------------------------------------------
# 2. Extract exact engine middleware blocks by marker
# -----------------------------------------------------------------------------

@dataclass
class Block:
    block_id: str
    start_marker: str
    end_marker: str
    found: bool
    start_line: int | None
    end_line: int | None
    text: str

BLOCK_SPECS = [
    (
        "runtime_status_gold_standard",
        "ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1",
        "END ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1",
    ),
    (
        "memory_runtime_strict",
        "ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1",
        "END ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1",
    ),
    (
        "recent_memory_processing",
        "ELI_ENGINE_MIDDLEWARE_RECENT_MEMORY_PROCESSING_V4",
        "END ELI_ENGINE_MIDDLEWARE_RECENT_MEMORY_PROCESSING_V4",
    ),
    (
        "self_report_recent_updates",
        "ELI_ENGINE_MIDDLEWARE_SELF_REPORT_RECENT_UPDATES_V4",
        "END ELI_ENGINE_MIDDLEWARE_SELF_REPORT_RECENT_UPDATES_V4",
    ),
]

def extract_block(block_id: str, start_marker: str, end_marker: str) -> Block:
    start_idx = next((i for i, line in enumerate(engine_lines) if start_marker in line), None)
    if start_idx is None:
        return Block(block_id, start_marker, end_marker, False, None, None, "")

    end_idx = next(
        (i for i in range(start_idx, len(engine_lines)) if end_marker in engine_lines[i]),
        None,
    )
    if end_idx is None:
        return Block(
            block_id,
            start_marker,
            end_marker,
            False,
            start_idx + 1,
            None,
            "\n".join(engine_lines[start_idx:]),
        )

    return Block(
        block_id,
        start_marker,
        end_marker,
        True,
        start_idx + 1,
        end_idx + 1,
        "\n".join(engine_lines[start_idx:end_idx + 1]),
    )

blocks = [extract_block(*spec) for spec in BLOCK_SPECS]

(out / "03_engine_block_inventory.json").write_text(
    json.dumps([asdict(b) for b in blocks], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

block_inventory = ["=== PHASE63 ENGINE BLOCK INVENTORY ==="]
for b in blocks:
    block_inventory.extend([
        "",
        f"[{b.block_id}]",
        f"found={b.found}",
        f"start_line={b.start_line}",
        f"end_line={b.end_line}",
        f"line_count={(b.end_line - b.start_line + 1) if b.found and b.start_line and b.end_line else 0}",
    ])
(out / "04_engine_block_inventory.txt").write_text(
    "\n".join(block_inventory) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 3. Semantic feature extraction from each block
# -----------------------------------------------------------------------------

@dataclass
class FeatureRow:
    block_id: str
    found: bool
    has_quick_branch_signal: bool
    has_nonquick_signal: bool
    has_direct_evidence_signal: bool
    has_explicit_gguf_synthesis_signal: bool
    sets_gguf_used_false: bool
    contains_explicit_synthesis_helper_call: bool
    contains_return_of_synthesized_output: bool
    contains_no_gguf_label: bool
    contains_synthesis_validated_assignment: bool
    contains_early_return_of_surface_output: bool
    direct_return_lines: list[int]
    no_gguf_lines: list[int]
    gguf_false_lines: list[int]
    synth_lines: list[int]

def global_line_numbers(block: Block, pattern: str) -> list[int]:
    if not block.found or block.start_line is None:
        return []
    hits = []
    for offset, line in enumerate(block.text.splitlines()):
        if re.search(pattern, line):
            hits.append(block.start_line + offset)
    return hits

features: list[FeatureRow] = []

for b in blocks:
    t = b.text

    direct_return_lines = global_line_numbers(
        b,
        r"\breturn\s+_eli_(?:rm|self_mw)_out\b|\breturn\s+_mw_[A-Za-z0-9_]+\b",
    )
    no_gguf_lines = global_line_numbers(b, r"no_gguf|no raw gguf|no-raw-gguf")
    gguf_false_lines = global_line_numbers(b, r'gguf_used["\']?\]?\s*=\s*False|"gguf_used"\s*:\s*False')
    explicit_synthesis_helper_call_lines = global_line_numbers(
        b,
        r"_mw_(?:recent_memory_processing|self_report_recent_updates)_synthesize\s*\(",
    )
    return_of_synthesized_output_lines = global_line_numbers(
        b,
        r"return\s+_eli_(?:rm|self)_mw_out\b",
    )
    synth_lines = global_line_numbers(b, r"synthesi[sz]e|_synth|synthesized via GGUF|GGUF")

    row = FeatureRow(
        block_id=b.block_id,
        found=b.found,
        has_quick_branch_signal=bool(re.search(r"\bquick\b|_is_quick|_quick", t, re.I)),
        has_nonquick_signal=bool(re.search(r"non[-_ ]?quick|nonquick", t, re.I)),
        has_direct_evidence_signal=bool(re.search(r"direct evidence|direct telemetry|quick_direct|evidence returned", t, re.I)),
        has_explicit_gguf_synthesis_signal=bool(re.search(r"synthesi[sz].*GGUF|synthesized via GGUF|_synthesi[sz]e", t, re.I)),
        sets_gguf_used_false=bool(gguf_false_lines),
        contains_explicit_synthesis_helper_call=bool(explicit_synthesis_helper_call_lines),
        contains_return_of_synthesized_output=bool(return_of_synthesized_output_lines),
        contains_no_gguf_label=bool(no_gguf_lines),
        contains_synthesis_validated_assignment="synthesis_validated" in t,
        contains_early_return_of_surface_output=bool(direct_return_lines),
        direct_return_lines=direct_return_lines,
        no_gguf_lines=no_gguf_lines,
        gguf_false_lines=gguf_false_lines,
        synth_lines=synth_lines,
    )
    features.append(row)

(out / "05_block_semantic_feature_matrix.json").write_text(
    json.dumps([asdict(f) for f in features], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

feature_lines = ["=== PHASE63 BLOCK SEMANTIC FEATURE MATRIX ==="]
for f in features:
    feature_lines.extend([
        "",
        f"[{f.block_id}]",
        f"found={f.found}",
        f"has_quick_branch_signal={f.has_quick_branch_signal}",
        f"has_nonquick_signal={f.has_nonquick_signal}",
        f"has_direct_evidence_signal={f.has_direct_evidence_signal}",
        f"has_explicit_gguf_synthesis_signal={f.has_explicit_gguf_synthesis_signal}",
        f"sets_gguf_used_false={f.sets_gguf_used_false}",
        f"contains_explicit_synthesis_helper_call={f.contains_explicit_synthesis_helper_call}",
        f"contains_return_of_synthesized_output={f.contains_return_of_synthesized_output}",
        f"contains_no_gguf_label={f.contains_no_gguf_label}",
        f"contains_synthesis_validated_assignment={f.contains_synthesis_validated_assignment}",
        f"contains_early_return_of_surface_output={f.contains_early_return_of_surface_output}",
        f"direct_return_lines={f.direct_return_lines}",
        f"no_gguf_lines={f.no_gguf_lines}",
        f"gguf_false_lines={f.gguf_false_lines}",
        f"synth_lines={f.synth_lines}",
    ])
(out / "06_block_semantic_feature_matrix.txt").write_text(
    "\n".join(feature_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 4. Targeted interpretation: compliant / risk / unresolved
# -----------------------------------------------------------------------------

feature_by_id = {f.block_id: f for f in features}

interpretations: list[dict[str, Any]] = []

def add_interp(surface: str, verdict: str, reason: str, evidence: dict[str, Any]) -> None:
    interpretations.append({
        "surface": surface,
        "verdict": verdict,
        "reason": reason,
        "evidence": evidence,
    })

# Gold standard checks
mrs = feature_by_id.get("memory_runtime_strict")
if mrs and mrs.found:
    if mrs.has_explicit_gguf_synthesis_signal and mrs.has_direct_evidence_signal:
        add_interp(
            "EXPLAIN_MEMORY_RUNTIME",
            "COMPLIANT_SOURCE_SHAPE",
            "Block contains both Quick direct-evidence handling and explicit non-Quick GGUF synthesis handling.",
            asdict(mrs),
        )
    else:
        add_interp(
            "EXPLAIN_MEMORY_RUNTIME",
            "UNRESOLVED_OR_BROKEN",
            "Expected Quick/direct plus non-Quick/synthesis signals were not both found.",
            asdict(mrs),
        )
else:
    add_interp(
        "EXPLAIN_MEMORY_RUNTIME",
        "BLOCK_MISSING",
        "Required memory-runtime strict middleware block was not found.",
        {},
    )

# Recent memory processing
rm = feature_by_id.get("recent_memory_processing")
if rm and rm.found:
    if (
        rm.contains_no_gguf_label
        and rm.sets_gguf_used_false
        and rm.contains_early_return_of_surface_output
        and not rm.has_explicit_gguf_synthesis_signal
    ):
        add_interp(
            "MEMORY_STATUS.recent_processing",
            "LIKELY_NONQUICK_DIRECT_BYPASS",
            "Block contains non-Quick no-GGUF naming, gguf_used=False, and an early return of the surface output without explicit synthesis signals.",
            asdict(rm),
        )
    elif rm.contains_no_gguf_label and rm.contains_early_return_of_surface_output:
        add_interp(
            "MEMORY_STATUS.recent_processing",
            "HIGH_SUSPICION",
            "Block contains a no-GGUF label and early return; inspect whether any synthesis occurs before return.",
            asdict(rm),
        )
    else:
        add_interp(
            "MEMORY_STATUS.recent_processing",
            "NO_CLEAR_BYPASS_PROVEN",
            "This narrow source-shape audit did not prove a direct non-Quick bypass.",
            asdict(rm),
        )
else:
    add_interp(
        "MEMORY_STATUS.recent_processing",
        "BLOCK_MISSING",
        "Required recent-memory middleware block was not found.",
        {},
    )

# Self-report recent updates
sr = feature_by_id.get("self_report_recent_updates")
if sr and sr.found:
    if (
        sr.contains_no_gguf_label
        and sr.sets_gguf_used_false
        and sr.contains_early_return_of_surface_output
        and not sr.has_explicit_gguf_synthesis_signal
    ):
        add_interp(
            "SELF_REPORT.recent_updates",
            "LIKELY_NONQUICK_DIRECT_BYPASS",
            "Block contains non-Quick no-GGUF naming, gguf_used=False, and an early return of the surface output without explicit synthesis signals.",
            asdict(sr),
        )
    elif (
        sr.sets_gguf_used_false
        and sr.contains_early_return_of_surface_output
        and not (
            sr.contains_explicit_synthesis_helper_call
            and sr.contains_return_of_synthesized_output
        )
    ):
        add_interp(
            "SELF_REPORT.recent_updates",
            "HIGH_SUSPICION",
            "Block sets gguf_used=False and appears to return the surface output directly without sufficient explicit synthesis-helper and synthesized-output return proof.",
            asdict(sr),
        )
    else:
        add_interp(
            "SELF_REPORT.recent_updates",
            "NO_CLEAR_BYPASS_PROVEN",
            "This narrow source-shape audit did not prove a direct non-Quick bypass.",
            asdict(sr),
        )
else:
    add_interp(
        "SELF_REPORT.recent_updates",
        "BLOCK_MISSING",
        "Required self-report recent-updates middleware block was not found.",
        {},
    )

(out / "07_nonquick_direct_bypass_risk_matrix.json").write_text(
    json.dumps(interpretations, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

risk_lines = ["=== PHASE63 NON-QUICK DIRECT-BYPASS RISK MATRIX ==="]
for item in interpretations:
    risk_lines.extend([
        "",
        f"[{item['surface']}]",
        f"verdict={item['verdict']}",
        f"reason={item['reason']}",
    ])
(out / "08_nonquick_direct_bypass_risk_matrix.txt").write_text(
    "\n".join(risk_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 5. Focused source windows around critical hits
# -----------------------------------------------------------------------------

focus_lines = ["=== PHASE63 FOCUSED ENGINE SOURCE WINDOWS ==="]

def emit_window(path_lines: list[str], title: str, line_no: int, radius_before: int = 7, radius_after: int = 12) -> None:
    focus_lines.append("")
    focus_lines.append("=" * 110)
    focus_lines.append(title)
    focus_lines.append("=" * 110)
    start = max(1, line_no - radius_before)
    end = min(len(path_lines), line_no + radius_after)
    for ln in range(start, end + 1):
        focus_lines.append(f"{ln:>6}: {path_lines[ln - 1]}")

for f in features:
    for line_no in sorted(set(f.direct_return_lines + f.no_gguf_lines + f.gguf_false_lines + f.synth_lines)):
        emit_window(engine_lines, f"{f.block_id} hit line {line_no}", line_no)

(out / "09_focused_engine_source_windows.txt").write_text(
    "\n".join(focus_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 6. Assertions
# -----------------------------------------------------------------------------

assertions: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str) -> None:
    assertions.append((label, ok, detail))

check(
    "memory-runtime strict block found",
    bool(mrs and mrs.found),
    "ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1 block missing",
)
check(
    "memory-runtime strict block shows explicit non-Quick synthesis path",
    bool(mrs and mrs.has_explicit_gguf_synthesis_signal),
    "no explicit synthesis signal found in memory-runtime strict block",
)

recent_verdict = next(i["verdict"] for i in interpretations if i["surface"] == "MEMORY_STATUS.recent_processing")
self_verdict = next(i["verdict"] for i in interpretations if i["surface"] == "SELF_REPORT.recent_updates")

check(
    "recent-memory-processing does not present a likely non-Quick direct bypass",
    recent_verdict not in {"LIKELY_NONQUICK_DIRECT_BYPASS", "HIGH_SUSPICION"},
    f"verdict={recent_verdict}",
)
check(
    "self-report recent-updates does not present a likely non-Quick direct bypass",
    self_verdict not in {"LIKELY_NONQUICK_DIRECT_BYPASS", "HIGH_SUSPICION"},
    f"verdict={self_verdict}",
)

failures = 0
assertion_lines = ["=== PHASE63 TARGETED ASSERTIONS ==="]
for label, ok, detail in assertions:
    if ok:
        assertion_lines.append(f"PASS: {label}")
    else:
        failures += 1
        assertion_lines.append(f"FAIL: {label} — {detail}")
assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={failures}")

(out / "10_targeted_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)

# -----------------------------------------------------------------------------
# 7. Verdict
# -----------------------------------------------------------------------------

likely_bypass_count = sum(
    1 for item in interpretations
    if item["verdict"] == "LIKELY_NONQUICK_DIRECT_BYPASS"
)
high_suspicion_count = sum(
    1 for item in interpretations
    if item["verdict"] == "HIGH_SUSPICION"
)

verdict = [
    "=== PHASE63 NON-QUICK GROUNDED SURFACE SYNTHESIS PATH VERDICT ===",
    f"TARGETED_ASSERTION_FAILURES={failures}",
    f"LIKELY_NONQUICK_DIRECT_BYPASS_COUNT={likely_bypass_count}",
    f"HIGH_SUSPICION_COUNT={high_suspicion_count}",
    "",
]

if failures == 0:
    verdict.extend([
        "Verdict:",
        "- This source-path audit did not identify a likely non-Quick direct-evidence bypass in the targeted blocks.",
        "- The next step would be a runtime execution proof audit across Quick and non-Quick modes.",
    ])
else:
    verdict.extend([
        "Verdict:",
        "- At least one targeted engine middleware appears to violate the non-Quick synthesis contract.",
        "- The current source shape indicates grounded evidence may be returned directly before the normal synthesis pipeline completes.",
        "- This is now a downstream engine/runtime problem, not a router problem.",
        "",
        "Recommended next move:",
        "- Inspect the exact failed block(s) in 09_focused_engine_source_windows.txt.",
        "- If the early-return reading holds, Phase64 should patch the engine middleware so:",
        "  1. Quick keeps direct compact evidence.",
        "  2. Non-Quick gathers the same evidence but passes it into the normal/persona synthesis route.",
        "  3. No non-Quick branch labels itself no-GGUF while claiming synthesis_validated=True.",
    ])

verdict.extend([
    "",
    "Review:",
    "- 02_route_probe_matrix.txt",
    "- 04_engine_block_inventory.txt",
    "- 06_block_semantic_feature_matrix.txt",
    "- 08_nonquick_direct_bypass_risk_matrix.txt",
    "- 09_focused_engine_source_windows.txt",
    "- 10_targeted_assertions.txt",
])

(out / "11_console_verdict.txt").write_text(
    "\n".join(verdict) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict))
print()
print(f"PHASE63_OUT={out}")

if failures:
    raise SystemExit(1)
PY
