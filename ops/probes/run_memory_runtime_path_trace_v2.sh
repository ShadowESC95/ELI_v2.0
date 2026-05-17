#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/memory_runtime_path_trace_${STAMP}"
mkdir -p "$OUT"

echo "OUT=$OUT"

{
  echo "=== git ==="
  git status -sb
  git log --oneline --decorate -10
  git tag --points-at HEAD

  echo
  echo "=== compile ==="
  python3 -m py_compile \
    eli/execution/executor_enhanced.py \
    eli/execution/router_enhanced.py \
    eli/kernel/engine.py \
    eli/cognition/agent_bus.py \
    eli/cognition/orchestrator.py \
    eli/memory/memory.py \
    eli/memory/__init__.py \
    eli/core/paths.py

  echo
  echo "=== canonical db path check ==="
  python3 - <<'PY'
from pathlib import Path
from eli.core.paths import user_db_path, agent_db_path, memory_db_path

print("user_db_path   =", user_db_path())
print("agent_db_path  =", agent_db_path())
print("memory_db_path =", memory_db_path())

assert str(user_db_path()).endswith("/artifacts/db/user.sqlite3")
assert str(agent_db_path()).endswith("/artifacts/db/agent.sqlite3")
assert str(memory_db_path()).endswith("/artifacts/db/user.sqlite3")
assert Path(user_db_path()).exists()
assert Path(agent_db_path()).exists()
assert not Path("artifacts/db/memory.sqlite3").exists()
assert not Path("artifacts/user.sqlite3").exists()
assert not Path("eli/artifacts/user.sqlite3").exists()

print("DB_PATHS_OK")
PY

  echo
  echo "=== focused route/executor grep ==="
  git grep -nE \
    'EXPLAIN_MEMORY_RUNTIME|MEMORY_STATUS|_explain_memory_runtime_report|_format_memory_runtime|_live_memory_audit|_format_memory_audit_for_chat|_memory_status_report|_get_db_schema_evidence|_runtime_memory_snapshot|_build_grounded_evidence_context|_route_grounded_runtime_intent|_query_is_grounded|MemoryAgent|memory_runtime|memory runtime|runtime memory|raw memory truth|PERSONAL_MEMORY_DEEP_EXPLAIN|PERSONAL_MEMORY_SUMMARY' \
    -- eli/execution/executor_enhanced.py eli/execution/router_enhanced.py eli/kernel/engine.py eli/cognition/agent_bus.py eli/cognition/orchestrator.py eli/cognition/grounded_status.py eli/runtime || true

  echo
  echo "=== exact source slices for likely memory-runtime path ==="
  python3 - <<'PY'
from pathlib import Path
import ast

targets = {
    "eli/execution/executor_enhanced.py": [
        "_explain_memory_runtime_report",
        "_format_memory_runtime",
        "_get_db_schema_evidence",
        "_memory_status_report",
        "_format_memory_status",
        "_live_memory_audit",
        "_format_memory_audit_for_chat",
        "_eli_sanitize_memory_runtime_output",
        "_eli_profile_scope_clean_memory_runtime_text",
    ],
    "eli/execution/router_enhanced.py": [
        "_route_grounded_runtime_intent",
        "_eli_pm_wants_raw_memory_truth",
        "_eli_pm_wants_personal_memory",
        "_eli_runtime_cognition_failure_guard",
    ],
    "eli/kernel/engine.py": [
        "_runtime_memory_snapshot",
        "_build_grounded_evidence_context",
        "_build_runtime_orchestrator_plan",
        "_build_dynamic_status_evidence",
        "_eli_pm_engine_wants_raw_memory_truth",
        "_eli_pm_engine_wants_personal_memory",
    ],
    "eli/cognition/agent_bus.py": [
        "_query_is_grounded",
        "_eli_memory_should_run",
        "MemoryAgent",
        "SystemAgent",
    ],
    "eli/cognition/orchestrator.py": [
        "MemoryAgent",
        "conversation_search",
    ],
}

for rel, names in targets.items():
    p = Path(rel)
    print(f"\n\n### FILE {rel}")
    if not p.exists():
        print("MISSING")
        continue

    src = p.read_text(encoding="utf-8", errors="ignore")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except Exception as e:
        print(f"AST_PARSE_FAILED: {type(e).__name__}: {e}")
        continue

    wanted = set(names)
    found = set()

    for node in ast.walk(tree):
        name = getattr(node, "name", None)
        if name in wanted:
            found.add(name)
            start = max(1, getattr(node, "lineno", 1) - 8)
            end = min(len(lines), getattr(node, "end_lineno", getattr(node, "lineno", 1)) + 8)
            print(f"\n--- {rel}:{start}-{end} :: {type(node).__name__} {name} ---")
            for i in range(start, end + 1):
                print(f"{i:05d}: {lines[i-1]}")

    missing = wanted - found
    if missing:
        print("\nMISSING_TARGETS:", ", ".join(sorted(missing)))
PY

  echo
  echo "=== action routing static map ==="
  python3 - <<'PY'
from pathlib import Path
import ast

for rel in [
    "eli/execution/router_enhanced.py",
    "eli/execution/executor_enhanced.py",
    "eli/kernel/engine.py",
    "eli/cognition/agent_bus.py",
]:
    p = Path(rel)
    src = p.read_text(encoding="utf-8", errors="ignore")
    lines = src.splitlines()
    print(f"\n### {rel}")

    for n, line in enumerate(lines, 1):
        if "EXPLAIN_MEMORY_RUNTIME" in line:
            lo = max(1, n - 8)
            hi = min(len(lines), n + 16)
            print(f"\n--- around line {n} ---")
            for i in range(lo, hi + 1):
                print(f"{i:05d}: {lines[i-1]}")
PY

  echo
  echo "=== direct module capability introspection ==="
  python3 - <<'PY'
import inspect
import importlib

mods = [
    "eli.execution.executor_enhanced",
    "eli.execution.router_enhanced",
    "eli.kernel.engine",
    "eli.cognition.agent_bus",
]

for modname in mods:
    print(f"\n### MODULE {modname}")
    try:
        m = importlib.import_module(modname)
    except Exception as e:
        print(f"IMPORT_FAILED: {type(e).__name__}: {e}")
        continue

    for name in sorted(dir(m)):
        low = name.lower()
        if any(k in low for k in ["memory", "runtime", "execute", "route", "status", "explain"]):
            obj = getattr(m, name, None)
            try:
                sig = str(inspect.signature(obj)) if callable(obj) else ""
            except Exception:
                sig = ""
            kind = type(obj).__name__
            print(f"{kind:24s} {name}{sig}")
PY

} 2>&1 | tee "$OUT/trace.log"

echo
echo "=== condensed files ==="
grep -nE \
  'EXPLAIN_MEMORY_RUNTIME|_explain_memory_runtime_report|_format_memory_runtime|_runtime_memory_snapshot|_build_grounded_evidence_context|_route_grounded_runtime_intent|MemoryAgent|DB_PATHS_OK|MISSING_TARGETS|IMPORT_FAILED|ERROR|Traceback' \
  "$OUT/trace.log" | tee "$OUT/condensed_hits.txt" || true

echo
echo "REPORT=$OUT"
