#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="eli/execution/executor_enhanced.py"
BACKUP="${TARGET}.bak_execute_action_alias_sync_${STAMP}"

cp "$TARGET" "$BACKUP"

cat >> "$TARGET" <<'PY'

# =============================================================================
# ELI_EXECUTOR_FINAL_EXECUTE_ACTION_ALIAS_SYNC_V1
# Final safety sync: execute_action must expose the same final contract surface as
# execute. Several historical wrappers reassigned execute without also rebinding
# execute_action, leaving execute_action pinned to an older wrapper.
# =============================================================================
try:
    _ELI_EXECUTOR_FINAL_ALIAS_SYNC_PREV_EXECUTE_ACTION = globals().get("execute_action")
    if callable(globals().get("execute")):
        execute_action = execute
        try:
            execute_action._eli_final_alias_sync_v1 = True
        except Exception:
            pass
        print("[EXECUTOR] final execute_action alias synced to execute", flush=True)
except Exception as _eli_executor_final_alias_sync_err:
    print(f"[EXECUTOR] final execute_action alias sync failed: {_eli_executor_final_alias_sync_err}", flush=True)
# =============================================================================
PY

echo "[PATCH] backup: $BACKUP"
echo
echo "=== compile ==="
python3 -m py_compile "$TARGET"

echo
echo "=== alias verification ==="
python3 - <<'PY'
import inspect
import eli.execution.executor_enhanced as ex

print("execute:", inspect.getsourcefile(ex.execute), ex.execute.__code__.co_firstlineno)
print("execute_action:", inspect.getsourcefile(ex.execute_action), ex.execute_action.__code__.co_firstlineno)
print("same_object:", ex.execute is ex.execute_action)
print("alias_marker:", getattr(ex.execute_action, "_eli_final_alias_sync_v1", False))

assert ex.execute is ex.execute_action, "execute_action is still not the final execute object"
assert getattr(ex.execute_action, "_eli_final_alias_sync_v1", False) is True, "alias sync marker missing"

for action, args in [
    ("EXPLAIN_MEMORY_RUNTIME", {"question": "What database files are your memories stored in, and what tables do they use?"}),
    ("MEMORY_STATUS", {"question": "How many memories and conversation turns are currently stored?"}),
    ("RUNTIME_STATUS", {}),
]:
    out = ex.execute_action(action, args)
    print()
    print("ACTION:", action)
    print("OK:", out.get("ok"))
    print("ACTION_OUT:", out.get("action"))
    print("EVIDENCE_SOURCE:", out.get("evidence_source"))
    text = str(out.get("content") or out.get("response") or "")
    print(text[:900])
PY

echo
echo "=== git diff ==="
git diff -- "$TARGET"
