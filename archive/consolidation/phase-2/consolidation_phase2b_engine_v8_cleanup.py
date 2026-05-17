#!/usr/bin/env python3
"""
Phase 2b: drop now-unconditional globals() guards from existing inline
middleware, delete the dead inline RUNTIME_STATUS_V8 middleware (replaced by
V19 in Phase 2a), and delete the V8 inert bottom block (no longer referenced).

Why this is minimal-risk:
- The 3 globals() guards we drop have always returned True at runtime, because
  the inert bottom blocks executing at module load define the helpers
  (`_eli_pm_engine_*`, `_eli_mc_*`, `_eli_recent_mem_v3_*`). Dropping the guard
  changes nothing observable; it just removes a defensive check the consolidated
  layout no longer needs.
- The V8 inline middleware (~115 lines) only fires for RUNTIME_STATUS questions.
  V19 (added in Phase 2a) detects the same questions and handles them with the
  correct synthesize-not-return-evidence semantics. V8 inline is dead code.
- The V8 inert bottom block (~365 lines) defines `_eli_v8_detect_runtime_status`
  and `_eli_v8_runtime_status_response`, which were ONLY referenced by V8
  inline. Removing both is safe.

Remaining inert blocks (REASONING_STATUS, PM, RECENT_MEM V1/V2/V3, SELF_REPORT,
MC V4/V5, V7) are left intact for now — they define helpers still referenced
by inline middleware via globals(). A future Phase 2c can relocate those
helpers to module level and delete the bodies.
"""
from __future__ import annotations

from pathlib import Path
import sys

p = Path(__file__).resolve().parents[3] / "eli" / "kernel" / "engine.py"
if not p.exists():
    print(f"ERROR: engine.py not found at {p}", file=sys.stderr)
    sys.exit(2)

src = p.read_text(encoding="utf-8")

SENTINEL_PHASE2B = "# === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8_DELETED_PHASE2B ==="
if SENTINEL_PHASE2B in src:
    print(f"already applied: sentinel '{SENTINEL_PHASE2B}' present; skipping.")
    sys.exit(0)


# ───────────────────────────────────────────────────────────────────────
# Step 1 — drop `"name" in globals()` guard from PERSONAL_MEMORY_QUICK_V1
# ───────────────────────────────────────────────────────────────────────
PM_GUARD_OLD = '''        # === ELI_ENGINE_MIDDLEWARE_PERSONAL_MEMORY_QUICK_V1 ===
        # Migrated from bottom-of-file _eli_pm_engine_process wrapper.
        # Quick mode keeps direct personal-memory/routing-fault surfaces.
        # Non-Quick falls through to the normal cognition/persona pipeline.
        try:
            if (
                "_eli_pm_engine_mode_key" in globals()
                and "_eli_pm_engine_wants_routing_fault" in globals()
                and "_eli_pm_engine_wants_personal_memory" in globals()
            ):
                _eli_pm_mw_raw = str(user_input or "")'''
PM_GUARD_NEW = '''        # === ELI_ENGINE_MIDDLEWARE_PERSONAL_MEMORY_QUICK_V1 ===
        # Migrated from bottom-of-file _eli_pm_engine_process wrapper.
        # Quick mode keeps direct personal-memory/routing-fault surfaces.
        # Non-Quick falls through to the normal cognition/persona pipeline.
        # (Helpers _eli_pm_engine_* are defined unconditionally below in the
        # legacy bottom block; the prior globals() guard was redundant.)
        try:
            if True:
                _eli_pm_mw_raw = str(user_input or "")'''
assert PM_GUARD_OLD in src, "PERSONAL_MEMORY_QUICK_V1 guard not found"
src = src.replace(PM_GUARD_OLD, PM_GUARD_NEW, 1)


# ───────────────────────────────────────────────────────────────────────
# Step 2 — drop `"name" in globals()` guard from MEMORY_COUNT_V5
# ───────────────────────────────────────────────────────────────────────
MC_GUARD_OLD = '''        # === ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_V5 ===
        # Migrated from bottom-of-file _eli_process_memory_count_depth_v5 wrapper.
        # Memory-count questions are deterministic SQLite/runtime facts.
        # This must preserve Quick vs non-Quick mode depth and must not call GGUF.
        try:
            if (
                "_eli_mc_is_memory_count_question_v4" in globals()
                and "_eli_mc_mode_v4" in globals()
                and "_eli_mc_payload_v5" in globals()
                and _eli_mc_is_memory_count_question_v4(user_input)
            ):'''
MC_GUARD_NEW = '''        # === ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_V5 ===
        # Migrated from bottom-of-file _eli_process_memory_count_depth_v5 wrapper.
        # Memory-count questions are deterministic SQLite/runtime facts.
        # This must preserve Quick vs non-Quick mode depth and must not call GGUF.
        # (Helpers _eli_mc_* are defined unconditionally below in the legacy
        # bottom block; the prior globals() guard was redundant.)
        try:
            if _eli_mc_is_memory_count_question_v4(user_input):'''
assert MC_GUARD_OLD in src, "MEMORY_COUNT_V5 guard not found"
src = src.replace(MC_GUARD_OLD, MC_GUARD_NEW, 1)


# ───────────────────────────────────────────────────────────────────────
# Step 3 — drop `"name" in globals()` guard from RECENT_MEMORY_PROCESSING_V4
# ───────────────────────────────────────────────────────────────────────
RM_GUARD_OLD = '''        # === ELI_ENGINE_MIDDLEWARE_RECENT_MEMORY_PROCESSING_V4 ===
        # Migrated from bottom-of-file _eli_recent_mem_process_v3 wrapper.
        # Recent-memory-processing questions are deterministic memory-runtime
        # evidence queries. They must not enter GGUF in any reasoning mode.
        try:
            if (
                "_eli_recent_mem_v3_is_prompt" in globals()
                and "_eli_recent_mem_v3_execute" in globals()
                and _eli_recent_mem_v3_is_prompt(user_input)
            ):'''
