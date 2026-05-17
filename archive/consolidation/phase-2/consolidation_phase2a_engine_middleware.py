#!/usr/bin/env python3
"""
Phase 2a: migrate the 4 active engine.py wrappers into canonical CognitiveEngine.process()
as inline middleware sections, and delete the wrapper bottom blocks.

Active wrappers being inlined:
  1. V18 + V19 RUNTIME_STATUS (canonical + non-Quick full-pipeline)
     -> ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1
  2. MEMORY_RUNTIME_STRICT_GROUNDED_NO_RAW_GGUF
     -> ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1
  3. MEMORY_COUNT_INCLUDE_CONVERSATION_TURNS
     -> ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_TURNS_TELEMETRY_V1

Phase 2a does NOT touch the inert legacy blocks (V1..V8 wrappers whose
"Migrated into" comment confirms they no longer reassign process). Those
get cleaned up in Phase 2b.

Strategy: exact-text replacements with assertions. Aborts on first
mismatch — leaves the file untouched.
"""
from __future__ import annotations

from pathlib import Path
import sys

p = Path(__file__).resolve().parents[2] / "eli" / "kernel" / "engine.py"
if not p.exists():
    print(f"ERROR: engine.py not found at {p}", file=sys.stderr)
    sys.exit(2)

src = p.read_text(encoding="utf-8")

# ───────────────────────────────────────────────────────────────────────
# Sentinel: refuse to re-apply
# ───────────────────────────────────────────────────────────────────────
SENTINEL = "# === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1 ==="
if SENTINEL in src:
    print(f"already applied: sentinel '{SENTINEL}' present; skipping.")
    sys.exit(0)


