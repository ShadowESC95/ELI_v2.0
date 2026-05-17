#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="ops/reports/memory_runtime_strict_verify_${STAMP}.log"
mkdir -p ops/reports

{
  echo "=== git ==="
  git status -sb
  git log --oneline --decorate -6

  echo
  echo "=== markers ==="
  grep -nE \
    "ELI_MEMORY_RUNTIME_ROUTE_LOCK_V1|ELI_MEMORY_RUNTIME_STRICT_GROUNDED_NO_RAW_GGUF_V1|ELI_MEMORY_COUNT_INCLUDE_CONVERSATION_TURNS_V1|memory_runtime_strict_grounded_no_raw_gguf|memory_count_include_conversation_turns" \
    eli/execution/router_enhanced.py eli/kernel/engine.py

  echo
  echo "=== compile ==="
  python3 -m py_compile \
    eli/execution/router_enhanced.py \
    eli/execution/executor_enhanced.py \
    eli/kernel/engine.py \
    eli/core/paths.py \
    eli/memory/memory.py \
    eli/memory/__init__.py

  echo
  echo "=== router assertions ==="
  python3 - <<'PY'
from eli.execution.router_enhanced import route

tests = [
    "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    "What database files are your memories stored in, and what tables do they use?",
    "Run EXPLAIN_MEMORY_RUNTIME.",
]

bad = 0
for q in tests:
    r = route(q)
    print("\nQUESTION:", q)
    print("ROUTE:", r)
    if not isinstance(r, dict) or r.get("action") != "EXPLAIN_MEMORY_RUNTIME":
        bad += 1

print("\nROUTER_RESULT=", "FAIL" if bad else "PASS")
raise SystemExit(1 if bad else 0)
PY

  echo
  echo "=== executor direct assertions ==="
  python3 - <<'PY'
from eli.execution.executor_enhanced import execute

out = execute("EXPLAIN_MEMORY_RUNTIME", {"question": "Explain exactly how your memory system works internally — which files, which DB tables, which functions."})
txt = str(out.get("content") or out.get("response") or "")

print("ACTION:", out.get("action"))
print("EVIDENCE_SOURCE:", out.get("evidence_source"))
print("HEAD:")
print(txt[:2200])

required = [
    "artifacts/db/user.sqlite3",
    "artifacts/db/agent.sqlite3",
    "memories",
    "conversation_turns",
    "eli.memory.memory.Memory",
]
bad_fragments = [
    "Personal memory evidence report",
    "human brain",
    "not stored in traditional database files",
    "Could not open app",
    "specific tables used depend",
]

missing = [x for x in required if x not in txt]
bad = [x for x in bad_fragments if x.lower() in txt.lower()]

print("MISSING_REQUIRED:", missing)
print("BAD_FRAGMENTS:", bad)

raise SystemExit(1 if missing or bad else 0)
PY

  echo
  echo "=== engine strict surface assertions ==="
  python3 - <<'PY'
import re
from eli.kernel.engine import CognitiveEngine

questions = [
    "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    "What database files are your memories stored in, and what tables do they use?",
    "Run EXPLAIN_MEMORY_RUNTIME.",
    "How many memories and conversation turns are currently stored?",
]

modes = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]

bad_re = re.compile(
    r"Personal memory evidence report|"
    r"The human brain does not use databases|"
    r"not stored in traditional database files|"
    r"specific tables used depend|"
    r"Could not open app: explain_memory_runtime|"
    r"Control contract upgraded action -> EXPLAIN_COGNITION_RUNTIME",
    re.I,
)

required_re = re.compile(
    r"artifacts/db/user\.sqlite3|artifacts/db/agent\.sqlite3|"
    r"conversation_turns|memories|eli\.memory\.memory\.Memory|"
    r"memory_count_include_conversation_turns_v1",
    re.I,
)

engine = CognitiveEngine()
failures = []

for mode in modes:
    for q in questions:
        print("\n" + "=" * 100)
        print("MODE=", mode)
        print("QUESTION=", q)

        out = engine.process(q, reasoning_mode=mode)
        txt = out if isinstance(out, str) else str(out.get("content") or out.get("response") or out)

        print("TYPE:", type(out).__name__)
        if isinstance(out, dict):
            print("ACTION:", out.get("action"))
            print("SOURCE:", out.get("source"))
            print("EVIDENCE_SOURCE:", out.get("evidence_source"))
            rep = out.get("report")
            if isinstance(rep, dict):
                for k in ("synthesis_validated", "raw_gguf_candidates_skipped", "gguf_used_for_memory_runtime_synthesis", "repair_reason"):
                    if k in rep:
                        print(f"report.{k}:", rep.get(k))

        print("--- HEAD ---")
        print(txt[:1800])

        is_count_q = "conversation turns" in q.lower()
        has_required = bool(required_re.search(txt))
        has_bad = bool(bad_re.search(txt))

        if has_bad:
            failures.append((mode, q, "bad contaminated surface"))
        if not has_required:
            failures.append((mode, q, "missing required grounded terms"))

try:
    engine.shutdown()
except Exception:
    pass

print("\n" + "=" * 100)
print("FAILURES:", failures)
print("MEMORY_RUNTIME_STRICT_VERIFY_RESULT=", "FAIL" if failures else "PASS")
raise SystemExit(1 if failures else 0)
PY

} 2>&1 | tee "$REPORT"

echo
echo "REPORT=$REPORT"
