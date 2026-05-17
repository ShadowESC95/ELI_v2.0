#!/usr/bin/env bash
# ============================================================
# ELI Stage 11 + Reasoning Mode Diagnostic
# Targets:
#   1. WHY Stage 11 primary path yields zero visible tokens
#   2. WHERE the visibility filter / token stripping lives
#   3. WHETHER reasoning mode is being passed through to Stage 11
#   4. WHAT the broker path does vs the fallback path
#   5. PIPELINE stage trace per reasoning mode
# No modifications — read-only.
# ============================================================
ROOT="$(pwd)"
TMPPY=$(mktemp /tmp/eli_s11_diag_XXXXXX.py)

cat > "$TMPPY" << 'ENDPY'
import sys, re, logging
logging.disable(logging.CRITICAL)

def grep_context(path, pattern, context=6, label=""):
    try:
        lines = open(path, errors="replace").readlines()
    except Exception as e:
        print(f"  [READ ERROR] {path}: {e}")
        return
    hits = []
    for i, ln in enumerate(lines):
        if re.search(pattern, ln, re.IGNORECASE):
            start = max(0, i - context)
            end   = min(len(lines), i + context + 1)
            hits.append((i+1, lines[start:end], start+1))
    if not hits:
        print(f"  [NOT FOUND] pattern='{pattern}' in {path}")
        return
    print(f"  [{label or pattern}] {len(hits)} hit(s) in {path}")
    for lineno, block, block_start in hits[:3]:  # max 3 hits shown
        print(f"    --- hit at line {lineno} ---")
        for j, l in enumerate(block):
            marker = ">>>" if (block_start + j) == lineno else "   "
            print(f"    {marker} {block_start+j:5d}: {l}", end="")
        print()

ENGINE  = "eli/kernel/engine.py"
ORCH    = "eli/cognition/orchestrator.py"
GGUF    = "eli/cognition/gguf_inference.py"

# ── 1. WHY Stage 11 yields zero visible tokens ────────────────
print("=" * 70)
print("1. Stage 11 'yielded zero visible tokens' — surrounding code")
print("=" * 70)
grep_context(ENGINE,  r"yielded zero visible", context=10, label="S11_ZERO_TOKENS")
grep_context(ORCH,    r"yielded zero visible", context=10, label="S11_ZERO_TOKENS_ORCH")

print()
print("=" * 70)
print("2. Visibility filter — what strips tokens as 'not visible'")
print("=" * 70)
grep_context(ENGINE, r"visible|visibility|visible_token|stripped|strip_token", context=6, label="VISIBILITY")
grep_context(ORCH,   r"visible|visibility|visible_token|stripped|strip_token", context=6, label="VISIBILITY_ORCH")

print()
print("=" * 70)
print("3. Stage 11 primary path — how it generates / what it yields")
print("=" * 70)
grep_context(ENGINE, r"Stage 11 primary path|stage_11|_run_stage_11|primary.*path", context=12, label="S11_PRIMARY")
grep_context(ORCH,   r"Stage 11 primary path|stage_11|_run_stage_11|primary.*path", context=12, label="S11_PRIMARY_ORCH")

print()
print("=" * 70)
print("4. Direct GGUF fallback path — what triggers it, what it bypasses")
print("=" * 70)
grep_context(ENGINE, r"direct gguf fallback|fallback.*path|_fallback", context=10, label="FALLBACK")
grep_context(ORCH,   r"direct gguf fallback|fallback.*path|_fallback", context=10, label="FALLBACK_ORCH")

print()
print("=" * 70)
print("5. Broker path — how it differs from fallback")
print("=" * 70)
grep_context(ENGINE, r"Using broker path|broker.*path|_broker", context=10, label="BROKER")
grep_context(ORCH,   r"Using broker path|broker.*path|_broker", context=10, label="BROKER_ORCH")

print()
print("=" * 70)
print("6. Reasoning mode passed into Stage 11 / broker")
print("=" * 70)
grep_context(ENGINE, r"reasoning_mode.*stage|stage.*reasoning_mode|mode.*broker|broker.*mode", context=8, label="MODE_TO_S11")
grep_context(ORCH,   r"reasoning_mode.*stage|stage.*reasoning_mode|mode.*broker|broker.*mode", context=8, label="MODE_TO_S11_ORCH")

# Does Stage 11 primary path receive the reasoning mode at all?
grep_context(ENGINE, r"def.*stage_11|stage_11.*def|_stage11|stage11", context=8, label="S11_FUNC_DEF")
grep_context(ORCH,   r"def.*stage_11|stage_11.*def|_stage11|stage11", context=8, label="S11_FUNC_DEF_ORCH")

print()
print("=" * 70)
print("7. Quick-path short-circuit in non-quick modes")
print("=" * 70)
# The issue: constitutional mode returned a quick answer
grep_context(ENGINE, r"quick_direct|allow_chat_without_evidence|quick.*mode|mode.*quick", context=8, label="QUICK_BYPASS")
# Is there a guard that should prevent quick answers in non-quick modes?
grep_context(ENGINE, r"if.*quick|mode\s*==\s*['\"]quick|is_quick|quick_only", context=6, label="QUICK_GUARD")

print()
print("=" * 70)
print("8. Pipeline stage trace — what stages are skipped/run per mode")
print("=" * 70)
grep_context(ENGINE, r"skip.*stage|stage.*skip|stage.*bypass|bypass.*stage", context=6, label="STAGE_SKIP")
grep_context(ORCH,   r"skip.*stage|stage.*skip|stage.*bypass|bypass.*stage", context=6, label="STAGE_SKIP_ORCH")

print()
print("=" * 70)
print("9. Stream lifecycle — generator exhaustion / async issue candidates")
print("=" * 70)
grep_context(ENGINE, r"yield|generator|stream.*iter|iter.*stream|StopIteration|next\(", context=5, label="STREAM_LIFECYCLE")
# Is the stream being consumed before visible-token check?
grep_context(ENGINE, r"list\(.*stream\)|collect.*stream|exhaust.*stream|stream.*list\(", context=5, label="STREAM_CONSUMED")

print()
print("=" * 70)
print("10. Stop token / early-stop candidates")
print("=" * 70)
grep_context(ENGINE, r"stop_token|stop_str|early.stop|eos|end.of.stream", context=5, label="STOP_TOKEN")
grep_context(GGUF,   r"stop_token|stop_str|early.stop|eos", context=5, label="STOP_TOKEN_GGUF")

print()
print("=" * 70)
print("11. Recent patch markers — what changed")
print("=" * 70)
# Look for Phase markers near Stage 11 that might be recent patches
grep_context(ENGINE, r"Phase 1[2-9]|Phase 2[0-9]|Phase 3[0-9]|Phase 4[0-9]|Phase 5[0-9]|Phase 6[0-9]|Phase 7[0-9]", context=3, label="RECENT_PHASE_MARKERS")

print()
print("=" * 70)
print("12. MEMORY_STATUS / quick-return paths that bypass Stage 11")
print("=" * 70)
# Quick direct return paths in engine that bypass orchestration entirely
grep_context(ENGINE, r"return.*quick|quick.*return|direct_return|_direct_response", context=8, label="DIRECT_RETURN")
grep_context(ENGINE, r"quick_direct_allowed|quick_direct", context=8, label="QUICK_DIRECT_ALLOWED")

ENDPY

PYTHONPATH="$ROOT" python3 "$TMPPY" 2>/dev/null
rm -f "$TMPPY"