# ───────────────────────────────────────────────────────────────────────
# Block 1 — new module-level helpers (above class CognitiveEngine:)
# Names use `_mw_*` prefix to avoid colliding with same-named functions
# still defined inside the wrapper try-blocks until those blocks are
# deleted below.
# ───────────────────────────────────────────────────────────────────────
HELPERS_ANCHOR_OLD = "class CognitiveEngine:\n    def __init__(self):"
HELPERS_ANCHOR_NEW = '''# ============================================================
# ENGINE MIDDLEWARE HELPERS (Phase 2a consolidation)
# Module-level helpers used by the inline middleware sections inside
# CognitiveEngine.process(). Defined unconditionally above the class
# so process() never needs `"name" in globals()` guards.
# ============================================================

# -- RUNTIME_STATUS non-Quick full-pipeline (V18+V19 merged) -----------

def _mw_rs_text_from_args(args, kwargs) -> str:
    for key in ("user_input", "message", "text", "prompt"):
        val = kwargs.get(key)
        if val is not None:
            return str(val)
    if args:
        return str(args[0])
    return ""


def _mw_rs_mode_from_args(args, kwargs) -> str:
    mode = kwargs.get("reasoning_mode")
    if mode is None and len(args) >= 4:
        mode = args[3]
    try:
        from eli.cognition.reasoning_modes import canonical_mode as _cm
        return _cm(mode)
    except Exception:
        return str(mode or "quick").strip().lower() or "quick"


def _mw_rs_is_quick(mode) -> bool:
    return str(mode or "").strip().lower() in {"quick", "fast", "direct"}


def _mw_rs_is_runtime_status_question(text) -> bool:
    raw = str(text or "").strip()
    low = raw.lower()
    if not low:
        return False
    # Prefer the real router contract where possible.
    try:
        routed = route_intent(raw)
        if isinstance(routed, dict):
            return str(routed.get("action") or "").strip().upper() == "RUNTIME_STATUS"
    except Exception:
        pass
    import re as _re
    return bool(
        _re.search(r"\\b(who are you|what are you actually running on|runtime status|model|context size|gpu layers|gpu|ctx)\\b", low)
        and _re.search(r"\\b(running|runtime|model|context|ctx|gpu|layers|provider|everything)\\b", low)
    )


def _mw_rs_extract_text(out) -> str:
    if isinstance(out, dict):
        return str(out.get("content") or out.get("response") or out.get("message") or "").strip()
    return str(out or "").strip()


def _mw_rs_call_runtime_status(question) -> dict:
    try:
        from eli.execution.executor_enhanced import execute as _exec
        out = _exec("RUNTIME_STATUS", {"question": str(question or ""), "detail": "full"})
        if not isinstance(out, dict):
            txt = str(out or "").strip()
            out = {
                "ok": bool(txt),
                "action": "RUNTIME_STATUS",
                "content": txt,
                "response": txt,
                "source": "runtime_status_executor_text",
                "evidence_source": "runtime_status_live_runtime_telemetry",
            }
        return dict(out)
    except Exception as e:
        return {
            "ok": False,
            "action": "RUNTIME_STATUS",
            "content": "",
            "response": "",
            "error": repr(e),
            "source": "runtime_status_nonquick_full_pipeline_v1_evidence_error",
            "evidence_source": "runtime_status_live_runtime_telemetry_failed",
        }


def _mw_rs_generate(prompt, system, mode) -> str:
    """Local GGUF synthesis for runtime-status. Not a raw telemetry return."""
    try:
        from eli.cognition import gguf_inference as _gguf
        for name in ("chat_completion", "complete", "generate_text", "_chat_completion_impl"):
            fn = getattr(_gguf, name, None)
            if not callable(fn):
                continue
            try:
                txt = fn(
                    prompt=prompt,
                    system=system,
                    max_tokens=900,
                    temperature=0.35 if mode == "constitutional_ai" else 0.45,
                    top_p=0.9,
                )
                if isinstance(txt, dict):
                    txt = txt.get("response") or txt.get("content") or txt.get("text") or ""
                txt = str(txt or "").strip()
                if txt:
                    return txt
            except Exception:
                continue
        gen_fn = getattr(_gguf, "_generate_impl", None)
        if callable(gen_fn):
            chunks = []
            try:
                result = gen_fn(
                    prompt=prompt,
                    system=system,
                    stream=False,
                    max_tokens=900,
                    temperature=0.35 if mode == "constitutional_ai" else 0.45,
                    top_p=0.9,
                )
                for chunk in result:
                    if isinstance(chunk, dict):
                        chunks.append(str(chunk.get("response") or chunk.get("content") or ""))
                    else:
                        chunks.append(str(chunk or ""))
                txt = "".join(chunks).strip()
                if txt:
                    return txt
            except Exception:
                pass
        raise RuntimeError("No usable GGUF synthesis surface produced text")
    except Exception as e:
        raise RuntimeError(f"runtime-status non-Quick synthesis failed: {e}") from e


def _mw_rs_bad_synthesis(text) -> str:
    low = str(text or "").lower()
    if not low.strip():
        return "empty synthesis"
    forbidden = (
        "raw gguf candidate",
        "raw_gguf_candidates_skipped",
        "repair_reason",
        "response_surface:",
        "synthesis_validated",
        "evidence_source:",
        "{'ok':",
        '"ok":',
        "canonical live grounded telemetry",
    )
    for frag in forbidden:
        if frag in low:
            return f"leaked internal/direct telemetry marker: {frag}"
    required_any = ("model", "context", "gpu", "provider", "runtime")
    if sum(1 for x in required_any if x in low) < 3:
        return "synthesis did not preserve enough runtime facts"
    return ""


def _mw_rs_synthesize(question, mode, evidence) -> dict:
    evidence_text = _mw_rs_extract_text(evidence)
    if not evidence_text:
        err = evidence.get("error") if isinstance(evidence, dict) else ""
        msg = f"Runtime-status evidence collection failed, so non-Quick synthesis was not attempted. Error: {err}"
        return {
            "ok": False, "action": "RUNTIME_STATUS",
            "content": msg, "response": msg,
            "source": "runtime_status_nonquick_full_pipeline_v1_fail_closed",
            "evidence_source": "runtime_status_live_runtime_telemetry_failed",
            "grounded": False, "evidence_used": False,
            "report": {
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
            },
        }
    mode_instruction = {
        "chain_of_thought": "Use private structured reasoning. Do not reveal hidden reasoning. Output only the final answer.",
        "self_consistency": "Privately compare several possible phrasings and output only the strongest final answer.",
        "tree_of_thoughts": "Privately explore branches, prune weak ones, and output only the strongest final answer.",
        "constitutional_ai": "Draft, privately critique for accuracy and contract compliance, revise, and output only the final answer.",
    }.get(str(mode), "Use the normal non-Quick synthesis path. Output only the final answer.")

    system = (
        "You are ELI, the local assistant inside the ELI MKXI project. "
        "You are answering from live runtime telemetry evidence. "
        "Do not invent runtime facts. "
        "Do not expose JSON packets, internal report fields, repair reasons, raw candidate metadata, or validation machinery. "
        "Do not say telemetry was skipped. "
        "Return a concise but complete synthesized answer."
    )
    prompt = (
        f"Original user question:\\n{question}\\n\\n"
        f"Reasoning mode:\\n{mode}\\n\\n"
        f"Mode contract:\\n{mode_instruction}\\n\\n"
        f"Live runtime telemetry evidence:\\n{evidence_text}\\n\\n"
        "Task:\\nAnswer the user as ELI. Include identity, model/provider, "
        "model path/name, context size, GPU layers, batch size, CPU threads, "
        "GPU info if present, project paths if present, and generation settings if present. "
        "This must be a synthesized final answer, not a raw telemetry dump.\\n"
    )
    try:
        synthesized = _mw_rs_generate(prompt, system, mode).strip()
    except Exception as e:
        msg = f"Runtime-status evidence was collected, but non-Quick synthesis failed: {e}"
        return {
            "ok": False, "action": "RUNTIME_STATUS",
            "content": msg, "response": msg,
            "source": "runtime_status_nonquick_full_pipeline_v1_synthesis_failed",
            "evidence_source": "runtime_status_live_runtime_telemetry",
            "grounded": True, "evidence_used": True,
            "report": {
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
                "error": repr(e),
            },
        }
    bad = _mw_rs_bad_synthesis(synthesized)
    if bad:
        msg = (
            f"Runtime-status non-Quick synthesis failed validation: {bad}. "
            "Direct telemetry was not returned because only Quick mode may use that surface."
        )
        return {
            "ok": False, "action": "RUNTIME_STATUS",
            "content": msg, "response": msg,
            "source": "runtime_status_nonquick_full_pipeline_v1_validation_failed",
            "evidence_source": "runtime_status_live_runtime_telemetry",
            "grounded": True, "evidence_used": True,
            "report": {
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
                "validation_error": bad,
            },
        }
    return {
        "ok": True, "action": "RUNTIME_STATUS",
        "content": synthesized, "response": synthesized,
        "source": "runtime_status_nonquick_full_pipeline_synthesized_v1",
        "evidence_source": "runtime_status_live_runtime_telemetry",
        "grounded": True, "evidence_used": True,
        "report": {
            "requested_mode": mode,
            "synthesis_validated": True,
            "direct_telemetry_returned": False,
            "quick_direct_allowed": False,
            "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
        },
    }


def _mw_rs_quick_direct(question, mode) -> dict:
    """Quick mode: deterministic grounded runtime evidence via contract module."""
    try:
        from eli.contracts.runtime_status import quick_result as _quick_result
        return _quick_result(mode=mode)
    except Exception as e:
        # Fall back to the same executor evidence used by Non-Quick, returned raw.
        ev = _mw_rs_call_runtime_status(question)
        ev = dict(ev)
        ev.setdefault("source", "runtime_status_quick_direct_fallback")
        ev["report"] = {
            **(ev.get("report") or {}),
            "requested_mode": mode,
            "synthesis_validated": None,
            "quick_direct_allowed": True,
            "fallback_reason": repr(e),
        }
        return ev


# -- MEMORY_RUNTIME strict grounded no-raw-GGUF ------------------------

def _mw_mem_runtime_strict_is_question(text) -> bool:
    import re as _re
    raw = str(text or "").strip()
    low = raw.lower()
    if not low:
        return False
    if _re.search(r"\\b(?:run|execute|call|invoke)?\\s*`?explain_memory_runtime`?\\b", low):
        return True
    if _re.search(
        r"\\b("
        r"explain exactly how your memory system works internally|"
        r"memory system works internally|"
        r"how (?:does|do) your memory system work|"
        r"how does your memory work internally|"
        r"which files.*which db tables.*which functions|"
        r"memory runtime(?: surface)?|"
        r"memory architecture|"
        r"memory internals"
        r")\\b",
        low,
    ):
        return True
    if _re.search(r"\\bmemor(?:y|ies)\\b", low) and _re.search(
        r"\\b("
        r"database files?|db files?|databases?|sqlite|tables?|schema|"
        r"functions?|internally|architecture|runtime|"
        r"faiss|fts5|vectors?|vectoring|recall_log|conversation_turns|"
        r"user\\.sqlite3|agent\\.sqlite3|memory\\.sqlite3"
        r")\\b",
        low,
    ):
        asks_profile = _re.search(
            r"\\b(what do you know about me|what do you remember about me|"
            r"my preferences|my profile|who am i|what is my name)\\b",
            low,
        )
        asks_arch = _re.search(
            r"\\b(files?|db|database|sqlite|tables?|functions?|schema|"
            r"internally|runtime|architecture)\\b",
            low,
        )
        if asks_profile and not asks_arch:
            return False
        return True
    return False


def _mw_mem_runtime_strict_live_result(raw, mode) -> dict:
    try:
        from eli.execution.executor_enhanced import execute as _exec
        out = _exec("EXPLAIN_MEMORY_RUNTIME", {"question": str(raw or ""), "detail": "full"})
        if not isinstance(out, dict):
            txt = str(out or "").strip()
            out = {
                "ok": bool(txt), "action": "EXPLAIN_MEMORY_RUNTIME",
                "content": txt, "response": txt, "report": {},
            }
        out = dict(out)
        report = dict(out.get("report") or {})
        report["requested_mode"] = mode
        report["synthesis_validated"] = None if mode == "quick" else True
        report["gguf_used_for_memory_runtime_synthesis"] = False
        report["raw_gguf_candidates_skipped"] = True
        report["response_surface"] = (
            "quick direct canonical memory-runtime telemetry"
            if mode == "quick"
            else "non-Quick canonical grounded memory-runtime telemetry; raw GGUF candidate generation skipped"
        )
        report["repair_reason"] = "memory_runtime_strict_grounded_no_raw_gguf"
        out["ok"] = bool(out.get("ok", True))
        out["action"] = "EXPLAIN_MEMORY_RUNTIME"
        out["report"] = report
        out["source"] = "memory_runtime_strict_grounded_no_raw_gguf_v1"
        out["evidence_source"] = "memory_runtime_strict_grounded_no_raw_gguf_v1"
        out["grounded"] = True
        out["evidence_used"] = True
        txt = str(out.get("content") or out.get("response") or "").strip()
        bad = (
            "Personal memory evidence report",
            "The human brain does not use databases",
            "not stored in traditional database files",
            "specific tables used depend",
            "Could not open app: explain_memory_runtime",
        )
        if any(x.lower() in txt.lower() for x in bad):
            raise RuntimeError("memory-runtime strict output rejected contaminated surface")
        return out
    except Exception as e:
        msg = (
            "Memory runtime inspection failed closed before synthesis. "
            f"No raw GGUF fallback was used. Error: {e}"
        )
        return {
            "ok": False, "action": "EXPLAIN_MEMORY_RUNTIME",
            "source": "memory_runtime_strict_grounded_no_raw_gguf_v1_fail_closed",
            "evidence_source": "memory_runtime_strict_grounded_no_raw_gguf_v1_fail_closed",
            "grounded": True, "evidence_used": True,
            "content": msg, "response": msg,
            "report": {
                "requested_mode": mode,
                "synthesis_validated": False,
                "gguf_used_for_memory_runtime_synthesis": False,
                "raw_gguf_candidates_skipped": True,
                "repair_reason": "memory_runtime_strict_fail_closed",
                "error": repr(e),
            },
        }


# -- MEMORY_COUNT + conversation_turns telemetry -----------------------

def _mw_mc_turns_is_question(text) -> bool:
    import re as _re
    low = str(text or "").lower()
    return bool(
        _re.search(r"\\bhow many\\b", low)
        and _re.search(r"\\bmemories?\\b", low)
        and _re.search(r"\\bconversation turns?\\b", low)
    )


def _mw_mc_turns_result(mode) -> dict:
    import sqlite3
    from pathlib import Path as _Path
    from eli.core.paths import user_db_path, agent_db_path
    user_db = _Path(user_db_path())
    agent_db = _Path(agent_db_path())
    def _count(path, table):
        try:
            con = sqlite3.connect(str(path))
            try:
                row = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                return int((row or [0])[0] or 0)
            finally:
                con.close()
        except Exception:
            return None
    user_memories = _count(user_db, "memories")
    user_turns = _count(user_db, "conversation_turns")
    user_recall_log = _count(user_db, "recall_log")
    user_runtime_events = _count(user_db, "runtime_events")
    agent_improvements = _count(agent_db, "improvements")
    agent_failures = _count(agent_db, "failures")
    lines = [
        "Memory/count telemetry from live SQLite:",
        f"- user_db: {user_db}",
        f"- agent_db: {agent_db}",
        f"- user.sqlite3:memories: {user_memories}",
        f"- user.sqlite3:conversation_turns: {user_turns}",
        f"- user.sqlite3:recall_log: {user_recall_log} [retrieval log, not counted as memory]",
        f"- user.sqlite3:runtime_events: {user_runtime_events} [runtime telemetry, not counted as memory]",
        f"- agent.sqlite3:improvements: {agent_improvements}",
        f"- agent.sqlite3:failures: {agent_failures}",
    ]
    txt = "\\n".join(lines)
    return {
        "ok": True, "action": "MEMORY_STATUS",
        "source": "memory_count_include_conversation_turns_v1",
        "evidence_source": "memory_count_include_conversation_turns_v1",
        "grounded": True, "evidence_used": True,
        "content": txt, "response": txt,
        "report": {
            "requested_mode": mode,
            "synthesis_validated": None if mode == "quick" else True,
            "user_db": str(user_db), "agent_db": str(agent_db),
            "memories": user_memories,
            "conversation_turns": user_turns,
            "recall_log": user_recall_log,
            "runtime_events": user_runtime_events,
        },
    }


class CognitiveEngine:
    def __init__(self):'''

