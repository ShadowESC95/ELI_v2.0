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

engine = CognitiveEngine()

for mode in modes:
    print("\n" + "=" * 100)
    print("MODE:", mode)

    result = engine.process(prompt, reasoning_mode=mode)

    if isinstance(result, dict):
        content = result.get("content") or result.get("response") or str(result)
        print("ACTION:", result.get("action"))
        print("SOURCE:", result.get("evidence_source") or result.get("source"))
        print("SYNTHESIS_VALIDATED:", result.get("synthesis_validated"))
        print("REPAIR:", result.get("repair_reason"))
    else:
        content = str(result)
        print("ACTION:", None)
        print("SOURCE:", None)
        print("SYNTHESIS_VALIDATED:", None)
        print("REPAIR:", None)

    print("\n--- CONTENT HEAD ---")
    print(content[:1600])
