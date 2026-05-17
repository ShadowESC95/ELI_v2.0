#!/usr/bin/env python3
"""
Phase 2c: relocate the remaining legacy helpers used by inline middleware to
module-level above class CognitiveEngine, then delete the inert bottom blocks
that previously hosted them.

Relocated helpers (13 total):
  Personal-memory family (used by PERSONAL_MEMORY_QUICK_V1 inline middleware):
    _eli_pm_engine_wants_raw_memory_truth
    _eli_pm_engine_wants_personal_memory
    _eli_pm_engine_wants_routing_fault
    _eli_pm_engine_mode_key
  Recent-memory-processing v3 family (used by RECENT_MEMORY_PROCESSING_V4 middleware):
    _eli_recent_mem_v3_is_prompt
    _eli_recent_mem_v3_mode
    _eli_recent_mem_v3_execute
  Memory-count v4/v5 family (used by MEMORY_COUNT_V5 inline middleware):
    _eli_mc_project_root_v4
    _eli_mc_table_count_v4   (internal helper for _eli_mc_counts_v4)
    _eli_mc_faiss_count_v4   (internal helper for _eli_mc_counts_v4)
    _eli_mc_counts_v4
    _eli_mc_is_memory_count_question_v4
    _eli_mc_mode_v4
    _eli_mc_content_v5
    _eli_mc_payload_v5

Deleted inert bottom blocks (~1500 lines):
  REASONING_STATUS body, PERSONAL_MEMORY body, UVRS retired stub, GMC V1
  validator, RECENT_MEM V1/V2/V3 wrappers, SELF_REPORT validator, MC V4 +
  V5 wrappers, V7 RS wrapper. Each was marked "Migrated into ... no
  import-time reassignment" or "Superseded by ..." in Phase 2a/2b.

Kept:
  ELI NON-QUICK PERSONA PIPELINE SAFETY GUARD block. This is config
  mutation (_PHASE45_DIRECT_FAST_ACTIONS), not a wrapper.
"""
from __future__ import annotations

from pathlib import Path
import sys

p = Path(__file__).resolve().parents[3] / "eli" / "kernel" / "engine.py"
src = p.read_text(encoding="utf-8")

SENTINEL = "# === ELI_ENGINE_PHASE2C_HELPERS_SECTION_V1 ==="
if SENTINEL in src:
    print(f"already applied: '{SENTINEL}' present; skipping.")
    sys.exit(0)


