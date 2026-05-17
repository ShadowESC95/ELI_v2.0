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

replacements = {
    "runtime_status_nonquick_canonical_contract":
        "runtime_status_nonquick_strict_grounded_no_raw_gguf_v3",

    "non-Quick synthesis attempted first; blank repair fields completed from live evidence":
        "non-Quick canonical grounded runtime-status contract; raw GGUF candidate generation skipped for telemetry hygiene",

    "Non-Quick mode attempted normal synthesis first; repair only filled missing grounded fields.":
        "Non-Quick runtime-status bypassed raw GGUF candidate generation and returned canonical live telemetry.",

    "missing_runtime_status_fields":
        "runtime_status_nonquick_strict_grounded_no_raw_gguf",
}

changed = False
for old, new in replacements.items():
    if old in src:
        src = src.replace(old, new)
        changed = True

if not changed:
    raise SystemExit("[PATCH] no matching runtime-status wording found; inspect runtime_status.py manually")

backup = p.with_suffix(f".py.bak_no_raw_wording_{time.strftime('%Y%m%d_%H%M%S')}")
backup.write_text(orig, encoding="utf-8")
p.write_text(src, encoding="utf-8")

print("[PATCH] runtime-status contract wording updated for no-raw-GGUF path")
print(f"[PATCH] backup: {backup}")
PY

python3 -m py_compile eli/contracts/runtime_status.py
grep -nE "runtime_status_nonquick|raw GGUF|normal synthesis|missing_runtime_status_fields" eli/contracts/runtime_status.py || true
