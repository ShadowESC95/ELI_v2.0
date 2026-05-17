#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$(pwd)}"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/phase19b_grounded_followup_meta_commit_v2_${STAMP}"
mkdir -p "$OUT/backups/eli/kernel"

cp -a eli/kernel/engine.py "$OUT/backups/eli/kernel/engine.py"

python3 - <<'PY'
from __future__ import annotations

from pathlib import Path
import re

path = Path("eli/kernel/engine.py")
text = path.read_text(encoding="utf-8")

begin = "# === ELI_PHASE19_GROUNDED_FOLLOWUP_REBIND_V1 ==="
end = "# === END ELI_PHASE19_GROUNDED_FOLLOWUP_REBIND_V1 ==="
marker = "# ELI_PHASE19B_COMMIT_REBOUND_META_V2"

if marker in text:
    print("Phase 19b v2 marker already present; no edit needed.")
    raise SystemExit(0)

if begin not in text or end not in text:
    raise SystemExit("Phase 19 helper block not found; refusing blind edit.")

start_i = text.index(begin)
end_i = text.index(end, start_i) + len(end)
block = text[start_i:end_i]

if 'current["meta"] = meta' in block:
    print('current["meta"] = meta already present in Phase 19 helper; no edit needed.')
    raise SystemExit(0)

pattern = re.compile(
    r'(?P<meta>\n[ \t]*meta\.update\(\{.*?\n[ \t]*\}\)\n)'
    r'(?P<action>[ \t]*current\["action"\]\s*=\s*prior_action\n)',
    re.DOTALL,
)

match = pattern.search(block)
if not match:
    raise SystemExit("Phase 19 meta/action insertion point not found; refusing blind edit.")

action_indent = re.match(r"[ \t]*", match.group("action")).group(0)
insert = (
    match.group("meta")
    + f"{action_indent}{marker}\n"
    + f"{action_indent}# Persist the rebound metadata into the routed intent packet.\n"
    + f'{action_indent}current["meta"] = meta\n'
    + match.group("action")
)

new_block = block[:match.start()] + insert + block[match.end():]
new_text = text[:start_i] + new_block + text[end_i:]
path.write_text(new_text, encoding="utf-8")
print("Phase 19b v2 metadata commit inserted.")
PY

{
  echo "=== Phase 19b v2 marker scan ==="
  grep -nE 'ELI_PHASE19B_COMMIT_REBOUND_META_V2|current\\["meta"\\] = meta' eli/kernel/engine.py || true
} > "$OUT/01_patch_markers.txt" 2>&1

python3 -m py_compile \
  eli/kernel/engine.py \
  tests/test_phase19_grounded_followup_truth_lock.py \
  > "$OUT/02_py_compile.txt" 2>&1

python3 -m pytest -q \
  tests/test_phase19_grounded_followup_truth_lock.py \
  tests/test_route_contracts.py \
  > "$OUT/03_pytest_phase19b_v2_core.txt" 2>&1 || true

python3 - <<'PY' > "$OUT/04_phase19b_v2_static_probe.txt" 2>&1
from eli.kernel.engine import _eli_phase19_rebind_grounded_followup

class Engine:
    _last_request_meta = {
        "request_id": "req-000002",
        "route_action": "RUNTIME_AUDIT",
        "result_action": "RUNTIME_AUDIT",
        "grounded": True,
        "evidence_used": True,
    }

intent = {
    "action": "CHAT",
    "args": {"message": "what are the exact lines?"},
    "confidence": 0.85,
    "meta": {"matched_by": "chat.long_question_guard"},
}

print(_eli_phase19_rebind_grounded_followup(
    Engine(),
    "what are the exact lines of the duplicates, can you fix it?",
    intent,
))
PY

{
  echo "# Phase 19b v2 Grounded Follow-up Metadata Commit"
  echo
  echo "Date: $(date -Is)"
  echo "Root: $ROOT"
  echo
  echo "## Purpose"
  echo "- Persist Phase 19 rebound metadata into intent['meta']."
  echo "- Replace the brittle Phase 19b exact-anchor patch with a bounded regex edit inside the Phase 19 helper block only."
  echo "- Resolve the two Phase 19 regression failures:"
  echo "  - missing grounded_followup"
  echo "  - missing grounded_followup_kind"
  echo
  echo "## Outputs"
  echo "- 01_patch_markers.txt"
  echo "- 02_py_compile.txt"
  echo "- 03_pytest_phase19b_v2_core.txt"
  echo "- 04_phase19b_v2_static_probe.txt"
} > "$OUT/SUMMARY.md"

echo
cat "$OUT/SUMMARY.md"
echo
echo "Report directory: $OUT"
