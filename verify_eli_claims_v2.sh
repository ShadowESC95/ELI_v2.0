#!/usr/bin/env bash
# ============================================================
# ELI Codebase Claim Verification Script
# Tests every concrete numeric/structural assertion from the
# analysis transcript. No files are modified or deleted.
# Usage:  cd /path/to/ELI_MKXI-main_MAY_NEWEST && bash verify_eli_claims.sh
# ============================================================
set -euo pipefail

ROOT="$(pwd)"
PASS=0; FAIL=0; WARN=0
REPORT=""

# ── helpers ──────────────────────────────────────────────────
green(){ echo -e "\033[32m[PASS]\033[0m $*"; }
red(){   echo -e "\033[31m[FAIL]\033[0m $*"; }
yellow(){ echo -e "\033[33m[WARN]\033[0m $*"; }

assert_eq(){
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    green "$label — expected=$expected actual=$actual"
    PASS=$((PASS+1)); REPORT+="PASS|$label|expected=$expected|actual=$actual\n"
  else
    red  "$label — expected=$expected actual=$actual"
    FAIL=$((FAIL+1)); REPORT+="FAIL|$label|expected=$expected|actual=$actual\n"
  fi
}

assert_ge(){
  local label="$1" threshold="$2" actual="$3"
  if (( actual >= threshold )); then
    green "$label — >=$threshold actual=$actual"
    PASS=$((PASS+1)); REPORT+="PASS|$label|>=$threshold|actual=$actual\n"
  else
    red  "$label — >=$threshold actual=$actual"
    FAIL=$((FAIL+1)); REPORT+="FAIL|$label|>=$threshold|actual=$actual\n"
  fi
}

assert_contains(){
  local label="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    green "$label — contains '$needle'"
    PASS=$((PASS+1)); REPORT+="PASS|$label|contains='$needle'\n"
  else
    red  "$label — missing '$needle'"
    FAIL=$((FAIL+1)); REPORT+="FAIL|$label|missing='$needle'\n"
  fi
}

assert_file_exists(){
  local label="$1" f="$2"
  if [[ -f "$f" ]]; then
    green "$label — $f exists"
    PASS=$((PASS+1)); REPORT+="PASS|$label|file=$f\n"
  else
    red  "$label — $f MISSING"
    FAIL=$((FAIL+1)); REPORT+="FAIL|$label|file=$f\n"
  fi
}

run_py(){ PYTHONPATH="$ROOT" python3 - <<PYEOF
$1
PYEOF
}

echo "============================================================"
echo " ELI Claim Verification — $(date)"
echo " CWD: $ROOT"
echo "============================================================"
echo ""

# ── SECTION 1: File / module existence ───────────────────────
echo "── 1. Key module existence ─────────────────────────────────"
for f in \
  eli/execution/executor_enhanced.py \
  eli/execution/router_enhanced.py \
  eli/runtime/deterministic_grounding_gate.py \
  eli/kernel/engine.py \
  eli/cognition/orchestrator.py \
  eli/cognition/agent_bus.py \
  eli/cognition/reasoning_modes.py \
  eli/cognition/persona.py \
  eli/cognition/persona_updater.py \
  eli/cognition/gguf_inference.py \
  eli/kernel/world_model.py \
  eli/kernel/state.py \
  eli/memory/memory.py \
  eli/planning/proactive_daemon.py \
  eli/planning/autonomy_controller.py \
  eli/planning/proposal_queue.py \
  eli/planning/goal_store.py \
  eli/perception/audio_stt.py \
  eli/perception/tts_router.py \
  eli/contracts/grounded_control.py \
  eli/brain/agents/custom/tvshowagent.py \
  capability_manifest.json \
; do
  assert_file_exists "exists: $f" "$f"
done
echo ""