RM_GUARD_NEW = '''        # === ELI_ENGINE_MIDDLEWARE_RECENT_MEMORY_PROCESSING_V4 ===
        # Migrated from bottom-of-file _eli_recent_mem_process_v3 wrapper.
        # Recent-memory-processing questions are deterministic memory-runtime
        # evidence queries. They must not enter GGUF in any reasoning mode.
        # (Helpers _eli_recent_mem_v3_* are defined unconditionally below in the
        # legacy bottom block; the prior globals() guard was redundant.)
        try:
            if _eli_recent_mem_v3_is_prompt(user_input):'''
assert RM_GUARD_OLD in src, "RECENT_MEMORY_PROCESSING_V4 guard not found"
src = src.replace(RM_GUARD_OLD, RM_GUARD_NEW, 1)

# Patch follow-up: the V3 middleware uses `"_eli_recent_mem_v3_mode" in globals()` further
# inside the same block. Drop that too.
RM_INNER_GUARD_OLD = '''                if "_eli_recent_mem_v3_mode" in globals():
                    _eli_rm_mode = _eli_recent_mem_v3_mode((), _eli_rm_kwargs)
                else:
                    _eli_rm_mode = str(_eli_rm_kwargs.get("reasoning_mode") or "quick").lower()'''
RM_INNER_GUARD_NEW = '''                _eli_rm_mode = _eli_recent_mem_v3_mode((), _eli_rm_kwargs)'''
assert RM_INNER_GUARD_OLD in src, "RECENT_MEMORY inner mode guard not found"
src = src.replace(RM_INNER_GUARD_OLD, RM_INNER_GUARD_NEW, 1)


# ───────────────────────────────────────────────────────────────────────
# Step 4 — delete the inline RUNTIME_STATUS_V8 middleware in process()
# ───────────────────────────────────────────────────────────────────────
V8_MW_START = "        # === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8 ===\n"
V8_MW_END = "        # === END ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8 ==="
assert V8_MW_START in src, "V8 inline middleware start marker not found"
assert V8_MW_END in src, "V8 inline middleware end marker not found"

v8mw_i = src.index(V8_MW_START)
v8mw_j = src.index(V8_MW_END, v8mw_i) + len(V8_MW_END)
src = (
    src[:v8mw_i]
    + "        " + SENTINEL_PHASE2B + "\n"
    + "        # Replaced by ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1 (V19) above."
    + src[v8mw_j:]
)


# ───────────────────────────────────────────────────────────────────────
# Step 5 — delete the V8 inert bottom block (lines beginning "# ELI RUNTIME
# STATUS ALL-MODES EARLY INTERCEPT V8" through its except clause)
# ───────────────────────────────────────────────────────────────────────
V8_INERT_START = "# =============================================================================\n# ELI RUNTIME STATUS ALL-MODES EARLY INTERCEPT V8"
V8_INERT_END = (
    "except Exception as _eli_v8_e:\n"
    "    print(\"[ENGINE][WARN] runtime-status all-modes early intercept v8 failed:\", repr(_eli_v8_e))"
)
assert V8_INERT_START in src, "V8 inert block start not found"
assert V8_INERT_END in src, "V8 inert block end not found"
v8i_i = src.index(V8_INERT_START)
v8i_j = src.index(V8_INERT_END, v8i_i) + len(V8_INERT_END)
src = (
    src[:v8i_i]
    + "# V8 RUNTIME_STATUS all-modes intercept removed — replaced by V19 inline middleware"
    + src[v8i_j:]
)


# ───────────────────────────────────────────────────────────────────────
# Final sanity checks
# ───────────────────────────────────────────────────────────────────────
assert "_eli_v8_detect_runtime_status" not in src or src.count("_eli_v8_detect_runtime_status") == 0, (
    f"V8 detector still referenced after delete ({src.count('_eli_v8_detect_runtime_status')} hits)"
)
assert "_eli_v8_runtime_status_response" not in src or src.count("_eli_v8_runtime_status_response") == 0, (
    f"V8 response builder still referenced ({src.count('_eli_v8_runtime_status_response')} hits)"
)
assert SENTINEL_PHASE2B in src, "Phase 2b sentinel not inserted"
assert "in globals()" not in src.split("# === ELI_ENGINE_MIDDLEWARE_PERSONAL_MEMORY_QUICK_V1")[1].split("# === END ELI_ENGINE_MIDDLEWARE_PERSONAL_MEMORY_QUICK_V1")[0], (
    "PERSONAL_MEMORY guard still present"
)
assert "in globals()" not in src.split("# === ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_V5")[1].split("# === END ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_V5")[0], (
    "MEMORY_COUNT_V5 guard still present"
)
assert "in globals()" not in src.split("# === ELI_ENGINE_MIDDLEWARE_RECENT_MEMORY_PROCESSING_V4")[1].split("# === END ELI_ENGINE_MIDDLEWARE_RECENT_MEMORY_PROCESSING_V4")[0], (
    "RECENT_MEMORY_PROCESSING guard still present"
)

p.write_text(src, encoding="utf-8")
print("Phase 2b complete:")
print(f"  - 3 globals() guards dropped from inline middleware")
print(f"  - V8 inline middleware deleted")
print(f"  - V8 inert bottom block deleted")
print(f"  - file size: {len(src.splitlines())} lines")
