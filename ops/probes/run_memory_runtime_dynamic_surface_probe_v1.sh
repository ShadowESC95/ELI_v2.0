#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="ops/reports/memory_runtime_dynamic_surface_${STAMP}.log"
mkdir -p ops/reports

{
  echo "=== git ==="
  git status -sb
  git log --oneline --decorate -5

  echo
  echo "=== dynamic memory-runtime questions ==="

  python3 - <<'PY'
import json
import re
import traceback

QUESTIONS = [
    "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
    "What database files are your memories stored in, and what tables do they use?",
    "Run EXPLAIN_MEMORY_RUNTIME.",
    "How many memories and conversation turns are currently stored?",
]

MODES = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]

BAD_RE = re.compile(
    r"Tree of Thoughts Memory Model|mental model of past interactions|"
    r"does not rely on specific files|complex network of interconnected thoughts|"
    r"cannot confirm.*without further evidence|not readily available|always here to help|"
    r"I don't have personal memories|I do not have personal memories|"
    r"generic memory system|various types of information|"
    r"what specifically|could you clarify|how can I assist",
    re.I,
)

GOOD_RE = re.compile(
    r"artifacts/db/user\.sqlite3|artifacts/db/agent\.sqlite3|"
    r"memories|conversation_turns|recall_log|runtime_events|"
    r"_explain_memory_runtime_report|_format_memory_runtime|"
    r"user_db_path|agent_db_path|memory_db_path|"
    r"eli\.memory|eli/execution/executor_enhanced\.py",
    re.I,
)

def visible_text(obj):
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for key in ("response", "content", "text", "message", "answer"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return json.dumps(obj, ensure_ascii=False, default=str, indent=2)
    return str(obj)

try:
    from eli.kernel.engine import CognitiveEngine
except Exception as e:
    print("IMPORT_FAILED CognitiveEngine:", type(e).__name__, e)
    traceback.print_exc()
    raise SystemExit(2)

try:
    engine = CognitiveEngine()
except TypeError:
    engine = CognitiveEngine({})
except Exception as e:
    print("ENGINE_INIT_FAILED:", type(e).__name__, e)
    traceback.print_exc()
    raise SystemExit(3)

failures = 0

for mode in MODES:
    for q in QUESTIONS:
        print("\n" + "=" * 100)
        print(f"MODE={mode}")
        print(f"QUESTION={q}")

        try:
            if hasattr(engine, "process"):
                try:
                    result = engine.process(q, reasoning_mode=mode)
                except TypeError:
                    result = engine.process(q)
            elif hasattr(engine, "chat"):
                try:
                    result = engine.chat(q, reasoning_mode=mode)
                except TypeError:
                    result = engine.chat(q)
            else:
                print("NO_PROCESS_OR_CHAT_METHOD")
                failures += 1
                continue
        except Exception as e:
            print("CALL_FAILED:", type(e).__name__, e)
            traceback.print_exc()
            failures += 1
            continue

        text = visible_text(result)
        print("--- RESULT TYPE ---")
        print(type(result).__name__)

        if isinstance(result, dict):
            print("--- RESULT KEYS ---")
            print(sorted(result.keys()))
            print("--- ACTION/SOURCE/META ---")
            for key in ("action", "source", "evidence_source", "grounded", "evidence_used"):
                if key in result:
                    print(f"{key}: {result.get(key)}")
            rep = result.get("report")
            if isinstance(rep, dict):
                for key in ("evidence_source", "synthesis_validated", "repair_reason", "response_surface", "gguf_used_for_runtime_status_synthesis", "raw_gguf_candidates_skipped"):
                    if key in rep:
                        print(f"report.{key}: {rep.get(key)}")

        print("--- VISIBLE HEAD ---")
        print(text[:2500])

        bad = bool(BAD_RE.search(text))
        good = bool(GOOD_RE.search(text))
        print("--- SCAN ---")
        print("BAD_GENERIC_MEMORY_SURFACE=", bad)
        print("GROUNDING_TERMS_PRESENT=", good)

        if bad:
            failures += 1
        if q.lower().startswith("explain exactly") and not good:
            failures += 1

try:
    if hasattr(engine, "shutdown"):
        engine.shutdown()
except Exception:
    pass

print("\n" + "=" * 100)
print("DYNAMIC_MEMORY_RUNTIME_RESULT=", "FAIL" if failures else "PASS")
raise SystemExit(1 if failures else 0)
PY

} 2>&1 | tee "$REPORT"

echo
echo "=== scan report ==="
grep -nE \
  'MODE=|QUESTION=|ACTION/SOURCE|action:|source:|evidence_source:|BAD_GENERIC_MEMORY_SURFACE|GROUNDING_TERMS_PRESENT|DYNAMIC_MEMORY_RUNTIME_RESULT|IMPORT_FAILED|ENGINE_INIT_FAILED|CALL_FAILED|Traceback' \
  "$REPORT" || true

echo
echo "REPORT=$REPORT"