# ───────────────────────────────────────────────────────────────────────
# Step 1 — insert relocated helpers above class CognitiveEngine, right
# after the existing Phase 2a "ENGINE MIDDLEWARE HELPERS" section.
# ───────────────────────────────────────────────────────────────────────
ANCHOR_OLD = "class CognitiveEngine:\n    def __init__(self):"
ANCHOR_NEW = '''# === ELI_ENGINE_PHASE2C_HELPERS_SECTION_V1 ===
# Helpers relocated from the legacy bottom-of-file wrapper blocks
# (Phase 2c). Defined unconditionally at module level so the inline
# middleware inside CognitiveEngine.process() never needs globals()
# guards. Names preserved verbatim from the original wrapper bodies so
# any external reference remains valid.

# -- Personal-memory routing helpers (used by PERSONAL_MEMORY_QUICK_V1) -

def _eli_pm_engine_wants_raw_memory_truth(low):
    import re as _re
    return bool(_re.search(
        r"\\b(memory truth report|memory count|how many memories|memory status|memory runtime status|raw counts?|db counts?|diagnostic counts?)\\b",
        low,
    ))


def _eli_pm_engine_wants_personal_memory(low):
    import re as _re
    if _eli_pm_engine_wants_raw_memory_truth(low):
        return False
    has_memory = bool(_re.search(
        r"\\b(memory|remember|stored memories|what do you know about me|what you know about me|actual(?:ly)? remember)\\b",
        low,
    ))
    has_depth = bool(_re.search(
        r"\\b(full|in[- ]?depth|personalised|personalized|properly|not quick|not in quick mode|"
        r"stop giving me data dumps|data dumps|what you actually remember|about me|which files|db tables|functions|internally|cognition pipeline)\\b",
        low,
    ))
    return has_memory and has_depth


def _eli_pm_engine_wants_routing_fault(low):
    import re as _re
    return bool(
        _re.search(r"\\bwhy\\b.*\\b(browser|web|online|search)\\b", low)
        or _re.search(r"\\bwhy.*go.*browser\\b", low)
    )


def _eli_pm_engine_mode_key(self, pargs, kwargs):
    mode = kwargs.get("reasoning_mode")
    if mode is None and len(pargs) >= 3:
        mode = pargs[2]
    if mode is None:
        mode = getattr(self, "reasoning_mode", None) or getattr(self, "_reasoning_mode", None)
    if mode is None:
        try:
            from eli.runtime.reasoning_status import current_reasoning_mode_label
            mode = current_reasoning_mode_label(self)
        except Exception:
            mode = "quick"
    try:
        from eli.cognition.reasoning_modes import canonical_mode
        return canonical_mode(mode)
    except Exception:
        low_mode = str(mode or "quick").strip().lower().replace(" ", "_")
        return low_mode or "quick"


# -- Recent-memory-processing v3 helpers (used by RECENT_MEMORY_PROCESSING_V4) --

def _eli_recent_mem_v3_is_prompt(text):
    import re as _re
    low = str(text or "").strip().lower()
    if not low:
        return False
    patterns = (
        r"\\bwhat\\s+memories\\s+have\\s+you\\s+been\\s+processing\\b",
        r"\\bwhat\\s+have\\s+you\\s+been\\s+remembering\\b",
        r"\\bwhat\\s+memory\\s+activity\\b",
        r"\\bshow\\s+recent\\s+memory\\s+activity\\b",
        r"\\brecent\\s+memory\\s+processing\\b",
        r"\\bmemories\\b.{0,80}\\b(processing|processed|lately|recent|recently|activity)\\b",
        r"\\b(remembering|memory)\\b.{0,80}\\b(lately|recent|recently|processing|activity)\\b",
    )
    return any(_re.search(pat, low) for pat in patterns)


def _eli_recent_mem_v3_mode(args, kwargs):
    try:
        if "reasoning_mode" in kwargs:
            return str(kwargs.get("reasoning_mode") or "quick").strip().lower()
        if args:
            return str(args[0] or "quick").strip().lower()
    except Exception:
        pass
    return "quick"


def _eli_recent_mem_v3_execute(user_input):
    from eli.execution.executor_enhanced import execute as _eli_execute
    out = _eli_execute(
        "MEMORY_STATUS",
        {"question": str(user_input or ""), "memory_scope": "recent_processing"},
    )
    if isinstance(out, dict):
        out = dict(out)
        out.setdefault("action", "MEMORY_STATUS")
    return out


# -- Memory-count v4/v5 helpers (used by MEMORY_COUNT_V5 inline middleware) ---

def _eli_mc_project_root_v4():
    from pathlib import Path as _Path
    try:
        return _Path(__file__).resolve().parents[2]
    except Exception:
        return _Path.cwd()


def _eli_mc_table_count_v4(conn, table):
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not row:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    except Exception:
        return 0


def _eli_mc_faiss_count_v4(root):
    index_path = root / "artifacts" / "vectors" / "index.faiss"
    if not index_path.exists():
        return 0
    try:
        import faiss  # type: ignore
        return int(faiss.read_index(str(index_path)).ntotal)
    except Exception:
        return 0


def _eli_mc_counts_v4():
    import sqlite3 as _sqlite3
    root = _eli_mc_project_root_v4()
    db_path = root / "artifacts" / "db" / "user.sqlite3"
    counts = {
        "long_term_memory_rows": 0,
        "memory_fts_rows": 0,
        "faiss_vector_entries": _eli_mc_faiss_count_v4(root),
        "conversation_turns": 0,
        "conversation_records": 0,
        "learning_replay_rows": 0,
        "observations": 0,
        "user_patterns": 0,
        "recall_log_rows": 0,
    }
    if db_path.exists():
        try:
            with _sqlite3.connect(str(db_path)) as conn:
                counts["long_term_memory_rows"] = _eli_mc_table_count_v4(conn, "memories")
                counts["memory_fts_rows"] = _eli_mc_table_count_v4(conn, "memories_fts")
                counts["conversation_turns"] = _eli_mc_table_count_v4(conn, "conversation_turns")
                counts["conversation_records"] = _eli_mc_table_count_v4(conn, "conversations")
                counts["learning_replay_rows"] = _eli_mc_table_count_v4(conn, "learning_replay")
                counts["observations"] = _eli_mc_table_count_v4(conn, "observations")
                counts["user_patterns"] = _eli_mc_table_count_v4(conn, "user_patterns")
                counts["recall_log_rows"] = _eli_mc_table_count_v4(conn, "recall_log")
        except Exception:
            pass
    return str(db_path), counts


def _eli_mc_is_memory_count_question_v4(text):
    q = str(text or "").strip().lower()
    if not q:
        return False
    has_memory = "memory" in q or "memories" in q
    asks_count = (
        "how many" in q
        or "number of" in q
        or "count" in q
        or "total" in q
    )
    if not (has_memory and asks_count):
        return False
    broader = (
        "what memories" in q
        or "which memories" in q
        or "show memories" in q
        or "recent memor" in q
        or "processing lately" in q
        or "remembering recently" in q
    )
    return not broader


def _eli_mc_mode_v4(args, kwargs):
    mode = kwargs.get("reasoning_mode")
    if mode is None and args:
        try:
            if isinstance(args[0], str):
                mode = args[0]
        except Exception:
            pass
    return str(mode or "quick").strip().lower()


def _eli_mc_content_v5(counts, *, include_related):
    main = counts.get("long_term_memory_rows", 0)
    if not include_related:
        return f"I have {main} long-term memory rows."
    return (
        f"I have {main} long-term memory rows.\\n\\n"
        "Grounded supporting counts:\\n"
        f"- FTS memory rows: {counts.get('memory_fts_rows', 0)}\\n"
        f"- FAISS vector entries: {counts.get('faiss_vector_entries', 0)}\\n"
        f"- conversation turns: {counts.get('conversation_turns', 0)}\\n"
        f"- conversation records: {counts.get('conversation_records', 0)}\\n"
        f"- learning replay rows: {counts.get('learning_replay_rows', 0)}\\n"
        f"- observations: {counts.get('observations', 0)}\\n"
        f"- user patterns: {counts.get('user_patterns', 0)}\\n"
        f"- recall log rows: {counts.get('recall_log_rows', 0)}"
    )


def _eli_mc_payload_v5(question, mode):
    db_path, counts = _eli_mc_counts_v4()
    quick = mode == "quick"
    content = _eli_mc_content_v5(counts, include_related=not quick)
    if quick:
        source = "memory_count_quick_concise_validated_v5"
        validated = None
        synthesis_kind = "quick_concise_deterministic"
    else:
        source = "memory_count_grounded_synthesis_validated_v5"
        validated = True
        synthesis_kind = "deterministic_grounded_synthesis"
    return {
        "ok": True,
        "action": "MEMORY_STATUS",
        "content": content,
        "response": content,
        "evidence_source": source,
        "report": {
            "ok": True,
            "question": str(question or ""),
            "memory_scope": "count_only",
            "db_path": db_path,
            "counts": counts,
            "synthesis_kind": synthesis_kind,
            "synthesis_validated": validated,
            "gguf_used": False,
            "answer_contract": (
                "Quick mode returns only long_term_memory_rows. "
                "Non-quick modes may include related grounded store counts. "
                "No GGUF is required for this deterministic SQLite/runtime fact."
            ),
        },
    }


# === END ELI_ENGINE_PHASE2C_HELPERS_SECTION_V1 ===


class CognitiveEngine:
    def __init__(self):'''

