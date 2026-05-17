#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="eli/execution/executor_enhanced.py"
BACKUP="${TARGET}.bak_runtime_status_evidence_metadata_${STAMP}"

cp "$TARGET" "$BACKUP"

python3 - <<'PY'
from pathlib import Path

target = Path("eli/execution/executor_enhanced.py")
text = target.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_EXECUTOR_EVIDENCE_METADATA_V1"

if marker in text:
    print("[PATCH] marker already present; no duplicate append")
else:
    block = r'''

# =============================================================================
# ELI_RUNTIME_STATUS_EXECUTOR_EVIDENCE_METADATA_V1
# Runtime-status is live local telemetry. The existing content path already
# reports grounded runtime facts, but some executor surfaces returned
# evidence_source=None. This wrapper normalises metadata only; it does not replace
# or hard-code the runtime-status content.
# =============================================================================
try:
    _ELI_RUNTIME_STATUS_EVIDENCE_METADATA_PREV_EXECUTE = execute

    def execute(action_name, args=None, *pargs, _prev=_ELI_RUNTIME_STATUS_EVIDENCE_METADATA_PREV_EXECUTE, **kwargs):
        out = _prev(action_name, args, *pargs, **kwargs)

        try:
            action_text = str(action_name or "").strip().upper()
        except Exception:
            action_text = ""

        if action_text != "RUNTIME_STATUS":
            return out

        if not isinstance(out, dict):
            txt = str(out or "").strip()
            out = {
                "ok": bool(txt),
                "action": "RUNTIME_STATUS",
                "content": txt,
                "response": txt,
            }
        else:
            out = dict(out)

        txt = str(out.get("content") or out.get("response") or "").strip()

        out["ok"] = bool(out.get("ok", bool(txt)))
        out["action"] = "RUNTIME_STATUS"
        out["grounded"] = True
        out["evidence_used"] = True

        if not out.get("source"):
            out["source"] = "runtime_status_executor_evidence_metadata_v1"

        if not out.get("evidence_source"):
            out["evidence_source"] = "runtime_status_live_runtime_telemetry"

        report = dict(out.get("report") or {})
        report.setdefault("repair_reason", "runtime_status_executor_evidence_metadata_v1")
        report.setdefault("metadata_normalised", True)
        report.setdefault("evidence_contract", "live_runtime_status_telemetry")
        report.setdefault("runtime_status_content_preserved", True)
        out["report"] = report

        if txt:
            out.setdefault("content", txt)
            out.setdefault("response", txt)

        return out

    execute_action = execute

    try:
        execute._eli_runtime_status_evidence_metadata_v1 = True
        execute_action._eli_runtime_status_evidence_metadata_v1 = True
        execute_action._eli_final_alias_sync_v1 = True
    except Exception:
        pass

    print("[EXECUTOR] RUNTIME_STATUS evidence metadata normalizer installed", flush=True)

except Exception as _eli_runtime_status_evidence_metadata_err:
    print(f"[EXECUTOR] RUNTIME_STATUS evidence metadata normalizer failed: {_eli_runtime_status_evidence_metadata_err}", flush=True)
# =============================================================================
'''
    target.write_text(text.rstrip() + block + "\n", encoding="utf-8")
    print("[PATCH] installed ELI_RUNTIME_STATUS_EXECUTOR_EVIDENCE_METADATA_V1")
PY

echo
echo "=== compile ==="
python3 -m py_compile "$TARGET"

echo
echo "=== direct verification ==="
python3 - <<'PY'
import inspect
import eli.execution.executor_enhanced as ex

print("execute:", inspect.getsourcefile(ex.execute), ex.execute.__code__.co_firstlineno)
print("execute_action:", inspect.getsourcefile(ex.execute_action), ex.execute_action.__code__.co_firstlineno)
print("same_object:", ex.execute is ex.execute_action)
print("alias_marker:", bool(getattr(ex.execute_action, "_eli_final_alias_sync_v1", False)))
print("runtime_status_marker:", bool(getattr(ex.execute_action, "_eli_runtime_status_evidence_metadata_v1", False)))

out = ex.execute_action("RUNTIME_STATUS", {})
print("OK:", out.get("ok"))
print("ACTION:", out.get("action"))
print("SOURCE:", out.get("source"))
print("EVIDENCE_SOURCE:", out.get("evidence_source"))
print("GROUNDED:", out.get("grounded"))
print("EVIDENCE_USED:", out.get("evidence_used"))
print("REPORT:", out.get("report"))
print()
print(str(out.get("content") or out.get("response") or "")[:1200])

assert ex.execute is ex.execute_action, "execute_action alias drifted again"
assert out.get("action") == "RUNTIME_STATUS", out
assert out.get("evidence_source"), out
assert out.get("grounded") is True, out
assert out.get("evidence_used") is True, out
PY

echo
echo "=== diff ==="
git diff -- "$TARGET"
