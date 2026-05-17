#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase16_identity_matcher_dataset_portability_repair_${STAMP}"
BACKUP="$OUT/backups"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 16 — Identity Matcher + Dataset Path Portability Repair"
echo "ROOT : $ROOT"
echo "OUT  : $OUT"
echo "TIME : $(date -Is)"
echo "======================================================================"
echo

if [ ! -d "$ROOT/eli" ] || [ ! -f "$ROOT/bin/elix" ]; then
  echo "FATAL: not an ELI project root:"
  echo "  $ROOT"
  false
fi

{
  echo "# Phase 16 — Identity Matcher + Dataset Path Portability Repair"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- PYTHONPATH: \`${PYTHONPATH-<unset>}\`"
  echo
} > "$OUT/SUMMARY.md"

echo "=== 0. Backups ==="
for rel in \
  "eli/runtime/control_contracts.py" \
  "eli/learning/dataset_builder.py" \
  "eli/learning/dataset_filters.py"
do
  SRC="$ROOT/$rel"
  DST="$BACKUP/$rel"
  if [ -f "$SRC" ]; then
    mkdir -p "$(dirname "$DST")"
    cp -a "$SRC" "$DST"
    echo "BACKUP $rel"
  else
    echo "MISSING $rel"
  fi
done
echo

echo "=== 1. Patch control_contracts.py identity matcher to stop overmatching 'what are you talking about' ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/runtime/control_contracts.py"

src = path.read_text(encoding="utf-8")

marker = "# PHASE16_IDENTITY_WHAT_ARE_YOU_BOUNDARY_FIX"

if marker in src:
    print("SKIP: Phase 16 identity matcher patch already present.")
    (out / "01_control_contracts_identity_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

old = '        r"|what are you(?:\\\\s|$)"\n'

new = (
    '        # PHASE16_IDENTITY_WHAT_ARE_YOU_BOUNDARY_FIX\n'
    '        # Match identity questions such as "what are you?" or\n'
    '        # "what are you exactly?", but do not match ordinary\n'
    '        # conversational forms like "what are you talking about?"\n'
    '        r"|what are you(?=\\\\s*(?:[?!.,]*\\\\s*$|(?:exactly|really|actually)[?!.,]*\\\\s*$))"\n'
)

if old not in src:
    raise SystemExit(
        "PATCH FAILED: could not find the old over-broad "
        "`what are you(?:\\s|$)` identity alternative."
    )

patched = src.replace(old, new, 1)
path.write_text(patched, encoding="utf-8")

(out / "01_control_contracts_identity_patch.txt").write_text(
    "PATCHED control_contracts.py: identity matcher no longer catches 'what are you talking about?'.\n",
    encoding="utf-8",
)

print("PATCHED control_contracts.py")
PY
echo

echo "=== 2. Patch dataset_builder.py to redact dynamic PROJECT_ROOT instead of /home/.../Desktop/ELI_MKXI ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/learning/dataset_builder.py"

src = path.read_text(encoding="utf-8")

marker = "# PHASE16_DYNAMIC_PROJECT_ROOT_REDACTION"

if marker in src:
    print("SKIP: Phase 16 dataset_builder portability patch already present.")
    (out / "02_dataset_builder_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

old = '''HOME_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+")
PROJECT_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+/Desktop/ELI_MKXI")
'''

new = '''# PHASE16_DYNAMIC_PROJECT_ROOT_REDACTION
# Redact the actual local project root dynamically. Do not assume Linux,
# a specific username, a Desktop checkout, or the historical ELI_MKXI folder name.
PROJECT_PATH_RE = re.compile(re.escape(str(PROJECT_ROOT)))

# Redact common user-home prefixes across Linux/macOS/Windows-shaped paths.
# This is sanitisation logic, not an operational filesystem default.
HOME_PATH_RE = re.compile(
    r"(?:"
    r"/home/[A-Za-z0-9._-]+"
    r"|/Users/[A-Za-z0-9._-]+"
    r"|[A-Za-z]:\\\\\\\\Users\\\\\\\\[^\\\\\\\\\\s]+"
    r")"
)
'''

if old not in src:
    raise SystemExit(
        "PATCH FAILED: could not find the old HOME_PATH_RE / PROJECT_PATH_RE block."
    )

patched = src.replace(old, new, 1)
path.write_text(patched, encoding="utf-8")

(out / "02_dataset_builder_patch.txt").write_text(
    "PATCHED dataset_builder.py: project-path redaction now uses dynamic PROJECT_ROOT and cross-platform home sanitisation.\n",
    encoding="utf-8",
)

print("PATCHED dataset_builder.py")
PY
echo

echo "=== 3. Patch dataset_filters.py home redaction to include Windows-shaped user paths ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/learning/dataset_filters.py"

src = path.read_text(encoding="utf-8")

marker = "# PHASE16_WINDOWS_HOME_REDACTION"

if marker in src:
    print("SKIP: Phase 16 dataset_filters Windows-path redaction already present.")
    (out / "03_dataset_filters_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

old = '''    s = re.sub(r"/home/[A-Za-z0-9._-]+", "<HOME>", s)
    s = re.sub(r"/Users/[A-Za-z0-9._-]+", "<HOME>", s)
'''

new = '''    s = re.sub(r"/home/[A-Za-z0-9._-]+", "<HOME>", s)
    s = re.sub(r"/Users/[A-Za-z0-9._-]+", "<HOME>", s)
    # PHASE16_WINDOWS_HOME_REDACTION
    s = re.sub(r"[A-Za-z]:\\\\\\\\Users\\\\\\\\[^\\\\\\\\\\s]+", "<HOME>", s)
'''

if old not in src:
    raise SystemExit(
        "PATCH FAILED: could not find dataset_filters normalise_text home-redaction block."
    )

patched = src.replace(old, new, 1)
path.write_text(patched, encoding="utf-8")

(out / "03_dataset_filters_patch.txt").write_text(
    "PATCHED dataset_filters.py: normalise_text now redacts Windows-shaped user home prefixes too.\n",
    encoding="utf-8",
)

print("PATCHED dataset_filters.py")
PY
echo

echo "=== 4. Compile verification ==="
{
  python3 -m py_compile \
    "$ROOT/eli/runtime/control_contracts.py" \
    "$ROOT/eli/learning/dataset_builder.py" \
    "$ROOT/eli/learning/dataset_filters.py"

  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"

  echo "PY_COMPILE_OK"
  echo "COMPILEALL_OK"
} | tee "$OUT/04_compile.txt"
echo

echo "=== 5. Targeted identity routing probe ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

from eli.runtime.control_contracts import route_control_text

cases = [
    "What are you talking about? is that a note to yourself, or me?",
    "what are you?",
    "what are you exactly?",
    "what are you really?",
    "tell me about yourself",
    "what are you running on right now — model, context, GPU?",
    "what is wrong with your last response?",
]

lines = []
for case in cases:
    action = route_control_text(case, current_action=None)
    lines.append(f"CONTROL case={case!r} action={action!r}")

text = "\n".join(lines) + "\n"
(out / "05_identity_routing_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 6. Dataset redaction portability probe ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

from eli.learning.dataset_builder import redact_text, PROJECT_ROOT
from eli.learning.dataset_filters import normalise_text

samples = [
    f"{PROJECT_ROOT}/artifacts/db/user.sqlite3",
    "/home/alice/Desktop/SomeOtherCheckout/data.txt",
    "/Users/charlie/Projects/ELI/data.txt",
    r"C:\\Users\\Dana\\Documents\\ELI\\notes.txt",
]

lines = []
for sample in samples:
    lines.append(f"BUILDER_IN  {sample!r}")
    lines.append(f"BUILDER_OUT {redact_text(sample)!r}")
    lines.append(f"FILTER_OUT  {normalise_text(sample)!r}")
    lines.append("")

text = "\n".join(lines).rstrip() + "\n"
(out / "06_dataset_redaction_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 7. Portability grep for historical ELI_MKXI-specific redaction literals ==="
{
  echo "--- dataset_builder.py ELI_MKXI mentions ---"
  grep -RIn --color=never 'ELI_MKXI' "$ROOT/eli/learning/dataset_builder.py" || true
  echo
  echo "--- exact /home/jay source mentions under eli/ ---"
  grep -RIn --color=never '/home/jay' "$ROOT/eli" || true
} | tee "$OUT/07_portability_grep.txt"
echo

echo "=== 8. Git diff ==="
{
  git diff --stat 2>/dev/null || true
  echo
  git diff -- \
    eli/runtime/control_contracts.py \
    eli/learning/dataset_builder.py \
    eli/learning/dataset_filters.py \
    2>/dev/null || true
} > "$OUT/08_patch_diff.txt"

{
  echo "## Repairs performed"
  echo
  echo "1. Narrowed identity-question matching so 'what are you talking about?' no longer routes as SELF_REPORT."
  echo "2. Preserved valid identity routing for 'what are you?', 'what are you exactly?', and related identity forms."
  echo "3. Replaced dataset_builder's historical /home/.../Desktop/ELI_MKXI redaction with dynamic PROJECT_ROOT redaction."
  echo "4. Expanded dataset redaction to recognise Linux/macOS/Windows-shaped home prefixes without hard-coding a user or checkout path."
  echo "5. Recompiled and probed routing/redaction behavior."
  echo
  echo "## Read these first"
  echo
  echo "- \`04_compile.txt\`"
  echo "- \`05_identity_routing_probe.txt\`"
  echo "- \`06_dataset_redaction_probe.txt\`"
  echo "- \`07_portability_grep.txt\`"
  echo "- \`08_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 16 COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/05_identity_routing_probe.txt"
echo "  $OUT/06_dataset_redaction_probe.txt"
echo "======================================================================"
