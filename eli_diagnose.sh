#!/usr/bin/env bash
# Diagnostic only — no modifications
ROOT="$(pwd)"
TMPPY=$(mktemp /tmp/eli_diag_XXXXXX.py)

cat > "$TMPPY" << 'ENDPY'
import sys, logging, re
logging.disable(logging.CRITICAL)

print("=" * 60)
print("DIAG S3: Router stage structure")
print("=" * 60)
try:
    text = open("eli/execution/router_enhanced.py", errors="replace").read()
    # Show lines containing known stage names to understand the pattern
    known = [
        "precedence","memory_runtime_lock","gui_actual_scan",
        "self_report_recent_updates","recent_memory","memory_count",
        "profile_scope_explicit","final_memory_contract",
        "runtime_or_name_contract","identity_name_source_contract",
        "runtime_cognition_failure_guard","self_improvement_guard",
        "personal_memory_pre_route","lrf_pre_route","portable_route",
        "voice_contract","persona_override","followup_passthrough",
        "identity_contract","core_router"
    ]
    found = []
    for stage in known:
        hits = [i+1 for i,ln in enumerate(text.splitlines()) if stage in ln]
        if hits:
            found.append(stage)
    print(f"  Known stage names present: {len(found)}/20")
    print(f"  Found: {found}")
    
    # Show what context 'precedence' appears in
    for line in text.splitlines():
        if 'precedence' in line:
            print(f"  PRECEDENCE CTX: {line[:120].strip()}")
            break
    # Show what context 'priority_pipeline_stage' appears in (if any)
    hits = [ln.strip()[:120] for ln in text.splitlines() 
            if 'priority_pipeline_stage' in ln]
    print(f"  priority_pipeline_stage occurrences: {len(hits)}")
    for h in hits[:3]:
        print(f"    {h}")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=" * 60)
print("DIAG S29: CapabilitySync introspection")
print("=" * 60)
try:
    from eli.runtime.capability_sync import CapabilitySync
    s = CapabilitySync()
    # Show all methods and attributes
    methods = [m for m in dir(s) if not m.startswith('__') and callable(getattr(s,m,None))]
    attrs   = [a for a in dir(s) if not a.startswith('__') and not callable(getattr(s,a,None))]
    print(f"  Methods: {methods}")
    print(f"  Attrs before any call: {attrs}")
    print(f"  Attr values: { {a: getattr(s,a) for a in attrs} }")
    
    # Try each method and check for count attrs after
    for method in methods:
        try:
            result = getattr(s, method)()
            dc = getattr(s, "discover_count", None)
            pl = getattr(s, "public_like_count", None)
            ro = getattr(s, "router_only", None)
            print(f"  After {method}(): discover_count={dc} public_like_count={pl} router_only={ro} result={str(result)[:80]}")
            if dc is not None:
                break
        except Exception as e:
            print(f"  {method}() -> error: {e}")
except Exception as e:
    print(f"  CapabilitySync error: {e}")
ENDPY

PYTHONPATH="$ROOT" python3 "$TMPPY" 2>/dev/null
rm -f "$TMPPY"
