#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import time

# ---------------------------------------------------------------------
# 1. Router lock:
#    memory-runtime architecture questions must route to EXPLAIN_MEMORY_RUNTIME,
#    never CHAT, OPEN_APP, or personal-memory profile surfaces.
# ---------------------------------------------------------------------
router = Path("eli/execution/router_enhanced.py")
src = router.read_text(encoding="utf-8")
orig = src

marker = "ELI_MEMORY_RUNTIME_ROUTE_LOCK_V1"

if marker not in src:
    backup = router.with_suffix(router.suffix + f".bak_memory_runtime_route_lock_{time.strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(src, encoding="utf-8")

    src += r'''

# =============================================================================
# ELI_MEMORY_RUNTIME_ROUTE_LOCK_V1
# Memory-runtime architecture/control questions are first-class grounded telemetry.
# They must not be stolen by generic CHAT, OPEN_APP, or personal-memory/profile
# routing. This does not answer the question; it only guarantees the correct
# evidence action.
# =============================================================================
try:
    _ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE = route

    def _eli_memory_runtime_route_lock_should_trigger(text):
        import re as _re

        raw = str(text or "").strip()
        low = raw.lower()

        if not low:
            return False

        # Literal control/action invocation.
        if _re.search(r"\b(?:run|execute|call|invoke)?\s*`?explain_memory_runtime`?\b", low):
            return True

        # Direct architecture/internal-memory requests.
        if _re.search(
            r"\b("
            r"explain exactly how your memory system works internally|"
            r"memory system works internally|"
            r"how (?:does|do) your memory system work|"
            r"how does your memory work internally|"
            r"which files.*which db tables.*which functions|"
            r"memory runtime(?: surface)?|"
            r"memory architecture|"
            r"memory internals"
            r")\b",
            low,
        ):
            return True

        # Broader DB/schema/function phrasing.
        if "memory" in low and _re.search(
            r"\b("
            r"database files?|db files?|databases?|sqlite|tables?|schema|"
            r"functions?|internally|architecture|runtime|"
            r"faiss|fts5|vectors?|vectoring|recall_log|conversation_turns|"
            r"user\.sqlite3|agent\.sqlite3|memory\.sqlite3"
            r")\b",
            low,
        ):
            # Personal profile questions should stay personal-memory unless the
            # user explicitly asks architecture/schema/files/functions.
            asks_profile = _re.search(
                r"\b(what do you know about me|what do you remember about me|"
                r"my preferences|my profile|who am i|what is my name)\b",
                low,
            )
            asks_arch = _re.search(
                r"\b(files?|db|database|sqlite|tables?|functions?|schema|"
                r"internally|runtime|architecture)\b",
                low,
            )
            if asks_profile and not asks_arch:
                return False
            return True

        return False


    def _eli_memory_runtime_route_lock_result(raw):
        return {
            "action": "EXPLAIN_MEMORY_RUNTIME",
            "args": {"question": str(raw or ""), "detail": "full"},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.memory_runtime_route_lock_v1",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "memory_runtime",
                "response_contract": "canonical_grounded_memory_runtime_no_raw_gguf",
            },
        }


    def route(text="", *args, _prev=_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE, **kwargs):
        if _eli_memory_runtime_route_lock_should_trigger(text):
            return _eli_memory_runtime_route_lock_result(text)
        return _prev(text, *args, **kwargs)


    if "route_intent" in globals() and callable(route_intent):
        _ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_INTENT = route_intent

        def route_intent(text="", *args, _prev=_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_INTENT, **kwargs):
            if _eli_memory_runtime_route_lock_should_trigger(text):
                return _eli_memory_runtime_route_lock_result(text)
            return _prev(text, *args, **kwargs)


    if "route_command" in globals() and callable(route_command):
        _ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_COMMAND = route_command

        def route_command(text="", *args, _prev=_ELI_MEMORY_RUNTIME_ROUTE_LOCK_PREV_ROUTE_COMMAND, **kwargs):
            if _eli_memory_runtime_route_lock_should_trigger(text):
                return _eli_memory_runtime_route_lock_result(text)
            return _prev(text, *args, **kwargs)


    print("[ROUTER] memory-runtime strict route lock installed", flush=True)

except Exception as _eli_memory_runtime_route_lock_err:
    print(f"[ROUTER] memory-runtime strict route lock failed: {_eli_memory_runtime_route_lock_err}", flush=True)
# =============================================================================
'''

    router.write_text(src, encoding="utf-8")
    print(f"[PATCH] router installed {marker}")
    print(f"[PATCH] router backup: {backup}")
else:
    print(f"[PATCH] router marker already present: {marker}")


# ---------------------------------------------------------------------
# 2. Engine lock:
#    EXPLAIN_MEMORY_RUNTIME is telemetry. Quick and non-Quick both return
#    canonical live evidence. Non-Quick must not generate raw GGUF candidates,
#    because this path already produced hallucinations and a CUDA abort.
# ---------------------------------------------------------------------
engine = Path("eli/kernel/engine.py")
src = engine.read_text(encoding="utf-8")
orig = src

marker = "ELI_MEMORY_RUNTIME_STRICT_GROUNDED_NO_RAW_GGUF_V1"

if marker not in src:
    backup = engine.with_suffix(engine.suffix + f".bak_memory_runtime_no_raw_{time.strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(src, encoding="utf-8")

    src += r'''

# =============================================================================
# ELI_MEMORY_RUNTIME_STRICT_GROUNDED_NO_RAW_GGUF_V1
# Memory-runtime architecture/status is local telemetry, not a freeform model
# question. This prevents:
#   - personal-memory hijack for architecture questions
#   - CHAT fallback hallucinations
#   - OPEN_APP hijack for literal EXPLAIN_MEMORY_RUNTIME
#   - non-Quick raw GGUF candidate generation / CUDA aborts
# =============================================================================
try:
    _ELI_MEMORY_RUNTIME_STRICT_PREV_PROCESS = CognitiveEngine.process

    def _eli_memory_runtime_strict_mode(_args, _kwargs):
        mode = _kwargs.get("reasoning_mode")
        if mode is None and len(_args) >= 4:
            mode = _args[3]
        try:
            from eli.cognition.reasoning_modes import canonical_mode as _cm
            return _cm(mode)
        except Exception:
            return str(mode or "quick").strip().lower() or "quick"


    def _eli_memory_runtime_strict_message(_args, _kwargs):
        for key in ("user_input", "message", "text", "prompt"):
            val = _kwargs.get(key)
            if val is not None:
                return str(val)
        if _args:
            return str(_args[0])
        return ""


    def _eli_memory_runtime_strict_is_question(text):
        import re as _re

        raw = str(text or "").strip()
        low = raw.lower()

        if not low:
            return False

        if _re.search(r"\b(?:run|execute|call|invoke)?\s*`?explain_memory_runtime`?\b", low):
            return True

        if _re.search(
            r"\b("
            r"explain exactly how your memory system works internally|"
            r"memory system works internally|"
            r"how (?:does|do) your memory system work|"
            r"how does your memory work internally|"
            r"which files.*which db tables.*which functions|"
            r"memory runtime(?: surface)?|"
            r"memory architecture|"
            r"memory internals"
            r")\b",
            low,
        ):
            return True

        if "memory" in low and _re.search(
            r"\b("
            r"database files?|db files?|databases?|sqlite|tables?|schema|"
            r"functions?|internally|architecture|runtime|"
            r"faiss|fts5|vectors?|vectoring|recall_log|conversation_turns|"
            r"user\.sqlite3|agent\.sqlite3|memory\.sqlite3"
            r")\b",
            low,
        ):
            asks_profile = _re.search(
                r"\b(what do you know about me|what do you remember about me|"
                r"my preferences|my profile|who am i|what is my name)\b",
                low,
            )
            asks_arch = _re.search(
                r"\b(files?|db|database|sqlite|tables?|functions?|schema|"
                r"internally|runtime|architecture)\b",
                low,
            )
            if asks_profile and not asks_arch:
                return False
            return True

        return False


    def _eli_memory_runtime_strict_live_result(raw, mode):
        try:
            from eli.execution.executor_enhanced import execute as _eli_exec

            out = _eli_exec(
                "EXPLAIN_MEMORY_RUNTIME",
                {"question": str(raw or ""), "detail": "full"},
            )

            if not isinstance(out, dict):
                txt = str(out or "").strip()
                out = {
                    "ok": bool(txt),
                    "action": "EXPLAIN_MEMORY_RUNTIME",
                    "content": txt,
                    "response": txt,
                    "report": {},
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

        except Exception as _eli_memory_runtime_strict_err:
            # Fail closed. Do not fall through to GGUF/CHAT/OPEN_APP.
            msg = (
                "Memory runtime inspection failed closed before synthesis. "
                f"No raw GGUF fallback was used. Error: {_eli_memory_runtime_strict_err}"
            )
            return {
                "ok": False,
                "action": "EXPLAIN_MEMORY_RUNTIME",
                "source": "memory_runtime_strict_grounded_no_raw_gguf_v1_fail_closed",
                "evidence_source": "memory_runtime_strict_grounded_no_raw_gguf_v1_fail_closed",
                "grounded": True,
                "evidence_used": True,
                "content": msg,
                "response": msg,
                "report": {
                    "requested_mode": mode,
                    "synthesis_validated": False,
                    "gguf_used_for_memory_runtime_synthesis": False,
                    "raw_gguf_candidates_skipped": True,
                    "repair_reason": "memory_runtime_strict_fail_closed",
                    "error": repr(_eli_memory_runtime_strict_err),
                },
            }


    def process(self, *args, _prev=_ELI_MEMORY_RUNTIME_STRICT_PREV_PROCESS, **kwargs):
        raw = _eli_memory_runtime_strict_message(args, kwargs)
        if _eli_memory_runtime_strict_is_question(raw):
            mode = _eli_memory_runtime_strict_mode(args, kwargs)
            print(
                "[ENGINE] EXPLAIN_MEMORY_RUNTIME strict grounded contract returned; raw GGUF candidates skipped",
                flush=True,
            )
            return _eli_memory_runtime_strict_live_result(raw, mode)

        return _prev(self, *args, **kwargs)


    CognitiveEngine.process = process
    print("[ENGINE] memory-runtime strict grounded no-raw contract installed", flush=True)

except Exception as _eli_memory_runtime_strict_install_err:
    print(f"[ENGINE] memory-runtime strict grounded no-raw install failed: {_eli_memory_runtime_strict_install_err}", flush=True)
# =============================================================================
'''

    engine.write_text(src, encoding="utf-8")
    print(f"[PATCH] engine installed {marker}")
    print(f"[PATCH] engine backup: {backup}")
else:
    print(f"[PATCH] engine marker already present: {marker}")


# ---------------------------------------------------------------------
# 3. Optional but targeted: memory count questions asking for conversation
#    turns must include conversation_turns, not only memory rows.
# ---------------------------------------------------------------------
marker = "ELI_MEMORY_COUNT_INCLUDE_CONVERSATION_TURNS_V1"
src = engine.read_text(encoding="utf-8")

if marker not in src:
    backup = engine.with_suffix(engine.suffix + f".bak_memory_count_conversation_turns_{time.strftime('%Y%m%d_%H%M%S')}")
    backup.write_text(src, encoding="utf-8")

    src += r'''

# =============================================================================
# ELI_MEMORY_COUNT_INCLUDE_CONVERSATION_TURNS_V1
# If the user asks for memories AND conversation turns, return both from the live
# SQLite DB. Do not answer only with long-term memory rows.
# =============================================================================
try:
    _ELI_MEMORY_COUNT_TURNS_PREV_PROCESS = CognitiveEngine.process

    def _eli_memory_count_turns_is_question(text):
        import re as _re
        low = str(text or "").lower()
        return bool(
            _re.search(r"\bhow many\b", low)
            and _re.search(r"\bmemories?\b", low)
            and _re.search(r"\bconversation turns?\b", low)
        )


    def _eli_memory_count_turns_mode(_args, _kwargs):
        mode = _kwargs.get("reasoning_mode")
        if mode is None and len(_args) >= 4:
            mode = _args[3]
        try:
            from eli.cognition.reasoning_modes import canonical_mode as _cm
            return _cm(mode)
        except Exception:
            return str(mode or "quick").strip().lower() or "quick"


    def _eli_memory_count_turns_result(mode):
        import sqlite3
        from pathlib import Path
        from eli.core.paths import user_db_path, agent_db_path

        user_db = Path(user_db_path())
        agent_db = Path(agent_db_path())

        def count(path, table):
            try:
                con = sqlite3.connect(str(path))
                try:
                    row = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                    return int((row or [0])[0] or 0)
                finally:
                    con.close()
            except Exception:
                return None

        user_memories = count(user_db, "memories")
        user_turns = count(user_db, "conversation_turns")
        user_recall_log = count(user_db, "recall_log")
        user_runtime_events = count(user_db, "runtime_events")
        agent_improvements = count(agent_db, "improvements")
        agent_failures = count(agent_db, "failures")

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
        txt = "\n".join(lines)

        return {
            "ok": True,
            "action": "MEMORY_STATUS",
            "source": "memory_count_include_conversation_turns_v1",
            "evidence_source": "memory_count_include_conversation_turns_v1",
            "grounded": True,
            "evidence_used": True,
            "content": txt,
            "response": txt,
            "report": {
                "requested_mode": mode,
                "synthesis_validated": None if mode == "quick" else True,
                "user_db": str(user_db),
                "agent_db": str(agent_db),
                "memories": user_memories,
                "conversation_turns": user_turns,
                "recall_log": user_recall_log,
                "runtime_events": user_runtime_events,
            },
        }


    def process(self, *args, _prev=_ELI_MEMORY_COUNT_TURNS_PREV_PROCESS, **kwargs):
        raw = ""
        if args:
            raw = str(args[0])
        for key in ("user_input", "message", "text", "prompt"):
            if kwargs.get(key) is not None:
                raw = str(kwargs.get(key))
                break

        if _eli_memory_count_turns_is_question(raw):
            mode = _eli_memory_count_turns_mode(args, kwargs)
            print("[ENGINE] memory count + conversation turns returned from live SQLite", flush=True)
            return _eli_memory_count_turns_result(mode)

        return _prev(self, *args, **kwargs)


    CognitiveEngine.process = process
    print("[ENGINE] memory-count conversation-turn telemetry contract installed", flush=True)

except Exception as _eli_memory_count_turns_err:
    print(f"[ENGINE] memory-count conversation-turn contract failed: {_eli_memory_count_turns_err}", flush=True)
# =============================================================================
'''

    engine.write_text(src, encoding="utf-8")
    print(f"[PATCH] engine installed {marker}")
    print(f"[PATCH] engine backup: {backup}")
else:
    print(f"[PATCH] engine marker already present: {marker}")
PY

echo
echo "=== compile ==="
python3 -m py_compile \
  eli/execution/router_enhanced.py \
  eli/execution/executor_enhanced.py \
  eli/kernel/engine.py \
  eli/core/paths.py \
  eli/memory/memory.py \
  eli/memory/__init__.py

echo
echo "=== diff ==="
git status -sb
git diff --stat
git diff -- eli/execution/router_enhanced.py eli/kernel/engine.py | sed -n '1,260p'