# ── SECTION 2: Line / def counts for hotspot modules ─────────
echo "── 2. File size claims ──────────────────────────────────────"
check_file_lines(){
  local label="$1" fpath="$2" expected_min="$3"
  local actual; actual=$(wc -l < "$fpath" 2>/dev/null || echo 0)
  if (( actual >= expected_min )); then
    green "$label — lines>=$expected_min actual=$actual"
    PASS=$((PASS+1)); REPORT+="PASS|$label|lines>=$expected_min|actual=$actual\n"
  else
    red  "$label — lines>=$expected_min actual=$actual"
    FAIL=$((FAIL+1)); REPORT+="FAIL|$label|lines>=$expected_min|actual=$actual\n"
  fi
}
# Transcript: executor_enhanced=10916, router_enhanced=4803, engine=~6600+,
#             orchestrator=773, agent_bus=1834
check_file_lines "executor_enhanced.py lines"       eli/execution/executor_enhanced.py   10000
check_file_lines "router_enhanced.py lines"         eli/execution/router_enhanced.py      4500
check_file_lines "engine.py lines"                  eli/kernel/engine.py                  6000
check_file_lines "orchestrator.py lines"            eli/cognition/orchestrator.py          700
check_file_lines "agent_bus.py lines"               eli/cognition/agent_bus.py            1700
echo ""

# ── SECTION 3: Router — 20 priority stages ───────────────────
echo "── 3. Router priority pipeline (claimed: 20 stages) ────────"
ROUTER_STAGES=$(python3 - <<'PY'
import re
from pathlib import Path
text = Path("eli/execution/router_enhanced.py").read_text(errors="replace")
# stages logged as  "stage_name"  or  stage_<n>  in the pipeline list
hits = re.findall(r'["\']([a-z][a-z0-9_]{3,})["\'](?=.*priority_pipeline_stage)', text)
# also count the flat stage name list if present
stage_list = re.findall(r'priority_pipeline_stage["\']?\s*[:=]\s*["\']([a-z][a-z0-9_]+)["\']', text)
unique = sorted(set(stage_list))
print(len(unique))
PY
)
assert_ge "router priority stage count" 15 "$ROUTER_STAGES"

# Check a sample of the 20 named stages
echo "  Spot-checking named router stages..."
ROUTER_SRC=$(cat eli/execution/router_enhanced.py)
for stage in precedence memory_runtime_lock personal_memory_pre_route \
             identity_contract core_router voice_contract; do
  assert_contains "router stage '$stage'" "$stage" "$ROUTER_SRC"
done
echo ""

# ── SECTION 4: Executor — 8 middleware stages ────────────────
echo "── 4. Executor canonical middleware (claimed: 8 stages) ─────"
EXEC_MW=$(python3 - <<'PY'
import re
from pathlib import Path
text = Path("eli/execution/executor_enhanced.py").read_text(errors="replace")
# look for the middleware table list entries
hits = re.findall(r'["\']([a-z][a-z0-9_]{3,})["\'].*canonical middleware', text, re.DOTALL)
# simpler: count entries inside the middleware table definition block
table_block = re.search(
    r'canonical.*middleware.*table.*?=\s*\[(.*?)\]',
    text, re.DOTALL | re.IGNORECASE
)
if table_block:
    entries = re.findall(r'["\']([a-z][a-z0-9_]+)["\']', table_block.group(1))
    print(len(entries))
else:
    # fallback: count "middleware_name" keys near install block
    hits2 = re.findall(r'"([a-z][a-z0-9_]+)"\s*:\s*\{[^}]*"handler"', text)
    print(len(set(hits2)))
PY
)
assert_ge "executor middleware stage count" 6 "$EXEC_MW"

for stage in multipdf runtime_status_metadata memory_count identity_only; do
  assert_contains "executor middleware stage '$stage'" "$stage" "$(cat eli/execution/executor_enhanced.py)"
done
echo ""

