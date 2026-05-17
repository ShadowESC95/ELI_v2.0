#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

TRACKED_NOISE=(
  ".capability_snapshot.json"
  "capability_manifest.json"
  "eli/capability_inventory.generated.json"
  "eli/cognition/persona.auto.txt"
)

BAD_RE="Could you please clarify|What specific details|What specific aspects|what do you need to know|clarify score|What specifically|what specifically|What are you looking for|what are you looking for|How can I assist you further|how can I assist you further|How can I assist further|how can I assist further|How can I help|how can I help|Do you need anything else|do you need anything else|Anything else|anything else"
POISON_RE="No active projects|No memory states|No external connections|No external databases|No external models loaded|No external dependencies|external dependencies are active|model details will be provided in the next response|Memory usage: 512 MB|Memory usage: adaptive|Mapped to memory: Yes|Locked in memory: Yes|No use of locking|Active projects include|active debugging|debugging SQLite memory|project development|operational context includes|no recent failures or errors have been stored|no other details are stored|latest GGUF model|How can I assist you further|What specifically are you interested|What specifically do you need this for|This setup is optimized|allows for detailed and personalized responses|tailored to your needs|without relying on external services|independently of external services|cloud services are used|secure and private experience|No specific model loaded|I use Qwen for inference|tailored to your runtime needs|tailored to your runtime needs and preferences|No batch size specified|fresh session|not connected to any external systems|operate entirely on my local hardware|no cloud connections|no external data streams"

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="ops/reports/mainline_grounded_control_no_clarify_clean_${STAMP}.log"

cleanup() {
  git restore "${TRACKED_NOISE[@]}" 2>/dev/null || true
}
trap cleanup EXIT

PYTHONPATH="$PWD" python3 ops/probes/runtime_status_contract_assert_v17.py \
  2>&1 | tee "$REPORT"

echo
echo "=== VISIBLE / CONTROL-SURFACE BAD CLARIFICATION SCAN ==="

VISIBLE_BAD="$(grep -nEi "$BAD_RE" "$REPORT" | grep -v "\[GGUF\]\[RAW_TEXT\]" || true)"

if [[ -n "$VISIBLE_BAD" ]]; then
  echo "$VISIBLE_BAD"
  echo
  echo "FAIL: bad clarification text reached non-raw/control-visible log surface."
  cleanup
  git status -sb
  echo
  echo "Report: $REPORT"
  exit 3
else
  echo "PASS: no bad clarification text reached visible/control surface."
fi

echo
echo "=== RAW GGUF CANDIDATE CLARIFICATION SCAN ==="

RAW_BAD="$(grep -nEi "$BAD_RE" "$REPORT" | grep "\[GGUF\]\[RAW_TEXT\]" || true)"

if [[ -n "$RAW_BAD" ]]; then
  echo "$RAW_BAD"
  echo
  echo "WARN: raw discarded GGUF candidate still contains clarification language."
  echo "This is not user-visible, but it is still model-candidate contamination."
else
  echo "PASS: no raw GGUF candidate clarification text found."
fi

echo
echo "=== RUNTIME STATUS POISON CLAIM SCAN ==="

POISON_BAD="$(grep -nEi "$POISON_RE" "$REPORT" \
  | grep -v "Runtime-status poisoned synthesis rejected" \
  | grep -v "hits=\[" \
  || true)"

if [[ -n "$POISON_BAD" ]]; then
  echo "$POISON_BAD"
  echo
  echo "INFO: raw GGUF diagnostic candidates still produced unsupported runtime-status claims."
  echo "INFO: this is not a contract failure unless the claim reaches ACTION / CONTENT HEAD / final visible output."
else
  echo "PASS: no poisoned runtime-status claims found in raw diagnostic candidates."
fi

echo
echo "=== SUPPRESSION MARKER ==="
grep -n "grounded-control no-clarify v2 suppressed" "$REPORT" || true

echo
echo "=== STATUS AFTER CLEANUP ==="
cleanup
git status -sb

echo
echo "Report: $REPORT"
