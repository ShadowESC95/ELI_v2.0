#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/bash_audit_cleanup_${STAMP}"
QUAR="$OUT/quarantine"

mkdir -p "$OUT" "$QUAR"
exec > >(tee "$OUT/run.log") 2>&1

echo "Bash audit + cleanup: $OUT"
echo

FAIL=0

echo "=== git before ==="
git status -sb
git log --oneline --decorate -5 || true
echo

echo "=== collect bash scripts ==="
mapfile -t SCRIPTS < <(
  find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './ops/reports' -prune -o \
    -type f \( -name '*.sh' -o -name 'eli.sh' -o -name 'install.sh' -o -name 'run_tests.sh' \) \
    -printf '%P\n' | sort
)

printf '%s\n' "${SCRIPTS[@]}" > "$OUT/00_bash_scripts.txt"
echo "script_count=${#SCRIPTS[@]}"
cat "$OUT/00_bash_scripts.txt"
echo

echo "=== safe text normalization: CRLF, trailing whitespace, final newline ==="
NORMALIZED_COUNT="$(
python3 - "$OUT/00_bash_scripts.txt" <<'PY'
from pathlib import Path
import sys

script_list = Path(sys.argv[1])
count = 0

for rel in script_list.read_text(encoding="utf-8").splitlines():
    p = Path(rel)
    if not p.exists() or not p.is_file():
        continue
    try:
        raw = p.read_bytes()
    except Exception:
        continue
    if b"\x00" in raw:
        continue
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        continue

    new = text.replace("\r\n", "\n").replace("\r", "\n")
    new = "\n".join(line.rstrip() for line in new.split("\n")).rstrip() + "\n"

    if new != text:
        p.write_text(new, encoding="utf-8")
        print(rel)
        count += 1

print(f"COUNT={count}")
PY
)"
echo "$NORMALIZED_COUNT" | sed -n '/^COUNT=/!p'
NORMALIZED_COUNT="$(echo "$NORMALIZED_COUNT" | awk -F= '/^COUNT=/{print $2}' | tail -1)"
NORMALIZED_COUNT="${NORMALIZED_COUNT:-0}"
echo "normalized_count=$NORMALIZED_COUNT"
echo

echo "=== executable bit normalization ==="
echo "non-mutating: executable issues are reported in shebang audit; no chmod is applied"
echo

echo "=== bash -n syntax audit ==="
: > "$OUT/01_bash_n_failures.txt"
for f in "${SCRIPTS[@]}"; do
  if ! bash -n "$f" >> "$OUT/01_bash_n_failures.txt" 2>&1; then
    echo "bash -n failed: $f" >> "$OUT/01_bash_n_failures.txt"
  fi
done

if [[ -s "$OUT/01_bash_n_failures.txt" ]]; then
  echo "bash -n: FAIL"
  cat "$OUT/01_bash_n_failures.txt"
  FAIL=1
else
  echo "bash -n: PASS"
fi
echo

echo "=== shellcheck audit if available ==="
if command -v shellcheck >/dev/null 2>&1; then
  : > "$OUT/02_shellcheck.txt"
  if ! shellcheck "${SCRIPTS[@]}" > "$OUT/02_shellcheck.txt" 2>&1; then
    echo "shellcheck: WARN/FAIL"
    cat "$OUT/02_shellcheck.txt"
  else
    echo "shellcheck: PASS"
  fi
else
  {
    echo "shellcheck not installed; skipping."
    echo "Install later with: sudo apt install shellcheck"
  } | tee "$OUT/02_shellcheck.txt"
fi
echo

echo "=== shebang / executable audit ==="
: > "$OUT/03_shebang_executable_warnings.txt"
for f in "${SCRIPTS[@]}"; do
  first="$(head -n 1 "$f" 2>/dev/null || true)"
  if [[ "$first" == '#!'* && ! -x "$f" ]]; then
    echo "not executable despite shebang: $f" >> "$OUT/03_shebang_executable_warnings.txt"
  fi
done

if [[ -s "$OUT/03_shebang_executable_warnings.txt" ]]; then
  echo "shebang/executable audit: WARN"
  cat "$OUT/03_shebang_executable_warnings.txt"
else
  echo "shebang/executable audit: PASS"
fi
echo

echo "=== risky token / broken paste audit ==="
python3 - "$OUT/00_bash_scripts.txt" "$OUT/04_broken_paste_risk_hits.txt" <<'PY'
from pathlib import Path
import re
import sys

script_list = Path(sys.argv[1])
out = Path(sys.argv[2])

frag_head = "HEAD"
frag_final = "FINAL" + "_REPORT="
frag_bad_txt = "txt" + '"n'

patterns = [
    re.compile(frag_head + "rate"),
    re.compile(frag_head + r"r\\b"),
    re.compile(r"git checkout -- \\git"),
    re.compile(r"git add \\git"),
    re.compile("echo " + r'"echo'),
    re.compile(r"\.sh1\.sh"),
    re.compile(r"\.shh\s"),
    re.compile("status after " + r'audit ==="'),
    re.compile(re.escape(frag_final) + r".*" + re.escape(frag_bad_txt)),
]

hits = []
for rel in script_list.read_text(encoding="utf-8").splitlines():
    p = Path(rel)
    if not p.exists() or not p.is_file():
        continue
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        continue

    for i, line in enumerate(lines, 1):
        for pat in patterns:
            if pat.search(line):
                hits.append(f"{rel}:{i}: {line}")
                break

