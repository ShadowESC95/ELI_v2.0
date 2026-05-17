#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_v8_quick_only_${STAMP}"
REPORT="ops/reports/runtime_status_v8_quick_only_patch_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path
import re
import sys

p = Path("eli/kernel/engine.py")
text = p.read_text(encoding="utf-8")

old = '''    def _eli_v8_process(self, message, *args, **kwargs):
        mode = kwargs.get("reasoning_mode", None)
        if mode is None and args:
            # Keep this conservative: most direct calls use reasoning_mode as kwarg.
            # We still avoid consuming positional args unless they are obvious strings.
            for a in args:
                if isinstance(a, str) and a in {
                    "quick",
                    "chain_of_thought",
                    "constitutional_ai",
                    "self_consistency",
                    "tree_of_thoughts",
                }:
                    mode = a
                    break

        if _eli_v8_detect_runtime_status(message):
            return _eli_v8_runtime_status_response(message, mode or "quick")

        return _eli_v8_prev_process(self, message, *args, **kwargs)

    CognitiveEngine.process = _eli_v8_process
    print("[ENGINE] runtime-status all-modes early intercept v8 installed")
'''

new = '''    def _eli_v8_process(self, message, *args, **kwargs):
        mode = kwargs.get("reasoning_mode", None)

        if mode is None:
            mode = kwargs.get("mode", None)

        if mode is None and args:
            # Conservative positional recovery. Do not default unknown mode to Quick.
            for a in args:
                if isinstance(a, str) and a.strip().lower() in {
                    "quick",
                    "chain_of_thought",
                    "constitutional_ai",
                    "self_consistency",
                    "tree_of_thoughts",
                    "tot",
                    "cot",
                    "self-c",
                    "const_ai",
                    "constitutional",
                }:
                    mode = a
                    break

        if mode is None:
            # GUI builds sometimes store the current reasoning mode on the engine.
            for attr in (
                "reasoning_mode",
                "current_reasoning_mode",
                "mode",
                "_reasoning_mode",
                "_current_reasoning_mode",
            ):
                try:
                    v = getattr(self, attr, None)
                    if isinstance(v, str) and v.strip():
                        mode = v
                        break
                except Exception:
                    pass

        mode_key = _eli_v8_str(mode or "").strip().lower().replace("-", "_").replace(" ", "_")
        quick = mode_key in {"quick", "fast", "direct"}

        # Critical contract:
        # Quick mode may return direct grounded runtime evidence.
        # Non-Quick modes must fall through to the previous CognitiveEngine.process
        # wrapper so Stage 11/12 synthesis, persona, validation, and broker routing
        # still run. Do not default unknown mode to Quick.
        if _eli_v8_detect_runtime_status(message) and quick:
            return _eli_v8_runtime_status_response(message, "quick")

        return _eli_v8_prev_process(self, message, *args, **kwargs)

    CognitiveEngine.process = _eli_v8_process
    print("[ENGINE] runtime-status quick-only intercept v9 installed")
'''

if old not in text:
    print("ERROR: exact V8 all-modes block not found.", file=sys.stderr)

    hits = [m.start() for m in re.finditer(r"runtime-status all-modes early intercept v8 installed", text)]
    print(f"found marker count={len(hits)}", file=sys.stderr)

    # Print nearby context to help manual repair.
    marker = "runtime-status all-modes early intercept v8 installed"
    idx = text.find(marker)
    if idx >= 0:
        start = max(0, idx - 2500)
        end = min(len(text), idx + 500)
        print(text[start:end], file=sys.stderr)

    sys.exit(2)

text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

print("patched runtime-status V8 all-modes intercept -> quick-only V9")
PY

python3 -m compileall -q eli/kernel/engine.py

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== CURRENT RUNTIME STATUS INTERCEPT MARKERS ==="
  grep -n "runtime-status .*intercept" "$ENGINE" || true
  echo
  echo "=== CURRENT V8/V9 PROCESS CONTEXT ==="
  grep -n "_eli_v8_process\\|runtime-status quick-only\\|runtime-status all-modes" "$ENGINE" || true
  echo
  echo "=== GIT DIFF ==="
  git diff -- "$ENGINE" || true
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
