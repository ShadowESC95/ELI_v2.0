#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_visible_sanitize_v11_${STAMP}"
REPORT="ops/reports/runtime_status_visible_sanitize_v11_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path
import sys

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11"

if marker in src:
    print("runtime-status visible sanitize v11 already installed")
    raise SystemExit(0)

append = r'''

# =============================================================================
# ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11
# Purpose:
#   - Keep Quick direct runtime evidence allowed.
#   - Keep non-Quick runtime-status synthesis/repair contract intact.
#   - Prevent raw template/control poison tokens from appearing in visible repaired
#     runtime-status diagnostics.
#   - Normalize quick runtime wording from ctx=... to context_size=... so probes
#     and user-visible output use the same field language.
# =============================================================================

try:
    import re as _eli_v11_re

    _ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11_PREV_PROCESS = CognitiveEngine.process

    _ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11_POISON_REPLACEMENTS = {
        "</think>": "[blocked-template-token]",
        "<|im_": "[blocked-chatml-token:",
        "|im_end|": "[blocked-chatml-end]",
        ">>>>>>>": "[blocked-merge-marker]",
        "<<<<<<<": "[blocked-merge-marker]",
    }

    def _eli_runtime_status_visible_sanitize_v11_text(_text):
        if not isinstance(_text, str):
            return _text

        _out = _text

        # Normalize compact quick wording without changing the underlying runtime data.
        _out = _out.replace("effective ctx=", "effective context_size=")
        _out = _out.replace(" ctx=", " context_size=")

        # Do not render the raw offending poison token inside repair_reason.
        # Example:
        #   repair_reason: poison_token_or_unsupported_claim:</think>
        # becomes:
        #   repair_reason: poison_token_or_unsupported_claim
        _out = _eli_v11_re.sub(
            r"(repair_reason:\s*poison_token_or_unsupported_claim):[^\s]+",
            r"\1",
            _out,
            flags=_eli_v11_re.IGNORECASE,
        )

        # Final visible-surface sweep. This is not synthesis. It is output hygiene.
        for _bad, _safe in _ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11_POISON_REPLACEMENTS.items():
            _out = _out.replace(_bad, _safe)

        return _out

    def _eli_runtime_status_visible_sanitize_v11_process(self, *args, **kwargs):
        _result = _ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11_PREV_PROCESS(self, *args, **kwargs)

        if isinstance(_result, dict) and _result.get("action") == "RUNTIME_STATUS":
            for _key in ("content", "response"):
                if isinstance(_result.get(_key), str):
                    _result[_key] = _eli_runtime_status_visible_sanitize_v11_text(_result[_key])

            _report = _result.get("report")
            if isinstance(_report, dict):
                _rr = _report.get("repair_reason")
                if isinstance(_rr, str):
                    _rr_clean = _rr
                    if "poison_token_or_unsupported_claim:" in _rr_clean:
                        _rr_clean = "poison_token_or_unsupported_claim"
                    for _bad, _safe in _ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11_POISON_REPLACEMENTS.items():
                        _rr_clean = _rr_clean.replace(_bad, _safe)
                    _report["repair_reason"] = _rr_clean

        return _result

    CognitiveEngine.process = _eli_runtime_status_visible_sanitize_v11_process
    print("[ENGINE] runtime-status visible sanitize v11 installed", flush=True)

except Exception as _eli_runtime_status_visible_sanitize_v11_err:
    print(
        f"[ENGINE] runtime-status visible sanitize v11 failed: {_eli_runtime_status_visible_sanitize_v11_err!r}",
        flush=True,
    )
'''

p.write_text(src.rstrip() + "\n\n" + append + "\n", encoding="utf-8")
print("installed runtime-status visible sanitize v11")
PY

python3 -m py_compile "$ENGINE"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== MARKERS ==="
  grep -n "runtime-status visible sanitize v11\|ELI_RUNTIME_STATUS_VISIBLE_SANITIZE_V11" "$ENGINE" || true
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ENGINE"
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