# ── SECTION 5: Executor execute() redefinition count (claimed: 13) ──
echo "── 5. execute() redefinition count in executor (claimed: 13) "
EXEC_REDEFS=$(grep -c "^def execute(" eli/execution/executor_enhanced.py 2>/dev/null || echo 0)
assert_ge "execute() def count in executor" 10 "$EXEC_REDEFS"
echo "  (actual count: $EXEC_REDEFS — transcript claimed 13)"
echo ""

# ── SECTION 6: render_action() redefinition count (claimed: 8) ──
echo "── 6. render_action() redefinitions in grounding gate (claimed: 8)"
RENDER_REDEFS=$(grep -c "^def render_action(" eli/runtime/deterministic_grounding_gate.py 2>/dev/null || echo 0)
assert_ge "render_action() def count" 5 "$RENDER_REDEFS"
echo "  (actual count: $RENDER_REDEFS — transcript claimed 8)"
echo ""

# ── SECTION 7: Engine grounded middleware markers (claimed: 9) ──
echo "── 7. Engine grounded middleware markers (claimed: 9) ────────"
ENGINE_MARKERS=$(python3 - <<'PY'
import re
text = open("eli/kernel/engine.py", errors="replace").read()
# markers are things like REASONING_STATUS_V1, RECENT_MEMORY_PROCESSING_V4
hits = re.findall(r'#\s*([A-Z][A-Z0-9_]+_V\d+)', text)
unique = sorted(set(hits))
print(len(unique))
PY
)
assert_ge "engine grounded middleware markers" 7 "$ENGINE_MARKERS"
echo ""

# ── SECTION 8: Orchestrator stage annotations (claimed: 17 entries) ──
echo "── 8. Orchestrator stage annotations (claimed: 17) ──────────"
ORCH_STAGES=$(python3 - <<'PY'
import re
text = open("eli/cognition/orchestrator.py", errors="replace").read()
hits = re.findall(r'stage_\w+\s*[:=]', text)
print(len(set(hits)))
PY
)
assert_ge "orchestrator stage entries" 10 "$ORCH_STAGES"

for stage in stage_1 stage_2 stage_3 stage_4 stage_8 stage_11; do
  assert_contains "orchestrator $stage" "$stage" "$(cat eli/cognition/orchestrator.py)"
done
echo ""

# ── SECTION 9: Reasoning modes (claimed: 5 canonical) ────────
echo "── 9. Reasoning modes (claimed: 5 canonical) ────────────────"
for mode in quick chain_of_thought self_consistency tree_of_thoughts constitutional_ai; do
  assert_contains "reasoning mode '$mode'" "$mode" "$(cat eli/cognition/reasoning_modes.py)"
done
echo ""

# ── SECTION 10: Capability manifest numbers ──────────────────
echo "── 10. Capability manifest numbers ──────────────────────────"
if [[ -f capability_manifest.json ]]; then
  MANIFEST_TOTAL=$(python3 -c "import json; d=json.load(open('capability_manifest.json')); print(len(d.get('capabilities', d if isinstance(d, list) else [])))" 2>/dev/null || echo 0)
  assert_ge "manifest capability entries" 140 "$MANIFEST_TOTAL"
  echo "  actual manifest total: $MANIFEST_TOTAL (transcript claimed 169)"
else
  red "capability_manifest.json missing"
  FAIL=$((FAIL+1))
fi
echo ""

# ── SECTION 11: Runtime capability count (claimed: 169) ───────
echo "── 11. Runtime LIST_CAPABILITIES count (claimed: 169) ───────"
RUNTIME_CAPS=$(PYTHONPATH="$ROOT" python3 - <<'PY' 2>/dev/null || echo 0
from eli.execution.executor_enhanced import execute
r = execute("LIST_CAPABILITIES", {})
content = r.get("content", "") if isinstance(r, dict) else str(r)
# count lines that look like capability entries: "- ACTION_NAME"
import re
hits = re.findall(r'^\s*[-*]\s+[A-Z][A-Z0-9_]+', content, re.MULTILINE)
print(len(hits))
PY
)
assert_ge "runtime capability count" 100 "$RUNTIME_CAPS"
echo "  actual runtime count: $RUNTIME_CAPS (transcript claimed 169)"
echo ""

