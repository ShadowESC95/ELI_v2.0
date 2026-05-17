#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ROUTER="eli/execution/router_enhanced.py"
BACKUP="ops/backups/router_enhanced.py.before_gui_audit_actual_scan_route_v2_${STAMP}"
REPORT="ops/reports/gui_audit_actual_scan_route_v2_${STAMP}.log"

cp -a "$ROUTER" "$BACKUP"

python3 - <<'PY'
from pathlib import Path
import sys

p = Path("eli/execution/router_enhanced.py")
text = p.read_text(encoding="utf-8")

marker = "[ROUTER] GUI audit actual-scan proof route v2 installed"

if marker in text:
    print("GUI audit actual-scan proof route v2 already installed")
    sys.exit(0)

block = r'''

# =============================================================================
# ELI GUI AUDIT ACTUAL-SCAN PROOF ROUTE V2
# Catches direct "did you actually scan/read file in full" probes.
# =============================================================================
try:
    _ELI_GUI_AUDIT_ACTUAL_SCAN_PREV_ROUTE_V2 = route

    def _eli_gui_audit_actual_scan_v2(text):
        q = " ".join(str(text or "").lower().split())
        if not q:
            return False

        file_hit = any(x in q for x in (
            "eli/gui/eli_pro_audio_gui_mki.py",
            "eli_pro_audio_gui_mki.py",
            "gui file",
            "audio gui",
        ))

        scan_hit = any(x in q for x in (
            "actually scan",
            "actually scanned",
            "actually read",
            "did you scan",
            "did you read",
            "scan the file",
            "read the file",
            "in full",
            "full file",
            "whole file",
            "entire file",
        ))

        return bool(file_hit and scan_hit)

    def route(user_text="", *args, **kwargs):
        if _eli_gui_audit_actual_scan_v2(user_text):
            return {
                "action": "GUI_RUNTIME_AUDIT",
                "args": {
                    "question": str(user_text or ""),
                    "proof_requested": True,
                    "audit_depth": "proof",
                    "require_timestamps": True,
                    "require_full_file_read_evidence": True,
                },
                "confidence": 0.995,
                "meta": {
                    "matched_by": "router.gui_audit_actual_scan_proof_v2",
                    "need_grounding": True,
                    "allow_chat_without_evidence": False,
                    "task_family": "grounded_audit",
                    "forbid_chat_fallback": True,
                },
            }

        return _ELI_GUI_AUDIT_ACTUAL_SCAN_PREV_ROUTE_V2(user_text, *args, **kwargs)

    print("[ROUTER] GUI audit actual-scan proof route v2 installed", flush=True)

except Exception as _eli_gui_audit_actual_scan_v2_err:
    print(f"[ROUTER] GUI audit actual-scan proof route v2 failed: {_eli_gui_audit_actual_scan_v2_err}", flush=True)
'''

text = text.rstrip() + "\n\n" + block + "\n"
p.write_text(text, encoding="utf-8")
print("installed GUI audit actual-scan proof route v2")
PY

python3 -m compileall -q "$ROUTER"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== ROUTE PROBE ==="
  python3 - <<'PY'
from eli.execution.router_enhanced import route

tests = [
    "Did you actually scan eli/gui/eli_pro_audio_gui_MKI.py in full?",
    "Prove to me that you actually scanned the file provide data or timestamps etc",
    "YES, I WANT MORE DETAILS AND TIMESTAMPS AS PROOF THAT YOU READ THE FILE",
]

for t in tests:
    print()
    print("PROMPT:", t)
    print(route(t))
PY
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ROUTER" || true
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