assert HELPERS_ANCHOR_OLD in src, "anchor 'class CognitiveEngine:' not found"
src = src.replace(HELPERS_ANCHOR_OLD, HELPERS_ANCHOR_NEW, 1)


# ───────────────────────────────────────────────────────────────────────
# Block 2 — insert 3 new middleware sections in process(), just before
# the existing # === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8 === marker.
# ───────────────────────────────────────────────────────────────────────
MW_ANCHOR_OLD = "        # === END ELI_ENGINE_MIDDLEWARE_PERSONAL_MEMORY_QUICK_V1 ===\n\n\n        # === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8 ==="
MW_ANCHOR_NEW = '''        # === END ELI_ENGINE_MIDDLEWARE_PERSONAL_MEMORY_QUICK_V1 ===


        # === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1 ===
        # Migrated from bottom-of-file V18+V19 wrappers.
        # Quick mode may return deterministic live runtime telemetry directly.
        # Non-Quick modes gather live telemetry as evidence, synthesize via local
        # GGUF, validate the synthesized answer, then return only the synthesized
        # surface. Replaces the older V8 inline path for RUNTIME_STATUS questions.
        try:
            _mw_rs_kwargs = dict(kwargs)
            try:
                _mw_rs_kwargs.setdefault("reasoning_mode", reasoning_mode)
            except Exception:
                pass
            _mw_rs_text = _mw_rs_text_from_args((user_input,), _mw_rs_kwargs) or str(user_input or "")
            if _mw_rs_is_runtime_status_question(_mw_rs_text):
                _mw_rs_mode = _mw_rs_mode_from_args((user_input,), _mw_rs_kwargs)
                if _mw_rs_is_quick(_mw_rs_mode):
                    return _mw_rs_quick_direct(_mw_rs_text, _mw_rs_mode)
                _mw_rs_evidence = _mw_rs_call_runtime_status(_mw_rs_text)
                _mw_rs_out = _mw_rs_synthesize(_mw_rs_text, _mw_rs_mode, _mw_rs_evidence)
                print("[ENGINE] RUNTIME_STATUS non-Quick full-pipeline synthesis middleware returned", flush=True)
                return _mw_rs_out
        except Exception as _mw_rs_err:
            print(f"[ENGINE][WARN] runtime-status full-pipeline middleware failed: {_mw_rs_err}", flush=True)
        # === END ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1 ===


        # === ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1 ===
        # Migrated from bottom-of-file _eli_memory_runtime_strict_* wrapper.
        # Memory-runtime architecture/status is local telemetry, not a freeform
        # model question. Prevents personal-memory hijack, CHAT hallucinations,
        # OPEN_APP hijack, and raw GGUF candidate poisoning for these questions.
        try:
            _mw_mrs_kwargs = dict(kwargs)
            try:
                _mw_mrs_kwargs.setdefault("reasoning_mode", reasoning_mode)
            except Exception:
                pass
            _mw_mrs_text = _mw_rs_text_from_args((user_input,), _mw_mrs_kwargs) or str(user_input or "")
            if _mw_mem_runtime_strict_is_question(_mw_mrs_text):
                _mw_mrs_mode = _mw_rs_mode_from_args((user_input,), _mw_mrs_kwargs)
                print("[ENGINE] EXPLAIN_MEMORY_RUNTIME strict grounded middleware returned; raw GGUF candidates skipped", flush=True)
                return _mw_mem_runtime_strict_live_result(_mw_mrs_text, _mw_mrs_mode)
        except Exception as _mw_mrs_err:
            print(f"[ENGINE][WARN] memory-runtime strict middleware failed: {_mw_mrs_err}", flush=True)
        # === END ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1 ===


        # === ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_TURNS_TELEMETRY_V1 ===
        # Migrated from bottom-of-file _eli_memory_count_turns_* wrapper.
        # Specifically handles "how many memories AND conversation turns" — a
        # broader telemetry surface than the narrower MEMORY_COUNT_V5 middleware.
        try:
            _mw_mct_kwargs = dict(kwargs)
            try:
                _mw_mct_kwargs.setdefault("reasoning_mode", reasoning_mode)
            except Exception:
                pass
            _mw_mct_text = _mw_rs_text_from_args((user_input,), _mw_mct_kwargs) or str(user_input or "")
            if _mw_mc_turns_is_question(_mw_mct_text):
                _mw_mct_mode = _mw_rs_mode_from_args((user_input,), _mw_mct_kwargs)
                print("[ENGINE] memory count + conversation turns middleware returned from live SQLite", flush=True)
                return _mw_mc_turns_result(_mw_mct_mode)
        except Exception as _mw_mct_err:
            print(f"[ENGINE][WARN] memory-count turns middleware failed: {_mw_mct_err}", flush=True)
        # === END ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_TURNS_TELEMETRY_V1 ===


        # === ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_V8 ==='''