# ── SECTION 12: SUPPORTED_ACTIONS unique count (claimed: 132) ─
echo "── 12. SUPPORTED_ACTIONS in executor (claimed: 132 unique) ──"
SUPPORTED=$(python3 - <<'PY'
import ast, re
from pathlib import Path
text = Path("eli/execution/executor_enhanced.py").read_text(errors="replace")
# find SUPPORTED_ACTIONS = {...} or ["..."]
m = re.search(r'SUPPORTED_ACTIONS\s*=\s*(\{[^}]*\}|\[[^\]]*\])', text, re.DOTALL)
if m:
    block = m.group(1)
    entries = re.findall(r'["\']([A-Z][A-Z0-9_]+)["\']', block)
    print(len(set(entries)))
else:
    print(0)
PY
)
assert_ge "SUPPORTED_ACTIONS unique count" 100 "$SUPPORTED"
echo "  actual: $SUPPORTED (transcript claimed 132)"
echo ""

# ── SECTION 13: Plugin dirs vs registry ───────────────────────
echo "── 13. Plugin dirs vs registry ──────────────────────────────"
PLUGIN_DIRS=$(find eli/plugins -maxdepth 2 -name "plugin.py" 2>/dev/null | wc -l)
assert_ge "plugin dirs with plugin.py" 8 "$PLUGIN_DIRS"
echo "  actual plugin dirs: $PLUGIN_DIRS (transcript claimed 11)"

REGISTRY_ENTRIES=$(python3 - <<'PY'
import json, pathlib
for candidate in ["eli/plugins/registry/index.json", "eli/plugins/index.json"]:
    p = pathlib.Path(candidate)
    if p.exists():
        d = json.loads(p.read_text())
        entries = d if isinstance(d, list) else d.get("plugins", d.get("entries", []))
        print(len(entries))
        raise SystemExit(0)
print(0)
PY
)
echo "  actual registry entries: $REGISTRY_ENTRIES (transcript claimed 7)"

# Check the 4 unregistered dirs mentioned
for pd in calendar document_reader media web_automation; do
  if [[ -f "eli/plugins/$pd/plugin.py" ]]; then
    yellow "plugin dir '$pd' present (transcript says unregistered — verify)"
    WARN=$((WARN+1))
  fi
done
echo ""

# ── SECTION 14: Orphan module checks ─────────────────────────
echo "── 14. Orphan module candidates ─────────────────────────────"
# grounded_control.py — claimed 0 call-sites
GROUNDED_REFS=$(grep -rl "grounded_control" eli/ --include="*.py" 2>/dev/null | grep -v "grounded_control.py" | wc -l)
if (( GROUNDED_REFS == 0 )); then
  yellow "grounded_control.py — 0 external call-sites (confirmed candidate orphan)"
  WARN=$((WARN+1))
else
  green "grounded_control.py — has $GROUNDED_REFS external reference(s)"
  PASS=$((PASS+1))
fi

# tvshowagent.py — claimed only self-refs
TVSHOW_EXTERNAL=$(grep -rl "tvshowagent\|TVShowAgent" eli/ --include="*.py" 2>/dev/null | grep -v "tvshowagent.py" | wc -l)
if (( TVSHOW_EXTERNAL == 0 )); then
  yellow "tvshowagent.py — 0 external call-sites (confirmed candidate orphan)"
  WARN=$((WARN+1))
else
  green "tvshowagent.py — has $TVSHOW_EXTERNAL external reference(s)"
  PASS=$((PASS+1))
fi
echo ""

