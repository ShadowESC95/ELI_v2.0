#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase16b_identity_matcher_dataset_portability_repair_${STAMP}"
BACKUP="$OUT/backups"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 16B — Identity Matcher + Dataset Path Portability Repair"
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
  echo "# Phase 16B — Identity Matcher + Dataset Path Portability Repair"
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

echo "=== 1. Inspect current identity matcher vicinity ==="
{
  grep -n -C 4 --color=never 'what are you' \
    "$ROOT/eli/runtime/control_contracts.py" || true
} | tee "$OUT/01_identity_matcher_before.txt"
echo

echo "=== 2. Patch control_contracts.py identity matcher without brittle escape assumptions ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/runtime/control_contracts.py"

src = path.read_text(encoding="utf-8")

marker = "# PHASE16B_IDENTITY_WHAT_ARE_YOU_BOUNDARY_FIX"

if marker in src:
    print("SKIP: Phase 16B identity matcher patch already present.")
    (out / "02_control_contracts_identity_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

# Match the real raw-regex alternative line regardless of whether local formatting
# uses spaces differently. We target only the identity-regex alternative, not prose.
pattern = re.compile(
    r'(?m)^(?P<indent>\s*)r"\|what are you\(\?:\\s\|\$\)"\s*$'
)

match = pattern.search(src)

if not match:
    # Fallback: show nearby lines in the failure record for exact next diagnosis.
    nearby = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if "what are you" in line:
            nearby.append(f"{lineno}: {line}")
    (out / "02_control_contracts_identity_patch_failure.txt").write_text(
        "Could not match old identity alternative.\n\n"
        + "\n".join(nearby)
        + "\n",
        encoding="utf-8",
    )
    raise SystemExit(
        "PATCH FAILED: could not match identity alternative "
        "`r\"|what are you(?:\\s|$)\"`. "
        f"See {out / '02_control_contracts_identity_patch_failure.txt'}"
    )

indent = match.group("indent")

replacement = (
    f'{indent}# PHASE16B_IDENTITY_WHAT_ARE_YOU_BOUNDARY_FIX\n'
    f'{indent}# Match identity questions such as "what are you?" or\n'
    f'{indent}# "what are you exactly?", but do not match normal\n'
    f'{indent}# conversational text such as "what are you talking about?".\n'
    f'{indent}r"|what are you(?=\\s*(?:[?!.,]*\\s*$|(?:exactly|really|actually)[?!.,]*\\s*$))"'
)

patched, n = pattern.subn(replacement, src, count=1)

if n != 1:
    raise SystemExit(f"PATCH FAILED: expected one identity substitution, got {n}.")

path.write_text(patched, encoding="utf-8")

(out / "02_control_contracts_identity_patch.txt").write_text(
    "PATCHED control_contracts.py: identity matcher no longer overmatches `what are you talking about?`.\n",
    encoding="utf-8",
)

print("PATCHED control_contracts.py")
PY
echo

echo "=== 3. Patch dataset_builder.py: dynamic PROJECT_ROOT redaction instead of historical ELI_MKXI path ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/learning/dataset_builder.py"

src = path.read_text(encoding="utf-8")

marker = "# PHASE16B_DYNAMIC_PROJECT_ROOT_REDACTION"

if marker in src:
    print("SKIP: Phase 16B dataset_builder portability patch already present.")
    (out / "03_dataset_builder_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

old = '''HOME_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+")
PROJECT_PATH_RE = re.compile(r"/home/[A-Za-z0-9._-]+/Desktop/ELI_MKXI")
'''

new = '''# PHASE16B_DYNAMIC_PROJECT_ROOT_REDACTION
# Redact the actual local checkout dynamically. Do not assume a username,
# a Desktop checkout, a Linux-only host, or a historical ELI_MKXI folder name.
PROJECT_PATH_RE = re.compile(re.escape(str(PROJECT_ROOT)))

# Sanitisation patterns for common user-home path shapes. These are redaction
# rules, not operational filesystem defaults.
HOME_PATH_RE = re.compile(
    r"(?:"
    r"/home/[A-Za-z0-9._-]+"
    r"|/Users/[A-Za-z0-9._-]+"
    r"|[A-Za-z]:\\\\Users\\\\[^\\\\\\s]+"
    r")"
)
'''

if old not in src:
    nearby = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if "HOME_PATH_RE" in line or "PROJECT_PATH_RE" in line:
            nearby.append(f"{lineno}: {line}")
    (out / "03_dataset_builder_patch_failure.txt").write_text(
        "Could not find old redaction block.\n\n"
        + "\n".join(nearby)
        + "\n",
        encoding="utf-8",
    )
    raise SystemExit(
        "PATCH FAILED: could not find old HOME_PATH_RE / PROJECT_PATH_RE block. "
        f"See {out / '03_dataset_builder_patch_failure.txt'}"
    )

patched = src.replace(old, new, 1)
path.write_text(patched, encoding="utf-8")

(out / "03_dataset_builder_patch.txt").write_text(
    "PATCHED dataset_builder.py: dynamic PROJECT_ROOT redaction and cross-platform HOME redaction installed.\n",
    encoding="utf-8",
)

print("PATCHED dataset_builder.py")
PY
echo

echo "=== 4. Patch dataset_filters.py: add Windows-shaped user-home redaction ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/learning/dataset_filters.py"

src = path.read_text(encoding="utf-8")

marker = "# PHASE16B_WINDOWS_HOME_REDACTION"

if marker in src:
    print("SKIP: Phase 16B dataset_filters portability patch already present.")
    (out / "04_dataset_filters_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

old = '''    s = re.sub(r"/home/[A-Za-z0-9._-]+", "<HOME>", s)
    s = re.sub(r"/Users/[A-Za-z0-9._-]+", "<HOME>", s)
'''

new = '''    s = re.sub(r"/home/[A-Za-z0-9._-]+", "<HOME>", s)
    s = re.sub(r"/Users/[A-Za-z0-9._-]+", "<HOME>", s)
    # PHASE16B_WINDOWS_HOME_REDACTION
    s = re.sub(r"[A-Za-z]:\\\\Users\\\\[^\\\\\\s]+", "<HOME>", s)
'''

if old not in src:
    nearby = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        if 're.sub(r"/home/' in line or 're.sub(r"/Users/' in line:
            nearby.append(f"{lineno}: {line}")
    (out / "04_dataset_filters_patch_failure.txt").write_text(
        "Could not find old dataset_filters home-redaction lines.\n\n"
        + "\n".join(nearby)
        + "\n",
        encoding="utf-8",
    )
    raise SystemExit(
        "PATCH FAILED: could not find dataset_filters home-redaction block. "
        f"See {out / '04_dataset_filters_patch_failure.txt'}"
    )

patched = src.replace(old, new, 1)
path.write_text(patched, encoding="utf-8")

(out / "04_dataset_filters_patch.txt").write_text(
    "PATCHED dataset_filters.py: Windows-shaped user-home path redaction added.\n",
    encoding="utf-8",
)

print("PATCHED dataset_filters.py")
PY
echo

echo "=== 5. Compile verification ==="
{
  python3 -m py_compile \
    "$ROOT/eli/runtime/control_contracts.py" \
    "$ROOT/eli/learning/dataset_builder.py" \
    "$ROOT/eli/learning/dataset_filters.py"

  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"

  echo "PY_COMPILE_OK"
  echo "COMPILEALL_OK"
} | tee "$OUT/05_compile.txt"
echo

echo "=== 6. Identity routing probe ==="
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
    "what are you actually?",
    "what are you doing?",
    "tell me about yourself",
    "what is wrong with your last response?",
]

lines = []

for case in cases:
    action = route_control_text(case, current_action=None)
    lines.append(f"CONTROL case={case!r} action={action!r}")

text = "\n".join(lines) + "\n"
(out / "06_identity_routing_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 7. Dataset redaction portability probe ==="
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
    "/home/alice/Desktop/SomeCheckout/data.txt",
    "/Users/charlie/Projects/ELI/data.txt",
    r"C:\Users\Dana\Documents\ELI\notes.txt",
]

lines = []

for sample in samples:
    lines.append(f"INPUT       {sample!r}")
    lines.append(f"BUILDER_OUT {redact_text(sample)!r}")
    lines.append(f"FILTER_OUT  {normalise_text(sample)!r}")
    lines.append("")

text = "\n".join(lines).rstrip() + "\n"
(out / "07_dataset_redaction_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 8. Portability grep ==="
{
  echo "--- ELI_MKXI mentions in dataset_builder.py ---"
  grep -RIn --color=never 'ELI_MKXI' "$ROOT/eli/learning/dataset_builder.py" || true
  echo
  echo "--- Exact /home/jay source mentions under eli/ ---"
  grep -RIn --color=never '/home/jay' "$ROOT/eli" || true
} | tee "$OUT/08_portability_grep.txt"
echo

echo "=== 9. Identity matcher after patch ==="
{
  grep -n -C 5 --color=never 'PHASE16B_IDENTITY_WHAT_ARE_YOU_BOUNDARY_FIX' \
    "$ROOT/eli/runtime/control_contracts.py" || true
} | tee "$OUT/09_identity_matcher_after.txt"
echo

echo "=== 10. Git diff ==="
{
  git diff --stat 2>/dev/null || true
  echo
  git diff -- \
    eli/runtime/control_contracts.py \
    eli/learning/dataset_builder.py \
    eli/learning/dataset_filters.py \
    2>/dev/null || true
} > "$OUT/10_patch_diff.txt"

{
  echo "## Repairs performed"
  echo
  echo "1. Narrowed the identity matcher so 'what are you talking about?' no longer routes as SELF_REPORT."
  echo "2. Preserved intended identity routing for 'what are you?', 'what are you exactly?', 'what are you really?', and 'what are you actually?'."
  echo "3. Replaced dataset_builder's historical ELI_MKXI checkout redaction with dynamic PROJECT_ROOT redaction."
  echo "4. Expanded dataset redaction to cover Linux, macOS, and Windows-shaped home paths without hard-coding a user or checkout layout."
  echo "5. Recompiled and verified routing/redaction behavior."
  echo
  echo "## Read these first"
  echo
  echo "- \`05_compile.txt\`"
  echo "- \`06_identity_routing_probe.txt\`"
  echo "- \`07_dataset_redaction_probe.txt\`"
  echo "- \`08_portability_grep.txt\`"
  echo "- \`10_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 16B COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/06_identity_routing_probe.txt"
echo "  $OUT/07_dataset_redaction_probe.txt"
echo "======================================================================"