assert MW_ANCHOR_OLD in src, "anchor for inserting new middleware not found"
src = src.replace(MW_ANCHOR_OLD, MW_ANCHOR_NEW, 1)


# ───────────────────────────────────────────────────────────────────────
# Block 3 — delete the 4 active wrapper bottom blocks.
# We delete by exact-text replacement of each block with a one-line
# breadcrumb comment so the diff is readable.
# ───────────────────────────────────────────────────────────────────────

# 3a. V10/V18 RUNTIME_STATUS canonical contract block (lines ~9710-9794)
V18_BLOCK_START = "# =============================================================================\n# ELI RUNTIME_STATUS NON-QUICK REPAIR VALIDATOR V10"
V18_BLOCK_END = (
    "except Exception as e:\n"
    "    print(f\"[ENGINE] runtime-status all-surfaces generation block v17 install failed: {e}\")"
)

assert V18_BLOCK_START in src, "V18 block header not found"
assert V18_BLOCK_END in src, "V18 block tail (orphan except v17) not found"

# Excise everything from V18_BLOCK_START through V18_BLOCK_END inclusive.
_v18_i = src.index(V18_BLOCK_START)
_v18_j = src.index(V18_BLOCK_END, _v18_i) + len(V18_BLOCK_END)
src = (
    src[:_v18_i]
    + "# RUNTIME_STATUS canonical contract (V10/V18) migrated to inline middleware "
      "ELI_ENGINE_MIDDLEWARE_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_V1\n"
    + src[_v18_j:]
)

