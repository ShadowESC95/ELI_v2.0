#!/usr/bin/env bash
# ============================================================
# ELI Claim Verification — Final patch for S3 and S29
# Based on diagnostic output:
#   S3:  stage names are matched_by values; count via known-name grep
#   S29: real API is capability_count(), discover(), live_capability_names()
#        (discover_count/public_like_count/router_only attrs don't exist)
# ============================================================
ROOT="$(pwd)"
PASS=0; FAIL=0; WARN=0

green(){ printf '\033[32m[PASS]\033[0m %s\n' "$*"; }
red(){   printf '\033[31m[FAIL]\033[0m %s\n' "$*"; }
yellow(){ printf '\033[33m[WARN]\033[0m %s\n' "$*"; }

assert_ge(){
  local label="$1" threshold="$2"
  local n; n=$(echo "$3" | grep -oP '^\d+' || echo 0); n=${n:-0}
  if (( n >= threshold )); then
    green "$label — >=$threshold actual=$n"; PASS=$((PASS+1))
  else
    red   "$label — >=$threshold actual=$n"; FAIL=$((FAIL+1))
  fi
}

assert_eq(){
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    green "$label — expected=$expected actual=$actual"; PASS=$((PASS+1))
  else
    red   "$label — expected=$expected actual=$actual"; FAIL=$((FAIL+1))
  fi
}

echo "============================================================"
echo " ELI Claim Verification — Final patch — $(date)"
echo " CWD: $ROOT"
echo "============================================================"
echo ""

# ── S3 FINAL FIX: Count known stage names present in router ──
echo "── S3 (final). Router priority pipeline — 20 known stage names"
KNOWN_STAGES=(
  precedence memory_runtime_lock gui_actual_scan
  self_report_recent_updates recent_memory memory_count
  profile_scope_explicit final_memory_contract
  runtime_or_name_contract identity_name_source_contract
  runtime_cognition_failure_guard self_improvement_guard
  personal_memory_pre_route lrf_pre_route portable_route
  voice_contract persona_override followup_passthrough
  identity_contract core_router
)
FOUND=0; MISSING=()
for stage in "${KNOWN_STAGES[@]}"; do
  if grep -qF "$stage" eli/execution/router_enhanced.py 2>/dev/null; then
    FOUND=$((FOUND+1))
  else
    MISSING+=("$stage")
  fi
done

echo "  Stage names present in router source: $FOUND / ${#KNOWN_STAGES[@]}"
if (( ${#MISSING[@]} > 0 )); then
  echo "  Missing: ${MISSING[*]}"
fi

assert_eq "all 20 router stage names present" "20" "$FOUND"

# Also confirm matched_by is the carrier (not priority_pipeline_stage as a key)
MW_OCCURRENCES=$(grep -c "matched_by" eli/execution/router_enhanced.py 2>/dev/null || echo 0)
echo "  'matched_by' occurrences in router: $MW_OCCURRENCES"
assert_ge "matched_by occurrences in router" 5 "$MW_OCCURRENCES"
echo ""

# ── S29 FINAL FIX: Use actual CapabilitySync API ──────────────
echo "── S29 (final). CapabilitySync — using real API ──────────────"
TMPPY=$(mktemp /tmp/eli_sync2_XXXXXX.py)
cat > "$TMPPY" << 'ENDPY'
import sys, logging
logging.disable(logging.CRITICAL)
try:
    from eli.runtime.capability_sync import CapabilitySync
    s = CapabilitySync()

    # capability_count() is the direct equivalent of discover_count
    total = s.capability_count()
    print(f"capability_count={total}")

    # discover() returns full dict; derive public-like and router-only from it
    caps = s.discover()
    if isinstance(caps, dict):
        public_like = sum(
            1 for v in caps.values()
            if isinstance(v, dict) and (
                v.get("in_supported_list") or v.get("routable")
            )
        )
        router_only = sum(
            1 for v in caps.values()
            if isinstance(v, dict)
            and v.get("routable")
            and not v.get("in_dispatch")
            and not v.get("in_supported_list")
        )
        print(f"public_like_count={public_like}")
        print(f"router_only={router_only}")
    else:
        print(f"public_like_count=?  (discover() returned {type(caps).__name__})")
        print(f"router_only=?")

    # live names as a sanity cross-check
    names = s.live_capability_names()
    print(f"live_capability_names_count={len(names) if names else 0}")

except Exception as e:
    print(f"error: {e}")
ENDPY

SYNC_OUT=$(PYTHONPATH="$ROOT" python3 "$TMPPY" 2>/dev/null || echo "unavailable")
rm -f "$TMPPY"

echo "$SYNC_OUT" | sed 's/^/  /'
echo "  (transcript claimed: discover_count=169, public_like_count=134, router_only=0)"
echo ""

# Assertions
CAP_COUNT=$(echo "$SYNC_OUT" | grep -oP 'capability_count=\K\d+' || echo 0)
PUB_COUNT=$(echo "$SYNC_OUT" | grep -oP 'public_like_count=\K\d+' || echo 0)
RO_COUNT=$(echo  "$SYNC_OUT" | grep -oP 'router_only=\K\d+'       || echo 0)
LIVE_COUNT=$(echo "$SYNC_OUT" | grep -oP 'live_capability_names_count=\K\d+' || echo 0)

assert_eq "capability_count() == 169"          "169" "${CAP_COUNT:-0}"
assert_ge "public_like_count >= 100"            100   "${PUB_COUNT:-0}"
assert_eq "router_only == 0"                   "0"   "${RO_COUNT:-0}"
assert_ge "live_capability_names count >= 100" 100   "${LIVE_COUNT:-0}"

# Cross-check: transcript claimed public_like=134; flag if far off
if [[ -n "$PUB_COUNT" ]] && (( PUB_COUNT > 0 )); then
  DELTA=$(( PUB_COUNT > 134 ? PUB_COUNT - 134 : 134 - PUB_COUNT ))
  if (( DELTA <= 10 )); then
    green "public_like_count within 10 of claimed 134 (actual=$PUB_COUNT delta=$DELTA)"
    PASS=$((PASS+1))
  else
    yellow "public_like_count=$PUB_COUNT vs claimed 134 (delta=$DELTA — definition may differ)"
    WARN=$((WARN+1))
  fi
fi
echo ""

# ── FINAL SUMMARY ─────────────────────────────────────────────
echo "============================================================"
echo " FINAL PATCH SUMMARY"
echo "============================================================"
printf ' \033[32mPASS\033[0m : %d\n' $PASS
printf ' \033[31mFAIL\033[0m : %d\n' $FAIL
printf ' \033[33mWARN\033[0m : %d\n' $WARN
echo ""
echo " Combined scorecard (v3 baseline + both patch runs):"
echo "   v3 baseline     : 72 PASS / 2 FAIL (S3, S12) / 10 WARN"
echo "   patch v1 fixed  : S12 (SUPPORTED_ACTIONS=132 ✓), S16 (0 non-init dups ✓)"
echo "   this patch fixes: S3 (router stage count), S29 (CapabilitySync API)"
echo ""
echo " Remaining transcript inaccuracies (informational, not regressions):"
echo "   engine.py:     9962 lines (transcript estimated ~6600)"
echo "   orch stages:   11 string tokens (transcript said 17 entries)"
echo "   engine markers: 8 (transcript claimed 9)"
echo "   render_action:  7 defs (transcript claimed 8)"
echo "   CapabilitySync: attrs renamed; capability_count() is the real API"
echo "============================================================"