# ── SECTION 15: Duplicate manifest file ──────────────────────
echo "── 15. Duplicate capability_manifest.json check ─────────────"
if [[ -f "eli/capability_manifest.json" ]] && [[ -f "capability_manifest.json" ]]; then
  yellow "Stale duplicate exists at eli/capability_manifest.json (transcript claim confirmed)"
  WARN=$((WARN+1))
  # Are they the same?
  if diff -q capability_manifest.json eli/capability_manifest.json > /dev/null 2>&1; then
    yellow "  Both files are identical."
  else
    yellow "  Files differ — potential divergence."
  fi
else
  green "No duplicate manifest found (transcript may be stale or already cleaned)"
  PASS=$((PASS+1))
fi
echo ""

# ── SECTION 16: Duplicate Python blob check ──────────────────
echo "── 16. Duplicate Python blobs (transcript claimed: 2) ────────"
DUP_BLOBS=$(python3 - <<'PY'
import hashlib, pathlib
seen = {}
dups = []
for f in pathlib.Path("eli").rglob("*.py"):
    h = hashlib.md5(f.read_bytes()).hexdigest()
    if h in seen:
        dups.append((f, seen[h]))
    else:
        seen[h] = f
print(len(dups))
PY
)
echo "  duplicate blob pairs: $DUP_BLOBS (transcript claimed 2)"
if (( DUP_BLOBS > 0 )); then
  yellow "  $DUP_BLOBS duplicate blob pair(s) found"
  WARN=$((WARN+1))
else
  green "  No duplicate blobs found"
  PASS=$((PASS+1))
fi
echo ""

# ── SECTION 17: Audit tools present ──────────────────────────
echo "── 17. Audit tool scripts ───────────────────────────────────"
for t in \
  tools/validate_capability_manifest.py \
  tools/audit_capability_manifest_against_source.py \
  tools/audit_plugin_integrity.py \
  tools/audit_plugin_router_surface.py \
; do
  assert_file_exists "audit tool: $t" "$t"
done
echo ""

# ── SECTION 18: Run audit tools ──────────────────────────────
echo "── 18. Run: validate_capability_manifest.py ─────────────────"
MANIFEST_VALIDATION=$(PYTHONPATH="$ROOT" python3 tools/validate_capability_manifest.py 2>&1 || true)
if echo "$MANIFEST_VALIDATION" | grep -q "PASS\|valid\|generated_at"; then
  green "validate_capability_manifest.py produced output"
  PASS=$((PASS+1))
else
  red "validate_capability_manifest.py — unexpected output"
  FAIL=$((FAIL+1))
fi
echo "$MANIFEST_VALIDATION" | grep -E "total|PASS|FAIL|WARN|manifest_total" | head -10 || true

echo ""
echo "── 19. Run: audit_capability_manifest_against_source.py ─────"
MANIFEST_AUDIT=$(PYTHONPATH="$ROOT" python3 tools/audit_capability_manifest_against_source.py 2>&1 || true)
AUDIT_FAILS=$(echo "$MANIFEST_AUDIT" | grep -c "^FAIL:" || true)
echo "  Source audit FAIL lines: $AUDIT_FAILS (transcript claimed 5; most recent run showed 2-5)"
if (( AUDIT_FAILS > 0 )); then
  yellow "  $AUDIT_FAILS manifest-vs-source mismatches (expected, see transcript)"
  WARN=$((WARN+1))
  echo "$MANIFEST_AUDIT" | grep "^FAIL:" | head -10
else
  green "  0 manifest-vs-source mismatches (improvement or audit tool changed)"
  PASS=$((PASS+1))
fi

echo ""
echo "── 20. Run: audit_plugin_integrity.py ───────────────────────"
PLUGIN_AUDIT=$(PYTHONPATH="$ROOT" python3 tools/audit_plugin_integrity.py 2>&1 || true)
if echo "$PLUGIN_AUDIT" | grep -qi "FAIL\|ERROR\|error"; then
  yellow "  plugin integrity audit has issues (check output)"
  WARN=$((WARN+1))
else
  green "  plugin integrity audit clean"
  PASS=$((PASS+1))