out.write_text("\n".join(hits) + ("\n" if hits else ""), encoding="utf-8")
print("\n".join(hits))
PY

if [[ -s "$OUT/04_broken_paste_risk_hits.txt" ]]; then
  echo "broken-paste risk audit: FAIL"
  FAIL=1
else
  echo "broken-paste risk audit: PASS"
fi
echo

echo "=== quarantine incomplete failed report dirs ==="
INCOMPLETE_COUNT=0
mkdir -p "$QUAR/incomplete_reports"

while IFS= read -r dir; do
  [[ "$dir" == "$OUT" ]] && continue
  [[ "$dir" == *"/quarantine/"* ]] && continue

  case "$dir" in
    ops/reports/wrapper_stack_audit_*|ops/reports/callable_chain_audit_*|ops/reports/bash_audit_cleanup_*)
      if [[ ! -f "$dir/SUMMARY.txt" ]]; then
        base="$(basename "$dir")"
        mv "$dir" "$QUAR/incomplete_reports/$base"
        echo "quarantined incomplete report dir: $dir"
        INCOMPLETE_COUNT=$((INCOMPLETE_COUNT + 1))
      fi
      ;;
  esac
done < <(find ops/reports -maxdepth 1 -mindepth 1 -type d | sort)

echo "incomplete_report_dirs_quarantined=$INCOMPLETE_COUNT"
echo

echo "=== quarantine patch backup files ==="
BACKUP_COUNT=0
mkdir -p "$QUAR/patch_backups"

while IFS= read -r file; do
  rel="${file#./}"
  dest="$QUAR/patch_backups/$rel"
  mkdir -p "$(dirname "$dest")"
  mv "$rel" "$dest"
  echo "quarantined backup: $rel"
  BACKUP_COUNT=$((BACKUP_COUNT + 1))
done < <(
  find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './ops/reports' -prune -o \
    -type f \( -name '*.bak' -o -name '*.bak_*' -o -name '*.backup' -o -name '*.orig' \) \
    -print | sort
)

echo "backup_files_quarantined=$BACKUP_COUNT"
echo

echo "=== remove generated __pycache__ outside .venv/.git/ops/reports ==="
PYCACHE_COUNT=0
while IFS= read -r d; do
  rm -rf "$d"
  PYCACHE_COUNT=$((PYCACHE_COUNT + 1))
done < <(
  find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './ops/reports' -prune -o \
    -type d -name '__pycache__' -print | sort
)
echo "pycache_dirs_removed=$PYCACHE_COUNT"
echo

echo "=== compile critical python surfaces ==="
if python3 -m py_compile \
  eli/execution/router_enhanced.py \
  eli/execution/executor_enhanced.py \
  eli/kernel/engine.py; then
  echo "compile: PASS"
else
  echo "compile: FAIL"
  FAIL=1
fi
echo

echo "=== git diff hygiene ==="
if git diff --check > "$OUT/05_git_diff_check.txt" 2>&1; then
  echo "git diff --check: PASS"
else
  echo "git diff --check: FAIL"
  cat "$OUT/05_git_diff_check.txt"
  FAIL=1
fi
echo

echo "=== final bash -n after cleanup ==="
: > "$OUT/06_final_bash_n_failures.txt"
mapfile -t FINAL_SCRIPTS < <(
  find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './ops/reports' -prune -o \
    -type f \( -name '*.sh' -o -name 'eli.sh' -o -name 'install.sh' -o -name 'run_tests.sh' \) \
    -printf '%P\n' | sort
)

for f in "${FINAL_SCRIPTS[@]}"; do
  if ! bash -n "$f" >> "$OUT/06_final_bash_n_failures.txt" 2>&1; then
    echo "bash -n failed: $f" >> "$OUT/06_final_bash_n_failures.txt"
  fi
done

if [[ -s "$OUT/06_final_bash_n_failures.txt" ]]; then
  echo "final bash -n: FAIL"
  cat "$OUT/06_final_bash_n_failures.txt"
  FAIL=1
else
  echo "final bash -n: PASS"
fi
echo

echo "=== git after ==="
git status -sb
echo

RESULT="PASS"
if [[ "$FAIL" -ne 0 ]]; then
  RESULT="FAIL"
fi

{
  echo "Bash audit + cleanup: $OUT"
  echo
  echo "Result: $RESULT"
  echo
  echo "Scripts audited: ${#SCRIPTS[@]}"
  echo "Incomplete report dirs quarantined: $INCOMPLETE_COUNT"
  echo "Backup files quarantined: $BACKUP_COUNT"
  echo "Pycache dirs removed: $PYCACHE_COUNT"
  echo
  echo "Git status:"
  git status -sb
  echo
  echo "Diff stat:"
  git diff --stat || true
  echo
  echo "Reports:"
  echo "- $OUT/00_bash_scripts.txt"
  echo "- $OUT/01_bash_n_failures.txt"
  echo "- $OUT/02_shellcheck.txt"
  echo "- $OUT/03_shebang_executable_warnings.txt"
  echo "- $OUT/04_broken_paste_risk_hits.txt"
  echo "- $OUT/05_git_diff_check.txt"
  echo "- $OUT/06_final_bash_n_failures.txt"
  echo "- $OUT/run.log"
} | tee "$OUT/SUMMARY.txt"

echo
echo "SUMMARY=$OUT/SUMMARY.txt"
echo "BASH_AUDIT_CLEANUP_RESULT=$RESULT"

[[ "$RESULT" == "PASS" ]]
