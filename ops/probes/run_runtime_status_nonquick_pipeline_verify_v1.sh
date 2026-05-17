#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/runtime_status_nonquick_pipeline_verify_${STAMP}"
mkdir -p "$OUT"

python3 - <<'PY' | tee "$OUT/run.log"
import json
from pathlib import Path

FAIL = []

question = "Who are you and what are you actually running on right now — model, context size, GPU layers, everything."

print("=== import engine ===")
from eli.kernel.engine import CognitiveEngine

engine = CognitiveEngine()

modes = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]

for mode in modes:
    print("\n" + "=" * 100)
    print("MODE=", mode)
    out = engine.process(question, reasoning_mode=mode)
    print("TYPE:", type(out).__name__)

    if isinstance(out, dict):
        action = out.get("action")
        source = out.get("source")
        evidence_source = out.get("evidence_source")
        report = out.get("report") if isinstance(out.get("report"), dict) else {}
        text = str(out.get("content") or out.get("response") or "")
    else:
        action = None
        source = None
        evidence_source = None
        report = {}
        text = str(out or "")

    print("ACTION:", action)
    print("SOURCE:", source)
    print("EVIDENCE_SOURCE:", evidence_source)
    print("REPORT:", json.dumps(report, indent=2, default=str)[:2000])
    print("--- TEXT HEAD ---")
    print(text[:1800])

    low = text.lower()

    if mode == "quick":
        # Quick is allowed to be direct/canonical.
        if action != "RUNTIME_STATUS":
            FAIL.append(f"{mode}: expected RUNTIME_STATUS")
        continue

    if action != "RUNTIME_STATUS":
        FAIL.append(f"{mode}: expected RUNTIME_STATUS action")

    if source != "runtime_status_nonquick_full_pipeline_synthesized_v1":
        FAIL.append(f"{mode}: wrong source; got {source}")

    if report.get("synthesis_validated") is not True:
        FAIL.append(f"{mode}: synthesis_validated not True")

    if report.get("direct_telemetry_returned") is not False:
        FAIL.append(f"{mode}: direct_telemetry_returned not False")

    forbidden = [
        "raw gguf candidate",
        "raw_gguf_candidates_skipped",
        "response_surface:",
        "repair_reason:",
        "canonical live grounded telemetry",
        "synthesis_validated",
        "evidence_source:",
        "{'ok':",
        '"ok":',
    ]
    for frag in forbidden:
        if frag in low:
            FAIL.append(f"{mode}: leaked forbidden fragment: {frag}")

    required = ["model", "context", "gpu"]
    for frag in required:
        if frag not in low:
            FAIL.append(f"{mode}: missing expected synthesized runtime fact: {frag}")

print("\n" + "=" * 100)
print("FAILURES:", FAIL)
if FAIL:
    Path("ops/reports").mkdir(exist_ok=True)
    raise SystemExit("RUNTIME_STATUS_NONQUICK_PIPELINE_VERIFY_RESULT=FAIL")

print("RUNTIME_STATUS_NONQUICK_PIPELINE_VERIFY_RESULT=PASS")
PY