# 3b. MEMORY_RUNTIME strict grounded no-raw GGUF block
MEM_RUNTIME_START = "# =============================================================================\n# ELI_MEMORY_RUNTIME_STRICT_GROUNDED_NO_RAW_GGUF_V1"
MEM_RUNTIME_END = (
    "except Exception as _eli_memory_runtime_strict_install_err:\n"
    "    print(f\"[ENGINE] memory-runtime strict grounded no-raw install failed: {_eli_memory_runtime_strict_install_err}\", flush=True)\n"
    "# ============================================================================="
)
assert MEM_RUNTIME_START in src, "memory-runtime strict block header not found"
assert MEM_RUNTIME_END in src, "memory-runtime strict block tail not found"
_mrs_i = src.index(MEM_RUNTIME_START)
_mrs_j = src.index(MEM_RUNTIME_END, _mrs_i) + len(MEM_RUNTIME_END)
src = (
    src[:_mrs_i]
    + "# MEMORY_RUNTIME strict grounded migrated to inline middleware "
      "ELI_ENGINE_MIDDLEWARE_MEMORY_RUNTIME_STRICT_V1"
    + src[_mrs_j:]
)

# 3c. MEMORY_COUNT_INCLUDE_CONVERSATION_TURNS_V1 block
MEM_COUNT_TURNS_START = "# =============================================================================\n# ELI_MEMORY_COUNT_INCLUDE_CONVERSATION_TURNS_V1"
MEM_COUNT_TURNS_END = (
    "except Exception as _eli_memory_count_turns_err:\n"
    "    print(f\"[ENGINE] memory-count conversation-turn contract failed: {_eli_memory_count_turns_err}\", flush=True)\n"
    "# ============================================================================="
)
assert MEM_COUNT_TURNS_START in src, "memory-count turns block header not found"
assert MEM_COUNT_TURNS_END in src, "memory-count turns block tail not found"
_mct_i = src.index(MEM_COUNT_TURNS_START)
_mct_j = src.index(MEM_COUNT_TURNS_END, _mct_i) + len(MEM_COUNT_TURNS_END)
src = (
    src[:_mct_i]
    + "# MEMORY_COUNT + conversation_turns telemetry migrated to inline middleware "
      "ELI_ENGINE_MIDDLEWARE_MEMORY_COUNT_TURNS_TELEMETRY_V1"
    + src[_mct_j:]
)