assert ANCHOR_OLD in src, "anchor 'class CognitiveEngine:' not found"
src = src.replace(ANCHOR_OLD, ANCHOR_NEW, 1)


# ───────────────────────────────────────────────────────────────────────
# Step 2 — delete inert bottom blocks.
# Each block has a stable header comment plus an `except` clause that
# matches a distinct variable name. We slice from header to except (incl.)
# ───────────────────────────────────────────────────────────────────────
BLOCKS_TO_DELETE = [
    # name, start anchor (unique marker line, possibly multi-line), end anchor (inclusive of except line)
    (
        "REASONING_STATUS body",
        "# ELI_ENGINE_REASONING_TERMINAL_SECOND_FIX_20260505",
        "except Exception as _eli_engine_second_patch_error:\n"
        "    print(f\"[ELI_ENGINE_REASONING_TERMINAL_SECOND_FIX] failed: {_eli_engine_second_patch_error}\", flush=True)",
    ),
    (
        "PERSONAL_MEMORY body",
        "# ELI_PERSONAL_MEMORY_MODE_AWARE_ENGINE_FIX_20260505",
        "except Exception as _eli_pm_engine_patch_error:\n"
        "    print(f\"[ELI_PERSONAL_MEMORY_MODE_AWARE_ENGINE_FIX] failed: {_eli_pm_engine_patch_error}\", flush=True)",
    ),
    (
        "UVRS retired stub",
        "# =============================================================================\n"
        "# ELI USER-VISIBLE RESPONSE SURFACE",
        "except Exception as _eli_uvrs_err:\n"
        "    print(f\"[ENGINE] user-visible response surface install failed: {_eli_uvrs_err}\", flush=True)",
    ),
    (
        "GMC V1 validator",
        "# =============================================================================\n"
        "# ELI GROUNDED MEMORY COUNT SYNTHESIS VALIDATOR",
        "except Exception as _err:\n"
        "    print(f\"[ENGINE] grounded memory-count synthesis validator failed: {_err}\", flush=True)",
    ),
    (
        "RECENT_MEM V1",
        "# =============================================================================\n"
        "# ELI RECENT MEMORY PROCESSING SYNTHESIS VALIDATOR",
        "except Exception as _eli_recent_memory_engine_err:\n"
        "    print(f\"[ENGINE] recent-memory-processing validator install failed: {_eli_recent_memory_engine_err}\", flush=True)",
    ),
    (
        "RECENT_MEM V2",
        "# =============================================================================\n"
        "# ELI RECENT MEMORY PROCESSING PROCESS OVERRIDE V2",
        "except Exception as _eli_recent_mem_process_v2_err:\n"
        "    print(f\"[ENGINE] recent-memory-processing process override v2 install failed: {_eli_recent_mem_process_v2_err}\", flush=True)",
    ),
    (
        "RECENT_MEM V3 (helpers now at module level)",
        "# =============================================================================\n"
        "# ELI RECENT MEMORY PROCESSING PROCESS OVERRIDE V3",
        "except Exception as _eli_recent_mem_v3_err:\n"
        "    print(f\"[ENGINE] recent-memory-processing process override v3 install failed: {_eli_recent_mem_v3_err}\", flush=True)",
    ),
    (
        "SELF_REPORT validator",
        "# =============================================================================\n"
        "# ELI SELF-REPORT RECENT UPDATES PROCESS VALIDATOR",
        "except Exception as _eli_self_engine_error:\n"
        "    print(\"[ENGINE][WARN] self-report recent-updates validator failed:\", _eli_self_engine_error)",
    ),
    (
        "MC V4 (helpers now at module level)",
        "# =============================================================================\n"
        "# ELI MEMORY COUNT NON-QUICK GROUNDED SYNTHESIS V4",
        "except Exception as _eli_mc_e:\n"
        "    print(f\"[ENGINE] memory-count nonquick deterministic synthesis v4 skipped: {_eli_mc_e}\")",
    ),
    (
        "MC V5 (helpers now at module level)",
        "# =============================================================================\n"
        "# ELI MEMORY COUNT MODE DEPTH FIX V5",
        "except Exception as _eli_mc_depth_e:\n"
        "    print(f\"[ENGINE] memory-count mode depth fix v5 skipped: {_eli_mc_depth_e}\")",
    ),
    (
        "V7 RS wrapper",
        "# =============================================================================\n"
        "# ELI RUNTIME STATUS MODE CONTRACT FIX V7",
        "except Exception as _eli_runtime_status_v7_exc:\n"
        "    print(f\"[ENGINE] runtime-status nonquick synthesis contract fix v7 failed: {_eli_runtime_status_v7_exc!r}\")",
    ),
]