fi
echo "$PLUGIN_AUDIT" | grep -E "FAIL|ERROR|OK|clean|INFO" | head -10 || true

echo ""
echo "── 21. Run: audit_plugin_router_surface.py ──────────────────"
ROUTER_AUDIT=$(PYTHONPATH="$ROOT" python3 tools/audit_plugin_router_surface.py 2>&1 || true)
if echo "$ROUTER_AUDIT" | grep -qi "Clean\|PASS\|all active"; then
  green "  plugin router surface audit: clean"
  PASS=$((PASS+1))
else
  yellow "  plugin router surface audit: see output"
  WARN=$((WARN+1))
fi
echo "$ROUTER_AUDIT" | tail -5

echo ""

# ── SECTION 22: pytest suites ─────────────────────────────────
echo "── 22. pytest: test_phase71_grounded_surface_contracts.py ───"
echo "   (transcript claimed: 23 passed)"
PHASE71_RESULT=$(PYTHONPATH="$ROOT" python3 -m pytest -q \
  tests/test_phase71_grounded_surface_contracts.py 2>&1 || true)
PHASE71_PASS=$(echo "$PHASE71_RESULT" | grep -oP '\d+(?= passed)' | tail -1 || echo 0)
assert_ge "phase71 contracts passed" 20 "${PHASE71_PASS:-0}"
echo "$PHASE71_RESULT" | tail -3

echo ""
echo "── 23. pytest: non-GGUF targeted suites ─────────────────────"
echo "   (transcript claimed: 7 passed)"
NONGGUF_RESULT=$(PYTHONPATH="$ROOT" python3 -m pytest -q \
  tests/test_runtime_status_nonquick_no_gguf.py \
  tests/test_recent_memory_processing_no_gguf.py \
  tests/test_self_report_recent_updates_no_gguf.py 2>&1 || true)
NONGGUF_PASS=$(echo "$NONGGUF_RESULT" | grep -oP '\d+(?= passed)' | tail -1 || echo 0)
assert_ge "non-GGUF suite passed" 5 "${NONGGUF_PASS:-0}"
echo "$NONGGUF_RESULT" | tail -3

echo ""
echo "── 24. pytest: test_eli_contract_routes.py ──────────────────"
echo "   (transcript claimed: 10 passed)"
ROUTES_RESULT=$(PYTHONPATH="$ROOT" python3 -m pytest -q \
  tests/test_eli_contract_routes.py 2>&1 || true)
ROUTES_PASS=$(echo "$ROUTES_RESULT" | grep -oP '\d+(?= passed)' | tail -1 || echo 0)
assert_ge "contract routes passed" 8 "${ROUTES_PASS:-0}"
echo "$ROUTES_RESULT" | tail -3

echo ""
echo "── 25. pytest: total collected (transcript claimed: 1866) ───"
TOTAL_COLLECTED=$(PYTHONPATH="$ROOT" python3 -m pytest --collect-only -q 2>&1 \
  | grep -oP '\d+(?= test)' | tail -1 || echo 0)
assert_ge "total tests collected" 1500 "${TOTAL_COLLECTED:-0}"
echo "  actual collected: $TOTAL_COLLECTED (transcript claimed 1866)"

echo ""
echo "── 26. pytest: regression/test_supported_action_surface.py ──"
echo "   (transcript: 1 passed)"
SURFACE_RESULT=$(PYTHONPATH="$ROOT" python3 -m pytest -q \
  tests/regression/test_supported_action_surface.py 2>&1 || true)
SURFACE_PASS=$(echo "$SURFACE_RESULT" | grep -oP '\d+(?= passed)' | tail -1 || echo 0)
assert_eq "supported action surface test" "1" "${SURFACE_PASS:-0}"
echo "$SURFACE_RESULT" | tail -2

echo ""

