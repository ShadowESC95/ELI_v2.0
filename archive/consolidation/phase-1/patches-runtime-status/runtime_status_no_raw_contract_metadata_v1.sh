#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import time

p = Path("eli/contracts/runtime_status.py")
src = p.read_text(encoding="utf-8")
orig = src

must = {
    "* Non-Quick modes must attempt normal synthesis first.":
        "* Non-Quick runtime-status requests return canonical live telemetry without raw GGUF candidate generation.",

    '"synthesis_validated": mode != "quick" and repair_reason in {"synthesis_valid"},':
        '"synthesis_validated": mode != "quick" and repair_reason in {"synthesis_valid", "runtime_status_nonquick_strict_grounded_no_raw_gguf"},',
}

optional = {
    "Runtime status, completed from live grounded evidence after synthesis/repair validation.":
        "Runtime status, completed from canonical live grounded telemetry.",
}

missing = [old for old in must if old not in src]
if missing:
    raise SystemExit("[PATCH] missing required text:\n" + "\n".join(missing))

for old, new in must.items():
    src = src.replace(old, new)

for old, new in optional.items():
    if old in src:
        src = src.replace(old, new)

backup = p.with_suffix(f".py.bak_no_raw_contract_metadata_{time.strftime('%Y%m%d_%H%M%S')}")
backup.write_text(orig, encoding="utf-8")
p.write_text(src, encoding="utf-8")

print("[PATCH] runtime-status no-raw contract metadata corrected")
print(f"[PATCH] backup: {backup}")
PY

python3 -m py_compile eli/contracts/runtime_status.py

grep -nE "Non-Quick|synthesis_validated|canonical live grounded telemetry|raw GGUF" eli/contracts/runtime_status.py | sed -n '1,120p'