for name, start, end in BLOCKS_TO_DELETE:
    assert start in src, f"start anchor for '{name}' not found"
    assert end in src, f"end anchor for '{name}' not found"
    i = src.index(start)
    j = src.index(end, i) + len(end)
    src = src[:i] + f"# {name} block removed (Phase 2c — helpers relocated above class CognitiveEngine)\n" + src[j:]


# ───────────────────────────────────────────────────────────────────────
# Final sanity checks
# ───────────────────────────────────────────────────────────────────────
# Helpers must be reachable at module level (only one definition each).
for fn in [
    "_eli_pm_engine_wants_personal_memory",
    "_eli_pm_engine_wants_routing_fault",
    "_eli_pm_engine_mode_key",
    "_eli_recent_mem_v3_is_prompt",
    "_eli_recent_mem_v3_mode",
    "_eli_recent_mem_v3_execute",
    "_eli_mc_is_memory_count_question_v4",
    "_eli_mc_mode_v4",
    "_eli_mc_payload_v5",
]:
    occurrences = src.count(f"def {fn}(")
    assert occurrences == 1, f"helper {fn} has {occurrences} definitions (expected 1)"

# No more `CognitiveEngine.process =` reassignments.
assert "CognitiveEngine.process =" not in src, "leftover process reassignment"

p.write_text(src, encoding="utf-8")
print("Phase 2c complete:")
print(f"  - relocated 13 helpers to module level above class CognitiveEngine")
print(f"  - deleted {len(BLOCKS_TO_DELETE)} inert bottom blocks")
print(f"  - file size: {len(src.splitlines())} lines")
