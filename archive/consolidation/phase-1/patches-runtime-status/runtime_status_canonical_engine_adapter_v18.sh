#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 - <<'PY'
from pathlib import Path
import time

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

start_marker = "_ELI_RUNTIME_STATUS_REPAIR_V10_PREV_PROCESS = CognitiveEngine.process"
end_marker = 'print("[ENGINE] runtime-status all-surfaces generation block v17 installed")'

if start_marker not in src:
    raise SystemExit(f"START MARKER NOT FOUND: {start_marker}")

if end_marker not in src:
    raise SystemExit(f"END MARKER NOT FOUND: {end_marker}")

start = src.index(start_marker)

# Move start back to beginning of the logical V10 block if there is a nearby blank/comment boundary.
prefix = src[:start]
candidate = prefix.rfind("\n# ", 0, start)
if candidate != -1 and start - candidate < 1000:
    start = candidate + 1

end = src.index(end_marker) + len(end_marker)

old = src[start:end]

replacement = r'''
# ELI_RUNTIME_STATUS_CANONICAL_CONTRACT_V18
# Canonical runtime-status adapter.
#
# This replaces the stacked V10-V17 runtime-status wrappers with a single
# contract-backed surface:
# - Quick: direct structured live evidence is allowed.
# - Non-Quick: the normal synthesis path runs first.
# - If synthesis is blank, evasive, poisoned, fabricated, or incomplete,
#   the visible answer is repaired from live evidence.
try:
    from eli.contracts.runtime_status import (
        RUNTIME_STATUS_ACTION as _ELI_RUNTIME_STATUS_ACTION_V18,
        complete_or_repair as _eli_runtime_status_v18_complete_or_repair,
        is_runtime_status_question as _eli_runtime_status_v18_is_question,
        quick_result as _eli_runtime_status_v18_quick_result,
    )

    _ELI_RUNTIME_STATUS_CANONICAL_CONTRACT_V18_PREV_PROCESS = CognitiveEngine.process

    def _eli_runtime_status_v18_mode_from_call(_args, _kwargs):
        _valid = {
            "quick",
            "chain_of_thought",
            "self_consistency",
            "tree_of_thoughts",
            "constitutional_ai",
        }

        for _key in ("reasoning_mode", "mode", "requested_mode"):
            _value = _kwargs.get(_key)
            if isinstance(_value, str) and _value in _valid:
                return _value

        if _args:
            _value = _args[0]
            if isinstance(_value, str) and _value in _valid:
                return _value

        return "quick"

    def _eli_runtime_status_canonical_contract_v18_process(self, message=None, *args, **kwargs):
        _mode = _eli_runtime_status_v18_mode_from_call(args, kwargs)
        _is_runtime_status = _eli_runtime_status_v18_is_question(message)

        # Quick is the only mode allowed to return direct structured evidence.
        if _is_runtime_status and _mode == "quick":
            return _eli_runtime_status_v18_quick_result(mode=_mode)

        _result = _ELI_RUNTIME_STATUS_CANONICAL_CONTRACT_V18_PREV_PROCESS(
            self, message, *args, **kwargs
        )

        _action = _result.get("action") if isinstance(_result, dict) else None

        # Non-Quick must synthesize first. After synthesis, validate the visible
        # content and repair only if needed.
        if _is_runtime_status or _action == _ELI_RUNTIME_STATUS_ACTION_V18:
            if not isinstance(_result, dict):
                _result = {"ok": False, "action": _ELI_RUNTIME_STATUS_ACTION_V18, "content": str(_result)}
            return _eli_runtime_status_v18_complete_or_repair(
                result=_result,
                mode=_mode,
            )

        return _result

    CognitiveEngine.process = _eli_runtime_status_canonical_contract_v18_process
    print("[ENGINE] runtime-status canonical contract v18 installed", flush=True)

except Exception as _eli_runtime_status_v18_error:
    print(
        f"[ENGINE][WARN] runtime-status canonical contract v18 failed to install: {_eli_runtime_status_v18_error}",
        flush=True,
    )
'''.strip()

stamp = time.strftime("%Y%m%d_%H%M%S")
backup = Path(f"ops/reports/engine_before_runtime_status_canonical_v18_{stamp}.py.bak")
backup.write_text(src, encoding="utf-8")

new_src = src[:start] + replacement + src[end:]

p.write_text(new_src, encoding="utf-8")

print("Replaced runtime-status wrapper block:")
print(f"- start byte: {start}")
print(f"- end byte:   {end}")
print(f"- removed chars: {len(old)}")
print(f"- backup: {backup}")
PY

python3 -m py_compile eli/contracts/runtime_status.py eli/kernel/engine.py

echo
echo "=== Remaining runtime-status process assignments ==="
python3 - <<'PY'
from pathlib import Path

src = Path("eli/kernel/engine.py").read_text(encoding="utf-8")
for i, line in enumerate(src.splitlines(), 1):
    if "CognitiveEngine.process =" in line:
        print(f"{i}: {line.strip()}")
PY
