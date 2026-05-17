#!/usr/bin/env python3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from eli.kernel.engine import CognitiveEngine

prompt = "Who are you and what are you actually running on right now — model, context size, GPU layers, everything."

modes = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]

required_lines = [
    "- provider:",
    "- model_name:",
    "- model_path:",
    "- context_size:",
    "- gpu_layers:",
    "- batch_size:",
    "- cpu_threads:",
    "- loaded_in_this_process:",
    "- project_root:",
    "- user_db:",
    "- agent_db:",
    "- max_tokens:",
    "- temperature:",
    "- use_mmap:",
    "- use_mlock:",
]

bad_tokens = [
    "</think>",
    "<|im_",
    "|im_end|",
    ">>>>>>>",
    "<<<<<<<",
    "unable to answer",
    "no suitable response",
    "clarify your request",
    "don't have access to internal system details",
]

engine = CognitiveEngine()
failures = []

for mode in modes:
    print("\n" + "=" * 100)
    print("MODE:", mode)

    r = engine.process(prompt, reasoning_mode=mode)
    content = ""
    if isinstance(r, dict):
        content = r.get("content") or r.get("response") or str(r)
        print("ACTION:", r.get("action"))
        print("SOURCE:", r.get("evidence_source") or r.get("source"))
        print("SYNTHESIS_VALIDATED:", r.get("synthesis_validated"))
        print("REPAIR:", r.get("repair_reason"))
    else:
        content = str(r)
        print("ACTION:", None)
        print("SOURCE:", None)
        print("SYNTHESIS_VALIDATED:", None)
        print("REPAIR:", None)

    print("\n--- CONTENT HEAD ---")
    print(content[:1400])

    if not isinstance(r, dict):
        failures.append((mode, "not_dict"))
        continue

    if r.get("action") != "RUNTIME_STATUS":
        failures.append((mode, "wrong_action", r.get("action")))

    for token in bad_tokens:
        if token in content:
            failures.append((mode, "bad_token", token))

    for line in required_lines:
        if line not in content:
            failures.append((mode, "missing_required_line", line))

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- ") and stripped.endswith(":"):
            failures.append((mode, "blank_runtime_field", stripped))
        if stripped.endswith(": unknown"):
            failures.append((mode, "unknown_runtime_field", stripped))

print("\n" + "=" * 100)
print("STRICT CONTRACT RESULT")
if failures:
    print("FAIL")
    for f in failures:
        print(" -", f)
    raise SystemExit(1)

print("PASS")