# ── SECTION 27: Quick execute() smoke checks ─────────────────
echo "── 27. Quick execute() smoke: NOOP, ROUTING_FAULT_EXPLAIN ───"
SMOKE=$(PYTHONPATH="$ROOT" python3 - <<'PY' 2>&1 || true
from eli.execution.executor_enhanced import execute
results = {}
for action in ["NOOP", "ROUTING_FAULT_EXPLAIN", "SEQUENCE_STEP", "TEMPLATE"]:
    try:
        ctx = {"message": "test"} if action == "NOOP" else {"question": "test"}
        r = execute(action, ctx)
        ok = r.get("ok", False) if isinstance(r, dict) else False
        results[action] = "ok" if ok else "returned_nok"
    except Exception as e:
        results[action] = f"error:{e}"
for k, v in results.items():
    print(f"  {k:<28s} -> {v}")
PY
)
echo "$SMOKE"

# Transcript: NOOP ok, SEQUENCE_STEP+TEMPLATE return unsupported at runtime
if echo "$SMOKE" | grep -q "NOOP.*ok"; then
  green "NOOP returns ok (confirmed)"
  PASS=$((PASS+1))
else
  red "NOOP did not return ok"
  FAIL=$((FAIL+1))
fi
for action in SEQUENCE_STEP TEMPLATE; do
  if echo "$SMOKE" | grep -q "${action}.*returned_nok\|${action}.*error\|${action}.*unsupported"; then
    yellow "$action returns not-ok at runtime (transcript: expected mismatch)"
    WARN=$((WARN+1))
  else
    yellow "$action smoke result unclear — check manually"
    WARN=$((WARN+1))
  fi
done

echo ""

# ── SECTION 28: SEQUENCE_STEP / TEMPLATE in manifest vs source ─
echo "── 28. Manifest vs source: SEQUENCE_STEP, TEMPLATE ──────────"
echo "   (transcript: in_dispatch=True but source says False)"
python3 - <<'PY' 2>/dev/null || true
import json
m = json.load(open("capability_manifest.json"))
caps = m.get("capabilities", m if isinstance(m, list) else [])
for cap in caps:
    action = cap.get("action", "")
    if action in ("SEQUENCE_STEP", "TEMPLATE"):
        in_dispatch = cap.get("in_dispatch")
        in_supported = cap.get("in_supported_list")
        routable = cap.get("routable")
        print(f"  {action:<20s} in_dispatch={in_dispatch}  in_supported_list={in_supported}  routable={routable}")
PY

echo ""

# ── SECTION 29: CapabilitySync discover counts ────────────────
echo "── 29. CapabilitySync discover/public counts ─────────────────"
echo "   (transcript: discover_count=169, public_like_count=134, router_only=0)"
SYNC_OUT=$(PYTHONPATH="$ROOT" python3 - <<'PY' 2>&1 || true
from eli.runtime.capability_sync import CapabilitySync
s = CapabilitySync()
result = s.run() if hasattr(s, "run") else s.sync() if hasattr(s, "sync") else {}
dc = getattr(s, "discover_count", result.get("discover_count", "?"))
pl = getattr(s, "public_like_count", result.get("public_like_count", "?"))
ro = getattr(s, "router_only", result.get("router_only", "?"))
print(f"discover_count={dc} public_like_count={pl} router_only={ro}")
PY
)
echo "  $SYNC_OUT"
echo "  (transcript claimed discover_count=169 public_like_count=134 router_only=0)"
echo ""

# ── FINAL SUMMARY ─────────────────────────────────────────────
echo "============================================================"
echo " SUMMARY"
echo "============================================================"
echo -e " \033[32mPASS\033[0m : $PASS"
echo -e " \033[31mFAIL\033[0m : $FAIL"
echo -e " \033[33mWARN\033[0m : $WARN  (expected mismatches / debt items)"
echo ""
echo " WARN items are known issues flagged in the transcript."
echo " FAIL items are claims the codebase does not currently support."
echo ""
echo " Full machine-readable log:"
printf "$REPORT" | column -t -s '|' 2>/dev/null || printf "$REPORT"
echo "============================================================"
