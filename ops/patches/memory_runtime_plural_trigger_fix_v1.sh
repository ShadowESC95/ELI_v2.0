#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import time

targets = [
    Path("eli/execution/router_enhanced.py"),
    Path("eli/kernel/engine.py"),
]

needle = 'if "memory" in low and _re.search('
replacement = 'if _re.search(r"\\bmemor(?:y|ies)\\b", low) and _re.search('

changed = []

for p in targets:
    src = p.read_text(encoding="utf-8")
    if replacement in src:
        print(f"[PATCH] already fixed: {p}")
        continue

    if needle not in src:
        raise SystemExit(f"[FAIL] needle not found in {p}: {needle}")

    backup = p.with_suffix(p.suffix + f".bak_memory_runtime_plural_trigger_{time.strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(src, encoding="utf-8")

    src2 = src.replace(needle, replacement)
    p.write_text(src2, encoding="utf-8")

    changed.append(str(p))
    print(f"[PATCH] fixed plural memory/memories trigger in {p}")
    print(f"[PATCH] backup: {backup}")

print("[PATCH] changed:", changed)
PY

python3 -m py_compile \
  eli/execution/router_enhanced.py \
  eli/kernel/engine.py \
  eli/execution/executor_enhanced.py

echo
echo "=== focused diff ==="
git diff -- eli/execution/router_enhanced.py eli/kernel/engine.py | sed -n '1,220p'