# 3d. V19 RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_SYNTHESIS_V1 block
V19_START = "# =============================================================================\n# ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_SYNTHESIS_V1"
V19_END = (
    "except Exception as _eli_runtime_status_nonquick_full_pipeline_err:\n"
    "    print(f\"[ENGINE] runtime-status non-Quick full-pipeline synthesis contract failed: {_eli_runtime_status_nonquick_full_pipeline_err}\", flush=True)\n"
    "# ============================================================================="
)
assert V19_START in src, "V19 block header not found"
assert V19_END in src, "V19 block tail not found"
_v19_i = src.index(V19_START)
_v19_j = src.index(V19_END, _v19_i) + len(V19_END)
src = (
    src[:_v19_i]
    + "# V19 RUNTIME_STATUS non-Quick full-pipeline synthesis already migrated to inline middleware above"
    + src[_v19_j:]
)

# ───────────────────────────────────────────────────────────────────────
# Final sanity checks
# ───────────────────────────────────────────────────────────────────────
assert "CognitiveEngine.process = process" not in src, (
    "leftover 'CognitiveEngine.process = process' assignment after deletes"
)
assert "_ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_PREV_PROCESS" not in src, (
    "V19 closure cell still present"
)
assert "_ELI_MEMORY_COUNT_TURNS_PREV_PROCESS" not in src, (
    "mem-count-turns closure cell still present"
)
assert "_ELI_MEMORY_RUNTIME_STRICT_PREV_PROCESS" not in src, (
    "mem-runtime-strict closure cell still present"
)
assert "_ELI_RUNTIME_STATUS_CANONICAL_CONTRACT_V18_PREV_PROCESS" not in src, (
    "V18 closure cell still present"
)
assert SENTINEL in src, "new sentinel not inserted"

p.write_text(src, encoding="utf-8")

print("Phase 2a complete:")
print("  - new helpers section inserted above class CognitiveEngine")
print("  - 3 new inline middleware sections added in process()")
print("  - V18, mem-runtime-strict, mem-count-turns, V19 wrapper blocks deleted")
print(f"  - file size: {len(src.splitlines())} lines")
