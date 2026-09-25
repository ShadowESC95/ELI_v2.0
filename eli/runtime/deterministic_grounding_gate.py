from __future__ import annotations

import ast
import importlib
import json
import re
import sqlite3
import subprocess

# Logger for safety-wrapper suppressed-exception reporting (used before the
# module's main logger exists; must be defined at the top of the file).
import logging as _swlog_logging
_SWLOG = _swlog_logging.getLogger(__name__)

import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from eli.core.paths import canonical_root
    PROJECT_ROOT = canonical_root(Path(__file__).resolve().parents[2])
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

DETERMINISTIC_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_IMPROVE",
    "SELF_ANALYZE",
}

IMPORT_TARGETS = [
    "eli.kernel.engine",
    "eli.cognition.gguf_inference",
    "eli.memory.memory",
    "eli.execution.router_enhanced",
    "eli.execution.executor_enhanced",
    "eli.gui.eli_pro_audio_gui_v2_0",
    "eli.core.runtime_settings",
    "eli.core.paths",
    "eli.planning.proactive_daemon",
]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _artifacts_dir() -> Path:
    """Where the runtime snapshot is actually written.

    The project root and the artifacts dir are the same directory in a source
    checkout and different ones in a shipped build — the code sits on the
    read-only AppImage mount while data lives under ~/.local/share/ELI_v2. So
    `PROJECT_ROOT / "artifacts"` reads a tree that is not there and the snapshot
    silently comes back empty, which is precisely the 2.1.82 self-report failure
    ce40453 fixed in three sibling modules. This is a fourth.
    """
    try:
        from eli.core.paths import data_dir as _dd
        return Path(_dd())
    except Exception:
        return PROJECT_ROOT / "artifacts"


def _runtime_snapshot() -> dict[str, Any]:
    return _read_json(_artifacts_dir() / "runtime_snapshot.json")


def _route_text(text: str) -> dict[str, Any] | None:
    try:
        router = importlib.import_module("eli.execution.router_enhanced")
        fn = getattr(router, "route", None)
        if callable(fn):
            r = fn(text)
            if isinstance(r, dict):
                return r
    except Exception:
        return None
    return None



def _current_mode_label(engine: Any = None) -> str:
    """Best-effort reasoning-mode detection.

    Critical rule:
    - Live engine/GUI-published mode may be trusted.
    - Helper-reported Quick is not trusted because it can be stale/default.
    """

    attr_names = (
        "reasoning_mode",
        "current_reasoning_mode",
        "_reasoning_mode",
        "mode",
        "current_mode",
        "selected_reasoning_mode",
        "reasoning_mode_key",
        "reasoning_mode_label",
        "_current_mode_label",
        "_selected_reasoning_mode",
        "_eli_reasoning_mode",
        "_eli_reasoning_mode_label",
        "eli_reasoning_mode",
        "eli_reasoning_mode_label",
    )

    # 1. Live engine attributes are authoritative.
    for name in attr_names:
        try:
            val = getattr(engine, name, None)
            if val:
                s = str(val).strip()
                if s:
                    return s
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    # 2. Nested engine dicts.
    for obj_name in ("settings", "config", "runtime_settings", "_settings", "state", "_state"):
        try:
            obj = getattr(engine, obj_name, None)
            if isinstance(obj, dict):
                for key in (
                    "reasoning_mode",
                    "mode",
                    "current_mode",
                    "selected_reasoning_mode",
                    "reasoning_mode_label",
                    "eli_reasoning_mode",
                ):
                    val = obj.get(key)
                    if val:
                        s = str(val).strip()
                        if s:
                            return s
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    # 3. Helper fallback LAST. If it says Quick, treat it as unknown unless
    # the live engine already confirmed Quick above.
    try:
        from eli.runtime.reasoning_status import current_reasoning_mode_label
        try:
            val = current_reasoning_mode_label(engine)
        except TypeError:
            val = current_reasoning_mode_label()

        if val:
            s = str(val).strip()
            low = s.lower()

            if low in {"quick", "quick mode", "fast", "fast mode", "direct", "direct mode"}:
                log.debug("[GROUNDING_GATE] ignoring stale helper Quick; no live engine mode published")
                return ""

            return s
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    return ""

def _is_quick_mode(label: str) -> bool:
    low = str(label or "").lower().strip()

    # Explicit deeper modes must never be treated as quick, even if some stale
    # helper reports a mixed label.
    deeper_tokens = (
        "self-c",
        "self consistency",
        "self_consistency",
        "constitutional",
        "const ai",
        "chain",
        "cot",
        "tree",
        "tot",
        "deep",
        "analytical",
        "reasoning",
    )
    if any(tok in low for tok in deeper_tokens):
        return False

    # Only raw quick/direct labels may bypass synthesis.
    return low in {
        "quick",
        "quick mode",
        "fast",
        "fast mode",
        "instant",
        "instant mode",
        "direct",
        "direct mode",
        "rapid",
        "rapid mode",
    }


def _build_synthesis_prompt(user_text: str, action: str, evidence: str, mode_label: str) -> str:
    return (
        "SYNTHESISE_FROM_DETERMINISTIC_EVIDENCE\n\n"
        "The user asked:\n"
        f"{user_text}\n\n"
        "Authoritative deterministic evidence follows. Treat it as ground truth. "
        "Do not invent missing runtime details. Do not contradict this evidence. "
        "Answer in ELI's normal voice for the current reasoning mode, not as a raw diagnostic dump.\n\n"
        f"Current reasoning mode: {mode_label or 'unknown'}\n"
        f"Action: {action}\n\n"
        "DETERMINISTIC_EVIDENCE:\n"
        f"{evidence}\n"
    )


# Response surface contract v2: the final authority separating diagnostic evidence from the
# user-facing answer surface.

import os as _eli_os
import re as _eli_re
import json as _eli_json
import sqlite3 as _eli_sqlite3
import subprocess as _eli_subprocess
from pathlib import Path as _EliPath
from typing import Any as _EliAny, Mapping as _EliMapping


_RESPONSE_SURFACE_ACTIONS_V2 = {
    "SELF_REPORT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "MEMORY_STATUS",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
}


def _eli_project_root_v2() -> _EliPath:
    return _EliPath(__file__).resolve().parents[2]


def _eli_json_file_v2(path: _EliPath) -> dict:
    try:
        if path.exists():
            return _eli_json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    return {}


def _eli_runtime_snapshot_v2() -> dict:
    return _eli_json_file_v2(_eli_project_root_v2() / "artifacts" / "runtime_snapshot.json")


def _eli_settings_v2() -> dict:
    return _eli_json_file_v2(_eli_project_root_v2() / "config" / "settings.json")


def _eli_gpu_line_v2() -> str:
    try:
        out = _eli_subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=3,
        ).strip().splitlines()
        return out[0].strip() if out else "unavailable"
    except Exception as e:
        return f"unavailable ({type(e).__name__}: {e})"


def _eli_db_paths_v2() -> dict[str, _EliPath]:
    root = _eli_project_root_v2()
    return {
        "user_db": root / "artifacts" / "db" / "user.sqlite3",
        "agent_db": root / "artifacts" / "db" / "agent.sqlite3",
        "vector_index": root / "artifacts" / "vectors" / "index.faiss",
        "vector_meta": root / "artifacts" / "vectors" / "meta.pkl",
    }


def _eli_count_rows_v2(db: _EliPath) -> dict[str, int]:
    out: dict[str, int] = {}
    if not db.exists():
        return out
    try:
        con = _eli_sqlite3.connect(str(db))
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = [r[0] for r in cur.fetchall()]
        for name in names:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{name}"')
                out[name] = int(cur.fetchone()[0])
            except Exception:
                out[name] = -1
        con.close()
    except Exception:
        return out
    return out


def _eli_mode_label_v2(engine: _EliAny = None, kwargs: dict | None = None) -> str:
    kwargs = kwargs or {}
    kw_mode = str(kwargs.get("reasoning_mode") or "").strip()
    if kw_mode:
        return kw_mode

    for attr in (
        "reasoning_mode",
        "current_reasoning_mode",
        "_reasoning_mode",
        "mode",
        "current_mode",
        "selected_reasoning_mode",
        "reasoning_mode_key",
        "reasoning_mode_label",
    ):
        try:
            v = getattr(engine, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    return ""


def _eli_is_quick_v2(label: str) -> bool:
    low = str(label or "").lower()
    return low in {"quick", "quick mode", "⚡ quick"} or low.endswith(" quick")


def _eli_is_runtime_probe_v2(text: str) -> bool:
    low = str(text or "").lower()
    return bool(
        _eli_re.search(r"\b(model|context|ctx|gpu|gpu layers|n_gpu_layers|batch|threads|running on|runtime|everything)\b", low)
        and _eli_re.search(r"\b(who are you|what are you|running|model|context|gpu)\b", low)
    )


def _eli_is_casual_identity_v2(text: str) -> bool:
    low = str(text or "").lower().strip()
    has_identity = bool(_eli_re.search(r"\bwho are you\b|\bwho am i\b|\bwho i am\b", low))
    return has_identity and not _eli_is_runtime_probe_v2(low)


def _eli_wants_memory_internals_v2(text: str) -> bool:
    low = str(text or "").lower()
    return bool(
        _eli_re.search(r"\bhow\b.*\bmemory\b.*\bworks?\b", low)
        or _eli_re.search(r"\bmemory system\b.*\binternally\b", low)
        or _eli_re.search(r"\bwhich files\b|\bwhich db tables\b|\bwhich functions\b|\binternal(?:ly)?\b", low)
    )


def _eli_wants_personal_memory_v2(text: str) -> bool:
    low = str(text or "").lower()
    return bool(
        _eli_re.search(r"\bwhat do you know about me\b", low)
        or _eli_re.search(r"\bwhat.*remember.*about me\b", low)
        or _eli_re.search(r"\bfrom memory\b", low)
    ) and not _eli_wants_memory_internals_v2(low)


def _eli_runtime_truth_v2(mode_label: str = "") -> str:
    root = _eli_project_root_v2()
    snap = _eli_runtime_snapshot_v2()
    settings = _eli_settings_v2()

    model_path = (
        settings.get("model_path")
        or settings.get("gguf_model_path")
        or settings.get("selected_model")
        or "unknown"
    )

    return json.dumps(
        {
            "surface": "runtime_evidence",
            "project_root": str(root),
            "python": _eli_os.sys.version.split()[0],
            "platform": _eli_os.sys.platform,
            "configured": {
                "provider": settings.get("provider", "unknown"),
                "model_path": model_path,
                "n_ctx": settings.get("n_ctx", settings.get("context_size", "unknown")),
                "n_gpu_layers": settings.get("n_gpu_layers", settings.get("gpu_layers", "unknown")),
                "n_threads": settings.get("n_threads", settings.get("threads", "unknown")),
                "batch_size": settings.get("batch_size", settings.get("n_batch", "unknown")),
                "max_tokens": settings.get("max_tokens", "unknown"),
            },
            "effective": {
                "n_ctx": snap.get("n_ctx", "unknown"),
                "n_gpu_layers": snap.get("n_gpu_layers", "unknown"),
                "n_threads": snap.get("n_threads", "unknown"),
                "n_batch": snap.get("n_batch", "unknown"),
            },
            "gpu": _eli_gpu_line_v2(),
            "mode": mode_label or "",
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _eli_identity_answer_v2(mode_label: str = "") -> str:
    name = _eli_known_user_name_v2()
    return json.dumps(
        {
            "surface": "identity_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["local_model", "memory_db", "agents", "tools", "desktop_control"],
            },
            "user_identity_value_present": bool(name),
            "mode": str(mode_label or ""),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _eli_memory_internals_v2() -> str:
    paths = _eli_db_paths_v2()
    user_counts = _eli_count_rows_v2(paths["user_db"])
    agent_counts = _eli_count_rows_v2(paths["agent_db"])

    def table_block(title: str, db: _EliPath, counts: dict[str, int]) -> list[str]:
        out = [f"## {title}", f"path: {db}", f"exists: {db.exists()}", ""]
        for k in ("memories", "memories_fts", "conversation_turns", "conversations", "observations", "recall_log", "habits", "habit_rules", "habit_events", "failures", "improvements", "kg_entities", "kg_relations"):
            if k in counts:
                out.append(f"- {k}: {counts[k]}")
        return out

    lines = [
        "Memory internals report:",
        "",
        "## Practical layers",
        "1. SQLite durable store: long-term facts, conversation turns, observations, recall logs, habits, failures, improvements.",
        "2. FTS/vector retrieval: SQLite FTS tables plus FAISS/nomic embeddings for semantic recall.",
        "3. Cognition assembly: memory/context agents collect evidence, then the engine assembles a prompt for GGUF or deterministic response surfaces.",
        "",
    ]

    lines.extend(table_block("user.sqlite3", paths["user_db"], user_counts))
    lines.append("")
    lines.extend(table_block("agent.sqlite3", paths["agent_db"], agent_counts))
    lines.append("")
    lines.extend([
        "## Vector store",
        f"- index.faiss: {paths['vector_index']} exists={paths['vector_index'].exists()}",
        f"- meta.pkl: {paths['vector_meta']} exists={paths['vector_meta'].exists()}",
        "",
        "## Main files/functions",
        "- eli/memory/memory.py: Memory, get_memory, get_agent_memory, get_search_memory, recall/store helpers, schema setup.",
        "- eli/memory/vector_store.py: VectorStore, get_vector_store, FAISS-backed semantic search.",
        "- eli/cognition/agent_bus.py: MemoryAgent, ReflectionAgent, FileCodeAgent, IntrospectionBusAgent, KnowledgeGraphAgent, AgentBus.",
        "- eli/cognition/orchestrator.py: retrieval/planning/context assembly path.",
        "- eli/cognition/context_synthesiser.py: context packaging and recall filtering.",
        "- eli/cognition/user_info_builder.py: durable user-profile synthesis.",
        "- eli/memory/retrieval.py: shared per-turn retrieval (keyword, semantic, RAG, knowledge graph).",
        "- eli/runtime/personal_memory_surface.py / personal_memory_deep_response.py: user-facing memory summaries.",
    ])
    return "\n".join(lines)


def _inference_runtime_lines() -> str:
    """The live inference parameters, as plain lines of evidence.

    Asked "what is your current context window?", ELI answered "The provided
    evidence does not specify the current context window size." It was running
    at n_ctx=12192 and had written that number to runtime_snapshot.json at
    startup — the evidence bundle for EXPLAIN_COGNITION_RUNTIME simply had no
    field for it. The action is named for the runtime and described only the
    architecture: module paths, line numbers and table counts.

    Requested and effective are BOTH reported, because they diverge and the
    difference is the answer to most questions in this area: on that session the
    user asked for 99 GPU layers and got 8, which is why replies took minutes.
    """
    snap = _runtime_snapshot() or {}
    req = snap.get("requested") or {}
    eff = snap.get("effective") or {}

    def pick(key, fallback_top=True):
        for src in (eff, snap if fallback_top else {}):
            if src.get(key) not in (None, ""):
                return src.get(key)
        return "unknown"

    lines = ["Inference runtime (live, from the loaded model):"]
    model = snap.get("model_name") or snap.get("model_path") or "unknown"
    lines.append(f"- model: {model}")
    lines.append(f"- provider: {snap.get('provider', 'unknown')}")
    lines.append(f"- context window (n_ctx): {pick('n_ctx')}")
    if req.get("n_ctx") not in (None, "") and req.get("n_ctx") != eff.get("n_ctx"):
        lines.append(f"  (requested {req.get('n_ctx')}, reduced to fit VRAM)")
    lines.append(f"- GPU layers offloaded: {pick('n_gpu_layers')}")
    if req.get("n_gpu_layers") not in (None, "") and req.get("n_gpu_layers") != eff.get("n_gpu_layers"):
        lines.append(f"  (requested {req.get('n_gpu_layers')} — the rest run on CPU, which is the "
                     f"dominant cost of a slow reply)")
    lines.append(f"- batch: {pick('n_batch')}   threads: {pick('n_threads')}")
    lines.append(f"- load mode: {snap.get('load_mode', 'unknown')}")
    return "\n".join(lines)


def _eli_cognition_pipeline_v2(focus: str = "", question: str = "") -> str:
    focus_l = str(focus or "").strip().lower()
    try:
        from eli.runtime.inference_footprint import format_inference_footprint_report
    except Exception:
        format_inference_footprint_report = None  # type: ignore[assignment,misc]

    if focus_l in ("inference_ram", "latency_timing") and format_inference_footprint_report:
        return format_inference_footprint_report(
            include_latency_note=(focus_l == "latency_timing"),
            question=question,
        )

    runtime_block = ""
    try:
        runtime_block = _inference_runtime_lines()
    except Exception:
        log.debug("inference runtime block unavailable", exc_info=True)

    # A question about the inference runtime leads with the numbers, then keeps the architecture
    # description; both are required. Returning only the footprint (v2.4.16) dropped "Cognition
    # pipeline" / Router from reports the tests and operator rely on.
    if focus_l == "inference_runtime":
        parts = []
        if runtime_block:
            parts.append(runtime_block)
        if format_inference_footprint_report:
            try:
                parts.append(format_inference_footprint_report(question=question))
            except Exception:
                log.debug("inference footprint unavailable", exc_info=True)
        parts.append(_COGNITION_PIPELINE_TEXT)
        return "\n\n".join(p for p in parts if p)

    return ((runtime_block + "\n\n") if runtime_block else "") + _COGNITION_PIPELINE_TEXT


_COGNITION_PIPELINE_TEXT = """Cognition pipeline, input to output:

1. GUI / voice capture
- Text input enters through eli/gui/eli_pro_audio_gui_v2_0.py.
- Voice input is captured through the STT/audio path, then normalised before it is sent into cognition.

2. Input normalisation
- The GUI strips attachment markers, file/PDF/image tags, and applies any voice/STT cleanup.
- The current reasoning mode is passed as reasoning_mode=... into CognitiveEngine.process.

3. CognitiveEngine.process
- Main engine path lives in eli/kernel/engine.py.
- This is the canonical cognition entry point for normal chat.

4. Router
- eli/execution/router_enhanced.py classifies the text into action, args, confidence, and meta.
- Examples: SELF_REPORT, RUNTIME_AUDIT, IMPORT_AUDIT, GENERATE_SCRIPT, EXPLAIN_COGNITION_RUNTIME, PERSONAL_MEMORY_DEEP_EXPLAIN.

5. Grounding / response-surface gate
- eli/runtime/deterministic_grounding_gate.py decides whether a request needs deterministic evidence.
- Quick mode may return raw deterministic reports.
- Non-quick modes must not receive raw dumps, but they still must not invent evidence.

6. Agent selection
- eli/cognition/agent_bus.py selects relevant agents.
- Typical agents include memory, file_code, reflection, habit, voice, introspection, self_improvement, plugin, proactive, and knowledge graph.

7. Evidence gathering
- Memory agent reads SQLite/FTS/vector memory.
- File/code agent inspects project files.
- Introspection agent reads runtime/model/cognition state.
- Reflection/self-improvement agents read recent failures, observations, improvements.

8. Context assembly
- The engine/orchestrator merges evidence into a compact prompt context.
- This is where prompt bloat and truncation can happen if evidence is too large.

9. Inference broker / GGUF handoff
- eli/cognition/gguf_inference.py formats the prompt for the loaded GGUF model.
- Current observed effective runtime is read from artifacts/runtime_snapshot.json.

10. Output governance
- Response governance/sanitiser removes known bad surface patterns and applies reasoning-mode contracts.
- This must not expose private scratchpad, hidden branch scoring, or fake confidence.

11. GUI append + TTS
- The final visible response is appended to the chat display.
- If voice is enabled, TTS speaks the response.

12. Memory/writeback
- Conversation turns, observations, summaries, recall logs, and some durable facts may be written back into SQLite.
- This is why synthetic diagnostic prompts must not be passed as fake user input: they poison memory.
"""


def _eli_runtime_audit_v2() -> str:
    root = _eli_project_root_v2()
    snap = _eli_runtime_snapshot_v2()
    settings = _eli_settings_v2()
    paths = _eli_db_paths_v2()

    files = [
        root / "eli" / "kernel" / "engine.py",
        root / "eli" / "cognition" / "gguf_inference.py",
        root / "eli" / "execution" / "router_enhanced.py",
        root / "eli" / "execution" / "executor_enhanced.py",
        root / "eli" / "runtime" / "deterministic_grounding_gate.py",
        root / "eli" / "runtime" / "generated_script_guard.py",
        root / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py",
        root / "eli" / "core" / "runtime_settings.py",
    ]

    lines = [
        "Runtime audit:",
        "",
        "## Effective runtime",
        f"- project_root: {root}",
        f"- configured ctx: {settings.get('n_ctx', settings.get('context_size', 'unknown'))}",
        f"- effective ctx: {snap.get('n_ctx', 'unknown')}",
        f"- configured gpu layers: {settings.get('n_gpu_layers', settings.get('gpu_layers', 'unknown'))}",
        f"- effective gpu layers: {snap.get('n_gpu_layers', 'unknown')}",
        f"- effective batch: {snap.get('n_batch', 'unknown')}",
        f"- gpu: {_eli_gpu_line_v2()}",
        "",
        "## File presence",
    ]

    for f in files:
        lines.append(f"- {f.relative_to(root)}: exists={f.exists()} size={f.stat().st_size if f.exists() else 0}")

    lines.extend([
        "",
        "## Databases/vector store",
        f"- user_db: {paths['user_db']} exists={paths['user_db'].exists()}",
        f"- agent_db: {paths['agent_db']} exists={paths['agent_db'].exists()}",
        f"- vector_index: {paths['vector_index']} exists={paths['vector_index'].exists()}",
        f"- vector_meta: {paths['vector_meta']} exists={paths['vector_meta'].exists()}",
        "",
        "## Known architectural debt from current logs",
        "- router_enhanced.py still has stacked late wrappers around route/route_intent.",
        "- executor_enhanced.py still has stacked late wrappers around execute/execute_action.",
        "- runtime_settings.py has duplicate load_settings definitions/wrappers.",
        "- non-quick audit requests must not be delegated to GGUF without deterministic evidence.",
        "- personal-memory questions must not trigger DB schema dumps unless the user explicitly asks for internals.",
        "",
        "## Actual root cause",
        "The main failure is not missing imports. It is response-surface conflation: routing, deterministic evidence, memory internals, personal memory, and normal identity/persona answers were allowed to collapse into each other.",
    ])
    return "\n".join(lines)


def _eli_last_response_confidence_v2(mode_label: str = "") -> str:
    """Real confidence assessment of the actual previous response — this used
    to return a fixed template regardless of what happened. Reuses
    ``last_trace.load_last_trace()`` + ``control_contracts._trace_text()``,
    the same real mechanism already used for "what was your last message"."""
    try:
        from eli.runtime.last_trace import load_last_trace
        from eli.runtime.control_contracts import _trace_text
        trace = load_last_trace() or {}
        if trace:
            return _trace_text(trace)
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    return (
        "Confidence assessment: no trace is available for the previous response "
        "(nothing was recorded yet this session, or this is the first turn) — I "
        "don't have a real basis to assess it, so I'm telling you that rather "
        "than guessing."
    )


def _eli_failure_analysis_v2() -> str:
    return (
        "Recent failure analysis:\n\n"
        "Actual root cause: response-surface contamination.\n\n"
        "1. SELF_REPORT was too broad. Casual identity prompts were treated like runtime diagnostics.\n"
        "2. Personal memory and memory internals were conflated. 'What do you know about me?' should summarise user memory, not print DB tables.\n"
        "3. Non-quick grounded actions were delegated to the model without guaranteed deterministic evidence. That creates slow, truncated, sometimes invented audits.\n"
        "4. The wrapper stack is too deep. router_enhanced.py and executor_enhanced.py have repeated late wrappers, so the last wrapper wins and earlier intent contracts become fragile.\n"
        "5. Generated-script handling needed deterministic safe paths for common scripts. The SQLite table-count script and GPU memory script should bypass free-form GGUF generation.\n\n"
        "So no: the core failure is not that the model cannot answer. The failure is that the runtime lets diagnostic actions, chat persona, memory reports, and script generation share the same dirty corridor."
    )


def _render_v2(action: str, args: _EliMapping[str, _EliAny] | None = None, user_input: str = "", mode_label: str = "") -> str:
    a = str(action or "").upper()
    text = str(user_input or "")

    if a == "SELF_REPORT":
        if _eli_is_casual_identity_v2(text):
            return _eli_identity_answer_v2(mode_label)
        return _eli_runtime_truth_v2(mode_label=mode_label)

    if a == "RUNTIME_AUDIT":
        return _eli_runtime_audit_v2()

    if a == "EXPLAIN_COGNITION_RUNTIME":
        # The router already decides this ("diagnostic_focus": "inference_runtime"
        # for a question about the context window / model / GPU) — pass it through
        # instead of returning the same architecture text for every question.
        return _eli_cognition_pipeline_v2(
            str((args or {}).get("diagnostic_focus") or ""),
            question=text,
        )

    if a in {"EXPLAIN_MEMORY_RUNTIME", "MEMORY_STATUS", "PERSONAL_MEMORY_DEEP_EXPLAIN"}:
        try:
            from eli.runtime.inference_footprint import (
                format_inference_footprint_report,
                is_inference_ram_question,
            )
            if is_inference_ram_question(text):
                return format_inference_footprint_report(
                    include_latency_note=True,
                    question=text,
                )
        except Exception:
            log.debug("inference RAM redirect unavailable", exc_info=True)
        if _eli_wants_personal_memory_v2(text):
            return _eli_personal_memory_answer_v2(mode_label)
        return _eli_memory_internals_v2()

    if a == "EXPLAIN_LAST_RESPONSE":
        return _eli_last_response_confidence_v2(mode_label)

    if a in {"SELF_ANALYZE", "SELF_IMPROVE"}:
        return _eli_failure_analysis_v2()

    return json.dumps(
        {
            "surface": "missing_deterministic_renderer",
            "action": a,
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )





# Personal memory noise filter v3: overrides the v2 sampler/name handling without touching routing.

_PERSONAL_MEMORY_NOISE_V3 = (
    "Reflection (24h):",
    "Session context:",
    "SYNTHESISE_FROM_DETERMINISTIC_EVIDENCE",
    "runtime_truth_evidence",
    "Memory internals report:",
    "Database:",
    "table                                                        rows",
    "Capability inventory updated",
    "[news synthesis offline:",
    "[HackerNews/",
    "[Reddit/",
    "HackerNews/tech",
    "Reddit/r/",
    "news_articles",
    "news_fts",
    "Generated Python script failed syntax validation",
    "What imports are failing",
    "Run a full runtime audit",
    "Who are you and what are you actually running",
    "Explain exactly how your memory system works internally",
    "Explain your cognition pipeline",
    "What's your confidence",
    "quarantine_",
    "sqlite_master",
)

_PERSONAL_MEMORY_POSITIVE_HINTS_V3 = (
    "user wants",
    "user prefers",
    "user is",
    "user has",
    "user uses",
    "user works",
    "eli",
    "eli_v2_0",
    "local assistant",
    "gguf",
    "memory",
    "persona",
    "physics",
    "simulation",
    "latex",
    "direct",
    "truth",
    "no lies",
    "bullshit",
    "runtime",
    "gpu",
    "linux",
)


def _eli_is_bad_personal_memory_row_v3(s: str) -> bool:
    if not s or len(s.strip()) < 12:
        return True

    low = s.lower()
    if any(n.lower() in low for n in _PERSONAL_MEMORY_NOISE_V3):
        return True

    # Reject rows that are just recent prompt echoes rather than remembered facts.
    if low.endswith("?") and not any(h in low for h in ("prefers", "wants", "uses", "works", "has")):
        return True

    # Reject generic operational traces.
    if low.startswith(("ok ", "route:", "input:", "mode:", "render_preview:", "script generated:")):
        return True

    return False


def _eli_memory_fact_score_v3(s: str) -> int:
    low = s.lower()
    score = 0

    for hint in _PERSONAL_MEMORY_POSITIVE_HINTS_V3:
        if hint in low:
            score += 2

    # Prefer durable preference/project facts over transient logs.
    if any(k in low for k in ("prefers", "wants", "does not want", "from now on", "moving forward")):
        score += 4

    if any(k in low for k in ("currently", "today", "last 24h", "recent", "conversation volume")):
        score -= 2

    if any(k in low for k in ("news", "hackernews", "reddit", "generated script", "runtime truth")):
        score -= 5

    return score


def _eli_known_user_name_v2() -> str:  # type: ignore[override]
    try:
        from eli.kernel.state import get_user_name as _eli_state_get_user_name
        stored = str(_eli_state_get_user_name("") or "").strip()
        if stored:
            return stored
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    samples = _eli_sample_memory_texts_v2(200)
    blob = "\n".join(samples)

    m = _eli_re.search(
        r"(?:preferred name|user'?s preferred name|name)\s*[:=]\s*([A-Za-z][A-Za-z0-9 _.-]{1,40})",
        blob,
        _eli_re.I,
    )
    if m:
        return m.group(1).strip()

    env_user = str(_eli_os.environ.get("USER", "")).strip()
    if env_user:
        return env_user[:1].upper() + env_user[1:]

    return "the local user"


# Personal memory fact-clause filter v4: replaces broad row sampling with stable user-fact
# extraction.

_PERSONAL_MEMORY_ROW_REJECT_V4 = (
    "conversation volume:",
    "top topics:",
    "a full runtime audit has been requested",
    "passed agents:",
    "failed agents:",
    "runtime truth report",
    "configured/requested:",
    "effective loaded snapshot:",
    "i'm running the",
    "i am currently running",
    "my identity emerges from memory",
    "my runtime evidence is stored",
    "model is custom_gguf",
    "context size of",
    "gpu layers",
    "n_ctx",
    "n_gpu_layers",
    "n_batch",
    "grounded user identity:",
    "memory internals report:",
    "database:",
    "hackernews",
    "reddit/",
    "news synthesis",
    "generated python script failed",
    "script generated:",
    "route:",
    "render_preview:",
    "input:",
    "mode:",
    "synthesise_from_deterministic_evidence",
)

_PERSONAL_MEMORY_CLAUSE_REJECT_V4 = (
    "conversation volume",
    "top topics",
    "full runtime audit",
    "passed agents",
    "failed agents",
    "runtime truth",
    "configured/requested",
    "effective loaded",
    "gpu layers",
    "context size",
    "model is",
    "i'm running",
    "i am running",
    "my runtime",
    "hackernews",
    "reddit",
    "news synthesis",
    "generated python script",
    "route:",
    "input:",
    "render_preview",
)

_PERSONAL_MEMORY_FACT_PATTERNS_V4 = (
    r"\buser\s+(?:prefers|wants|does not want|doesn't want|has|uses|is using|is running|is|works|values|likes|confirmed|completed|asked|requests)\b",
    r"\buser'?s\s+(?:preferred name|name|tone|preference|project|hardware|runtime|model|workflow)\b",
    r"\bpreferred_name\s*[:=]\s*",
    r"\bname\s*[:=]\s*[A-Za-z][A-Za-z0-9 _.\-]{1,40}",
)


def _eli_row_is_noise_v4(s: str) -> bool:
    low = " ".join(str(s or "").lower().split())
    if not low:
        return True
    return any(bad in low for bad in _PERSONAL_MEMORY_ROW_REJECT_V4)


def _eli_clause_is_noise_v4(s: str) -> bool:
    low = " ".join(str(s or "").lower().split())
    if not low or len(low) < 16:
        return True
    return any(bad in low for bad in _PERSONAL_MEMORY_CLAUSE_REJECT_V4)


def _eli_clause_is_user_fact_v4(s: str) -> bool:
    low = " ".join(str(s or "").lower().split())
    if _eli_clause_is_noise_v4(low):
        return False
    return any(_eli_re.search(pat, low) for pat in _PERSONAL_MEMORY_FACT_PATTERNS_V4)


def _eli_split_fact_clauses_v4(s: str) -> list[str]:
    # Split long assistant summaries into smaller fact candidates.
    raw = str(s or "")
    raw = raw.replace(" | ", ". ")
    raw = raw.replace(" - ", ". ")
    raw = raw.replace("; ", ". ")
    raw = raw.replace("\n", ". ")

    parts = _eli_re.split(r"(?<=[.!?])\s+|\s+\d+\.\s+", raw)
    out: list[str] = []

    for part in parts:
        part = " ".join(part.strip(" -•\t\r\n").split())
        if not part:
            continue

        # Extract embedded "User ..." facts from longer clauses (name-agnostic).
        hits = _eli_re.findall(
            r"\bUser\s+(?:prefers|wants|does not want|doesn't want|has|uses|is using|is running|is|works|values|likes|confirmed|completed|asked|requests)\b.{0,220}",
            part,
            flags=_eli_re.I,
        )
        if hits:
            for h in hits:
                h = " ".join(h.strip(" .;:-").split())
                if _eli_clause_is_user_fact_v4(h):
                    out.append(h[:260])
            continue

        if _eli_clause_is_user_fact_v4(part):
            out.append(part[:260])

    return out


def _eli_memory_fact_score_v4(s: str, source_table: str = "") -> int:
    low = s.lower()
    score = 0

    if source_table == "memories":
        score += 8
    elif source_table == "observations":
        score += 4
    elif source_table in {"conversation_turns", "conversations"}:
        score -= 3

    if any(k in low for k in ("prefers", "does not want", "doesn't want", "wants", "values")):
        score += 6
    if any(k in low for k in ("eli", "eli_v2_0", "local assistant", "gguf", "runtime", "memory", "persona")):
        score += 3
    if any(k in low for k in ("physics", "simulation", "latex", "paper")):
        score += 3
    if any(k in low for k in ("ubuntu", "fedora", "linux", "gpu", "nvidia", "wine", "steam")):
        score += 2

    if any(k in low for k in ("recent", "last 24", "today", "currently")):
        score -= 2

    return score


# Personal memory durable-profile filter v5: rejects transient interaction facts and keeps durable
# user-profile facts only.

_PERSONAL_MEMORY_TRANSIENT_REJECT_V5 = (
    "binary file:",
    "[binary file:",
    "user question:",
    "what's this",
    "whats this",
    "user has loaded",
    "loaded the following file",
    "file/folder content",
    "user is asking",
    "asking for help",
    "without more context",
    "phrase or idiom",
    "i've detected",
    "i have detected",
    "detected a few patterns",
    "recently:",
    "last 24 hours",
    "conversation volume",
    "top topics",
    "active topics",
    "session context",
    "reflection (24h)",
    "runtime truth report",
    "full runtime audit",
    "passed agents",
    "failed agents",
    "hackernews",
    "reddit",
    "news synthesis",
    "generated python script",
    "script generated",
    "route:",
    "render_preview",
    "bad_markers",
)

_PERSONAL_MEMORY_DURABLE_PATTERNS_V5 = (
    r"\buser\s+(?:prefers|wants|does not want|doesn't want|values|likes|uses|is using|is running|works on|is working on|is actively working on|is developing|is building|is debugging|is tuning|confirmed|completed|has completed|has successfully)\b",
    r"\buser'?s\s+(?:preferred name|name|tone|preference|preferences|project|projects|hardware|workflow|style)\b",
    r"\bpreferred_name\s*[:=]\s*",
    r"\bname\s*[:=]\s*[A-Za-z][A-Za-z0-9 _.\-]{1,40}",
)


def _eli_v5_norm(s: str) -> str:
    return " ".join(str(s or "").strip().split())


def _eli_v5_low(s: str) -> str:
    return _eli_v5_norm(s).lower()


def _eli_clause_is_noise_v5(s: str) -> bool:
    low = _eli_v5_low(s)
    if not low or len(low) < 18:
        return True
    if any(bad in low for bad in _PERSONAL_MEMORY_TRANSIENT_REJECT_V5):
        return True
    if any(bad in low for bad in _PERSONAL_MEMORY_ROW_REJECT_V4):
        return True
    if any(bad in low for bad in _PERSONAL_MEMORY_CLAUSE_REJECT_V4):
        return True
    return False


def _eli_clause_is_user_fact_v5(s: str) -> bool:
    low = _eli_v5_low(s)
    if _eli_clause_is_noise_v5(low):
        return False

    # Explicitly reject transient verbs even if they mention "user".
    if _eli_re.search(r"\b(?:user|current user|active user)\s+(?:asked|asks|is asking|requested|requests|said|sent|uploaded|loaded|provided)\b", low):
        return False

    return any(_eli_re.search(pat, low, flags=_eli_re.I) for pat in _PERSONAL_MEMORY_DURABLE_PATTERNS_V5)


def _eli_split_fact_clauses_v5(s: str) -> list[str]:
    raw = str(s or "")
    raw = raw.replace(" | ", ". ")
    raw = raw.replace(" - ", ". ")
    raw = raw.replace("; ", ". ")
    raw = raw.replace("\n", ". ")

    parts = _eli_re.split(r"(?<=[.!?])\s+|\s+\d+\.\s+", raw)
    out: list[str] = []

    durable_regex = (
        r"\bUser\s+"
        r"(?:prefers|wants|does not want|doesn't want|values|likes|uses|is using|is running|"
        r"works on|is working on|is actively working on|is developing|is building|is debugging|"
        r"is tuning|confirmed|completed|has completed|has successfully)\b.{0,220}"
    )

    for part in parts:
        part = _eli_v5_norm(part.strip(" -•\t\r\n"))
        if not part:
            continue

        hits = _eli_re.findall(durable_regex, part, flags=_eli_re.I)
        if hits:
            for h in hits:
                h = _eli_v5_norm(h.strip(" .;:-"))
                if _eli_clause_is_user_fact_v5(h):
                    out.append(h[:260])
            continue

        if _eli_clause_is_user_fact_v5(part):
            out.append(part[:260])

    return out


def _eli_tokens_v5(s: str) -> set[str]:
    stop = {
        "user",   "is", "are", "the", "and", "or", "to", "of", "a", "an",
        "with", "for", "on", "in", "their", "his", "her", "this", "that", "currently",
    }
    return {
        w for w in _eli_re.sub(r"[^a-z0-9]+", " ", s.lower()).split()
        if len(w) > 2 and w not in stop
    }


def _eli_is_near_duplicate_v5(candidate: str, existing: list[str]) -> bool:
    c = _eli_tokens_v5(candidate)
    if not c:
        return True

    for old in existing:
        o = _eli_tokens_v5(old)
        if not o:
            continue
        overlap = len(c & o) / max(1, min(len(c), len(o)))
        if overlap >= 0.72:
            return True

    return False


def _eli_memory_fact_score_v5(s: str, source_table: str = "") -> int:
    low = s.lower()
    score = 0

    if source_table == "memories":
        score += 10
    elif source_table == "observations":
        score += 6
    else:
        score -= 8

    if any(k in low for k in ("prefers", "does not want", "doesn't want", "wants", "values")):
        score += 8
    if any(k in low for k in ("eli", "eli_v2_0", "local assistant", "gguf", "memory", "persona", "cognition", "orchestrator")):
        score += 5
    if any(k in low for k in ("physics", "simulation", "latex", "paper")):
        score += 4
    if any(k in low for k in ("ubuntu", "fedora", "linux", "gpu", "nvidia", "wine", "steam")):
        score += 3

    if any(k in low for k in ("recent", "last 24", "today", "currently", "loaded", "asked", "asking")):
        score -= 6

    return score


# Personal memory clause-first profile filter v6: fixes v5 over-filtering by extracting valid
# durable clauses before rejecting mixed/noisy rows. Also reads durable profile files when present.

_PERSONAL_MEMORY_HARD_ROW_REJECT_V6 = (
    "runtime truth report:",
    "configured/requested:",
    "effective loaded snapshot:",
    "memory internals report:",
    "database:",
    "table                                                        rows",
    "hackernews",
    "reddit",
    "news synthesis",
    "generated python script failed",
    "script generated:",
    "render_preview:",
    "bad_markers:",
    "route:",
    "traceback",
)

_PERSONAL_MEMORY_CLAUSE_REJECT_V6 = (
    "binary file:",
    "[binary file:",
    "user question:",
    "what's this",
    "whats this",
    "user has loaded",
    "loaded the following file",
    "file/folder content",
    "user is asking",
    "asking for help",
    "without more context",
    "phrase or idiom",
    "i've detected",
    "i have detected",
    "detected a few patterns",
    "conversation volume",
    "top topics",
    "active topics",
    "session context",
    "reflection (24h)",
    "a full runtime audit",
    "passed agents",
    "failed agents",
    "i'm running the",
    "i am currently running",
    "my identity emerges",
    "my runtime evidence",
    "model is custom_gguf",
    "context size of",
    "gpu layers",
    "n_ctx",
    "n_gpu_layers",
    "n_batch",
    "who are you and what are you actually running",
    "explain exactly how your memory system works",
    "explain your cognition pipeline",
    "what imports are failing",
)

_PERSONAL_MEMORY_FACT_PATTERNS_V6 = (
    r"\b(?:user|current user|active user)\s+(?:prefers|wants|does not want|doesn't want|values|likes|uses|is using|is running|works on|is working on|is actively working on|is developing|is building|is debugging|is tuning|confirmed|completed|has completed|has successfully|has|is)\b",
    r"\b(?:preferred_name|preferred name|name)\s*[:=]\s*(?:user|current user)",
    r"\b(?:tone|preference|preferences|workflow|project|projects|hardware|runtime|research|theory|simulation)\b.{0,80}\b(?:user|current user|active user)\b",
)

_PERSONAL_MEMORY_PROFILE_FILES_V6 = (
    "artifacts/user_info.txt",
    "artifacts/user_info.md",
    "artifacts/user_profile.txt",
    "artifacts/user_profile.md",
    "artifacts/profile.txt",
    "eli/cognition/persona.auto.txt",
)


def _eli_v6_norm(s: str) -> str:
    return " ".join(str(s or "").replace("\x00", " ").split())


def _eli_v6_is_hard_bad_row(s: str) -> bool:
    low = _eli_v6_norm(s).lower()
    return any(bad in low for bad in _PERSONAL_MEMORY_HARD_ROW_REJECT_V6)


def _eli_v6_is_bad_clause(s: str) -> bool:
    low = _eli_v6_norm(s).lower()
    if not low or len(low) < 12:
        return True

    if any(bad in low for bad in _PERSONAL_MEMORY_CLAUSE_REJECT_V6):
        return True

    # Reject direct event/request rows.
    if _eli_re.search(r"\b(?:user|current user|active user)\s+(?:asked|asks|is asking|requested|requests|said|sent|uploaded|loaded|provided|opened|ran|runs|typed)\b", low):
        return True

    # Reject rows that are obviously assistant self-reports, not user facts.
    if _eli_re.search(r"\b(?:i am|i'm|my model|my runtime|my confidence|my response)\b", low):
        return True

    return False


def _eli_v6_is_fact_clause(s: str) -> bool:
    low = _eli_v6_norm(s).lower()
    if _eli_v6_is_bad_clause(low):
        return False
    return any(_eli_re.search(pat, low, flags=_eli_re.I) for pat in _PERSONAL_MEMORY_FACT_PATTERNS_V6)


def _eli_v6_split_clauses(raw: str) -> list[str]:
    text = str(raw or "")
    text = text.replace(" | ", ". ")
    text = text.replace("\n", ". ")
    text = text.replace("•", ". ")
    text = text.replace(" - ", ". ")
    text = text.replace("; ", ". ")

    rough = _eli_re.split(r"(?<=[.!?])\s+|\s+\d+\.\s+|\s{2,}", text)
    clauses: list[str] = []

    durable_hit = (
        r"\bUser\s+"
        r"(?:prefers|wants|does not want|doesn't want|values|likes|uses|is using|is running|"
        r"works on|is working on|is actively working on|is developing|is building|is debugging|"
        r"is tuning|confirmed|completed|has completed|has successfully|has|is)\b"
        r".{0,260}"
    )

    for part in rough:
        part = _eli_v6_norm(part.strip(" -•\t\r\n"))
        if not part:
            continue

        matches = _eli_re.findall(durable_hit, part, flags=_eli_re.I)
        if matches:
            for m in matches:
                m = _eli_v6_norm(m.strip(" .;:-"))
                if _eli_v6_is_fact_clause(m):
                    clauses.append(m[:280])
        elif _eli_v6_is_fact_clause(part):
            clauses.append(part[:280])

    return clauses


def _eli_v6_tokens(s: str) -> set[str]:
    stop = {
        "user",   "is", "are", "the", "and", "or", "to", "of", "a", "an",
        "with", "for", "on", "in", "their", "his", "her", "this", "that", "currently",
        "prefers", "wants", "likes", "values", "working", "works",
    }
    return {
        w for w in _eli_re.sub(r"[^a-z0-9]+", " ", s.lower()).split()
        if len(w) > 2 and w not in stop
    }


def _eli_v6_near_dup(candidate: str, existing: list[str]) -> bool:
    c = _eli_v6_tokens(candidate)
    if not c:
        return True
    for old in existing:
        o = _eli_v6_tokens(old)
        if not o:
            continue
        overlap = len(c & o) / max(1, min(len(c), len(o)))
        if overlap >= 0.78:
            return True
    return False


def _eli_v6_score_fact(s: str, source: str = "") -> int:
    low = s.lower()
    score = 0

    if source == "profile_file":
        score += 18
    elif source == "memories":
        score += 12
    elif source == "observations":
        score += 8
    elif source == "user_patterns":
        score += 5
    else:
        score += 1

    if any(k in low for k in ("prefers", "does not want", "doesn't want", "wants", "values")):
        score += 10
    if any(k in low for k in ("eli", "eli_v2_0", "local assistant", "gguf", "memory", "persona", "cognition", "orchestrator", "router", "executor")):
        score += 6
    if any(k in low for k in ("physics", "simulation", "latex", "paper", "field", "theory")):
        score += 5
    if any(k in low for k in ("ubuntu", "fedora", "linux", "gpu", "nvidia", "wine", "steam", "terminal", "bash", "commands")):
        score += 5
    if any(k in low for k in ("recent", "last 24", "today", "loaded", "asked", "asking", "uploaded")):
        score -= 8

    return score


def _eli_v6_profile_file_candidates() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    root = _EliPath(__file__).resolve().parents[2]

    for rel in _PERSONAL_MEMORY_PROFILE_FILES_V6:
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for clause in _eli_v6_split_clauses(raw):
            if _eli_v6_is_fact_clause(clause):
                out.append((_eli_v6_score_fact(clause, "profile_file"), clause))

    return out


def _eli_sample_memory_texts_v2(limit: int = 80) -> list[str]:  # type: ignore[override]
    candidates: list[tuple[int, str]] = []
    candidates.extend(_eli_v6_profile_file_candidates())

    db = _eli_db_paths_v2()["user_db"]
    if db.exists():
        try:
            con = _eli_sqlite3.connect(str(db))
            cur = con.cursor()

            table_plan = [
                ("memories", 2500),
                ("observations", 1200),
                ("user_patterns", 500),
            ]

            for table, n in table_plan:
                try:
                    cur.execute(f"PRAGMA table_info({table})")
                    cols = [r[1] for r in cur.fetchall()]
                    wanted = [
                        c for c in (
                            "text", "value", "content", "observation", "details",
                            "pattern_data", "pattern_type"
                        )
                        if c in cols
                    ]
                    if not wanted:
                        continue

                    expr = " || ' ' || ".join([f"COALESCE({c}, '')" for c in wanted])
                    ts_col = "ts" if "ts" in cols else ("timestamp" if "timestamp" in cols else "rowid")

                    cur.execute(
                        f"SELECT {expr} AS blob FROM {table} "
                        f"ORDER BY {ts_col} DESC LIMIT {int(n)}"
                    )

                    for (blob,) in cur.fetchall():
                        row = _eli_v6_norm(blob)
                        if not row or _eli_v6_is_hard_bad_row(row):
                            continue

                        for clause in _eli_v6_split_clauses(row):
                            if _eli_v6_is_fact_clause(clause):
                                candidates.append((_eli_v6_score_fact(clause, table), clause))

                except Exception:
                    continue

            con.close()
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    ranked = sorted(candidates, key=lambda x: x[0], reverse=True)

    clean: list[str] = []
    for score, clause in ranked:
        clause = _eli_v6_norm(clause)
        if score < 4:
            continue
        if not clause:
            continue
        if _eli_v6_near_dup(clause, clean):
            continue
        clean.append(clause)
        if len(clean) >= limit:
            break

    return clean


# Dynamic user profile filter v8: portable profile surface with no shipped/static user profile
# files. Reads durable facts only from the local installation's own DB/memory.

import getpass as _eli_getpass
import re as _eli_v8_re
import sqlite3 as _eli_v8_sqlite3
from pathlib import Path as _EliV8Path


def _eli_v8_project_root() -> _EliV8Path:
    try:
        return _EliV8Path(__file__).resolve().parents[2]
    except Exception:
        return _EliV8Path.cwd()


def _eli_v8_db_paths() -> list[_EliV8Path]:
    root = _eli_v8_project_root()
    return [
        root / "artifacts" / "db" / "user.sqlite3",
        root / "artifacts" / "db" / "agent.sqlite3",
    ]


def _eli_v8_norm(s: object) -> str:
    text = str(s or "")
    text = text.replace("\x00", " ")
    text = _eli_v8_re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n-•")
    text = _eli_v8_re.sub(r"\.{2,}$", ".", text)
    text = _eli_v8_re.sub(r"\s+\.", ".", text)
    return text.strip()


_ELI_V8_TRANSIENT_REJECT = (
    "runtime truth report",
    "configured/requested",
    "effective loaded snapshot",
    "conversation volume",
    "top topics",
    "session context",
    "active topics",
    "hackernews",
    "reddit/r/",
    "news synthesis",
    "generated python script failed",
    "full runtime audit",
    "passed agents",
    "failed agents",
    "memory internals report",
    "database:",
    "table rows",
    "binary file:",
    "[binary file:",
    "user question:",
    "what's this",
    "whats this",
    "without more context",
    "phrase or idiom",
    "synthesise_from_deterministic_evidence",
    "n_ctx",
    "n_gpu_layers",
    "gpu layers",
    "model_path",
    "custom_gguf",
)


def _eli_v8_reject(text: str) -> bool:
    low = text.lower()
    if len(text) < 8 or len(text) > 450:
        return True
    return any(marker in low for marker in _ELI_V8_TRANSIENT_REJECT)


def _eli_v8_table_columns(cur, table: str) -> list[str]:
    try:
        return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _eli_v8_collect_db_texts(limit_per_table: int = 600) -> list[str]:
    texts: list[str] = []

    tables = (
        "memories",
        "observations",
        "user_patterns",
        "corrections",
        "improvements",
    )

    preferred_cols = (
        "text",
        "value",
        "content",
        "observation",
        "details",
        "pattern_data",
        "corrected",
        "description",
        "title",
        "tags",
        "kind",
    )

    for db in _eli_v8_db_paths():
        if not db.exists():
            continue

        try:
            con = _eli_v8_sqlite3.connect(str(db))
            cur = con.cursor()
        except Exception:
            continue

        try:
            existing = {
                row[0]
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

            for table in tables:
                if table not in existing:
                    continue

                cols = _eli_v8_table_columns(cur, table)
                use_cols = [c for c in preferred_cols if c in cols]
                if not use_cols:
                    continue

                col_sql = ", ".join(use_cols)
                try:
                    rows = cur.execute(
                        f"SELECT {col_sql} FROM {table} ORDER BY rowid DESC LIMIT ?",
                        (limit_per_table,),
                    ).fetchall()
                except Exception:
                    continue

                for row in rows:
                    for value in row:
                        text = _eli_v8_norm(value)
                        if text and not _eli_v8_reject(text):
                            texts.append(text)

        finally:
            try:
                con.close()
            except Exception:
                _SWLOG.debug("suppressed exception", exc_info=True)

    return texts


def _eli_v8_extract_fact(text: str) -> str | None:
    t = _eli_v8_norm(text)
    low = t.lower()

    # Keep explicit durable user facts only.
    durable_patterns = (
        r"\buser'?s preferred name is\b",
        r"\bpreferred name\b",
        r"\buser'?s name is\b",
        r"\buser prefers\b",
        r"\buser values\b",
        r"\buser dislikes\b",
        r"\buser wants\b",
        r"\buser works on\b",
        r"\buser is working on\b",
        r"\buser is actively\b",
        r"\buser is developing\b",
        r"\buser uses\b",
        r"\buser runs\b",
        r"\buser has\b",
        r"\buser asked to remember\b",
    )

    if not any(_eli_v8_re.search(p, low) for p in durable_patterns):
        return None

    # Normalise common forms without hard-coding a shipped identity.
    t = _eli_v8_re.sub(r"^User's preferred name is\s+", "Preferred name: ", t, flags=_eli_v8_re.I)
    t = _eli_v8_re.sub(r"^User preferred name is\s+", "Preferred name: ", t, flags=_eli_v8_re.I)
    t = _eli_v8_re.sub(r"^User's name is\s+", "Name: ", t, flags=_eli_v8_re.I)

    t = _eli_v8_norm(t)
    if _eli_v8_reject(t):
        return None

    return t


def _eli_v8_bucket_for_fact(fact: str) -> str:
    low = fact.lower()

    if low.startswith("name:") or low.startswith("preferred name:") or "preferred name" in low:
        return "identity"

    if any(k in low for k in (
        "prefers", "values", "dislikes", "direct", "truth", "honest",
        "step-by-step", "diagnostic", "audit", "thorough", "meticulous",
        "vague", "commands", "bash", "terminal"
    )):
        return "tone and working style"

    if any(k in low for k in (
        "eli", "eli_v2_0", "assistant", "gguf", "router", "executor",
        "orchestrator", "cognition", "memory", "recall", "sqlite",
        "persona", "runtime"
    )):
        return "ELI / local assistant engineering"

    if any(k in low for k in (
        "physics", "simulation", "field", "latex", "paper", "theory",
        
    )):
        return "research / theory / writing"

    if any(k in low for k in (
        "linux", "ubuntu", "fedora", "gpu", "nvidia", "vram",
        "wine", "steam", "ollama"
    )):
        return "runtime / hardware / OS"

    return "other stable memory"


def _eli_v8_fallback_identity() -> str:
    # Portable fallback only. This is the OS account name, not a shipped human identity.
    try:
        name = _eli_getpass.getuser()
    except Exception:
        name = "local user"
    return f"Local account: {name}"


# The portable user-profile surface. No static profile files, no dev-specific identity
# shipped in, it rejects prompt/image-gen/event rows, and it only keeps runtime
# SELF_REPORT for actual runtime-status questions.

import re as _eli_v9_re
from typing import Any as _EliV9Any, Mapping as _EliV9Mapping


_ELI_V9_EVENT_REJECT = (
    "generated 1 images",
    "generated image",
    "generated images",
    "image from prompt",
    "from prompt:",
    "visual direction:",
    "recent user context",
    "user profile cues:",
    "draw an image",
    "generate an image",
    "image generation",
    "uploaded image",
    "binary file:",
    "[binary file:",
    "user question:",
    "whats this",
    "what's this",
    "without more context",
    "phrase or idiom",
    "conversation volume",
    "top topics",
    "session context",
    "active topics",
    "runtime truth report",
    "configured/requested",
    "effective loaded snapshot",
    "full runtime audit",
    "passed agents",
    "failed agents",
    "hackernews",
    "reddit/r/",
    "news synthesis",
    "generated python script failed",
    "synthesise_from_deterministic_evidence",
    "memory internals report",
    "table                                                        rows",
    "database:",
)


def _eli_v9_clean_text(value: object) -> str:
    text = str(value or "")
    text = text.replace("\x00", " ")
    text = _eli_v9_re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n-•")
    text = _eli_v9_re.sub(r"\.{2,}$", ".", text)
    text = _eli_v9_re.sub(r"\s+\.", ".", text)
    return text.strip()


def _eli_v9_is_event_noise(text: str) -> bool:
    low = _eli_v9_clean_text(text).lower()
    return any(marker in low for marker in _ELI_V9_EVENT_REJECT)


def _eli_v9_extract_durable_fact(text: str) -> str | None:
    raw = _eli_v9_clean_text(text)
    if not raw:
        return None

    if _eli_v9_is_event_noise(raw):
        return None

    fact = None
    try:
        fact = _eli_v8_extract_fact(raw)  # type: ignore[name-defined]
    except Exception:
        fact = raw

    fact = _eli_v9_clean_text(fact)
    if not fact:
        return None

    if _eli_v9_is_event_noise(fact):
        return None

    low = fact.lower()

    durable = (
        "preferred name:",
        "name:",
        "user prefers",
        "user values",
        "user dislikes",
        "user wants",
        "user works on",
        "user is working on",
        "user is actively",
        "user is developing",
        "user uses",
        "user runs",
        "user prefers",
    )

    if not any(d in low for d in durable):
        return None

    if len(fact) < 6 or len(fact) > 260:
        return None

    return fact


def _eli_v9_collect_durable_facts() -> list[str]:
    try:
        raw_texts = _eli_v8_collect_db_texts()  # type: ignore[name-defined]
    except Exception:
        raw_texts = []

    facts = []
    seen = set()

    for text in raw_texts:
        fact = _eli_v9_extract_durable_fact(text)
        if not fact:
            continue

        key = _eli_v9_re.sub(r"[^a-z0-9]+", " ", fact.lower()).strip()
        if not key or key in seen:
            continue

        seen.add(key)
        facts.append(fact)

    return facts


def _eli_v9_identity_label() -> tuple[str, str]:
    """Return (label, source). Source is local_memory or os_user_fallback."""

    facts = _eli_v9_collect_durable_facts()

    preferred = []
    names = []

    for fact in facts:
        if fact.lower().startswith("preferred name:"):
            preferred.append(fact.split(":", 1)[1].strip(" ."))
        elif fact.lower().startswith("name:"):
            names.append(fact.split(":", 1)[1].strip(" ."))

    if preferred:
        return preferred[0], "local_memory"

    if names:
        return names[0], "local_memory"

    # Do NOT fall back to the OS username — that is a system account name,
    # not the user's personal identity. Return empty when nothing is known.
    return "", "no_identity"


def _eli_v9_bucket_for_fact(fact: str) -> str:
    low = fact.lower()

    if low.startswith("name:") or low.startswith("preferred name:") or "preferred name" in low:
        return "identity"

    if any(k in low for k in (
        "prefers", "values", "dislikes", "direct", "truth", "honest",
        "step-by-step", "diagnostic", "audit", "thorough", "meticulous",
        "vague", "commands", "bash", "terminal"
    )):
        return "tone and working style"

    if any(k in low for k in (
        "eli", "eli_v2_0", "assistant", "gguf", "router", "executor",
        "orchestrator", "cognition", "memory", "recall", "sqlite",
        "persona", "runtime"
    )):
        return "ELI / local assistant engineering"

    if any(k in low for k in (
        "physics", "simulation", "field", "latex", "paper", "theory",
        
    )):
        return "research / theory / writing"

    if any(k in low for k in (
        "linux", "ubuntu", "fedora", "gpu", "nvidia", "vram",
        "wine", "steam", "ollama"
    )):
        return "runtime / hardware / OS"

    return "other stable memory"


def _eli_personal_memory_answer_v2(mode_label: str = "") -> str:  # type: ignore[override]
    facts = _eli_v9_collect_durable_facts()

    buckets = {
        "identity": [],
        "tone and working style": [],
        "ELI / local assistant engineering": [],
        "research / theory / writing": [],
        "runtime / hardware / OS": [],
        "other stable memory": [],
    }

    for fact in facts:
        buckets[_eli_v9_bucket_for_fact(fact)].append(fact)

    identity, source = _eli_v9_identity_label()
    if not buckets["identity"]:
        if source == "local_memory":
            buckets["identity"].append(f"Preferred name: {identity}")
        else:
            buckets["identity"].append(f"Current local OS account: {identity}")

    lines = [
        "What I know about this user from local memory:",
        "",
        "This is generated from this installation's local memory/database evidence. Runtime dumps, audits, news rows, uploaded-file events, one-off prompts, image-generation records, and script errors are filtered out.",
        "",
    ]

    emitted = 0
    for title, vals in buckets.items():
        vals = vals[:10]
        if not vals:
            continue

        lines.append(f"## {title}")
        for val in vals:
            lines.append(f"- {val}")
            emitted += 1
        lines.append("")

    if emitted <= 1:
        lines.append("No strong durable profile has been learned yet. Until explicit user facts exist, identify the user only from local account/session evidence.")
        lines.append("")

    lines.append("Operational rule: user identity is learned per installation. Do not package any developer-specific personal facts as defaults.")
    return "\n".join(lines).strip()


def _eli_v9_is_runtime_status_question(user_input: object) -> bool:
    low = str(user_input or "").lower()
    return bool(
        "actually running" in low
        or "model, context size" in low
        or "gpu layers" in low
        or "runtime" in low and ("who are you" in low or "model" in low)
        or "context size" in low
        or "n_ctx" in low
    )


def _eli_v9_self_report(user_input: object, mode_label: str = "") -> str:
    identity, source = _eli_v9_identity_label()
    return json.dumps(
        {
            "surface": "identity_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "runtime", "memory", "agents", "tools"],
            },
            "user_identity_source": source,
            "user_identity_value_present": bool(identity),
            "mode": str(mode_label or ""),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _render_v9(
    prev,
    action: str,
    args: _EliV9Mapping[str, _EliV9Any] | None = None,
    user_input: str = "",
    mode_label: str = "",
) -> str:
    a = str(action or "").upper()
    args = args or {}

    if a == "SELF_REPORT" and not _eli_v9_is_runtime_status_question(user_input):
        return _eli_v9_self_report(user_input, mode_label=mode_label)

    if a == "PERSONAL_MEMORY_DEEP_EXPLAIN":
        q = str(args.get("question") or user_input or "")
        low = q.lower()

        # Keep memory architecture questions on the internals surface.
        if (
            "internally" in low
            or "which files" in low
            or "db tables" in low
            or "which functions" in low
            or "memory system works" in low
        ):
            return prev(a, args, user_input, mode_label=mode_label)

        return _eli_personal_memory_answer_v2(mode_label=mode_label)

    return prev(a, args, user_input, mode_label=mode_label)

# Dynamic profile clause extractor v10: recovers durable user-preference clauses from noisy rows
# without keeping prompt/image/runtime wrappers.

import re as _eli_v10_re


_ELI_V10_DURABLE_PREFIXES = (
    "user prefers",
    "user values",
    "user dislikes",
    "user wants",
    "user works on",
    "user is working on",
    "user is actively",
    "user is developing",
    "user uses",
    "user runs",
    "user prefers",
    "preferred name:",
    "name:",
)


_ELI_V10_CLAUSE_REJECT = (
    "generated 1 images",
    "generated image",
    "generated images",
    "draw an image",
    "generate an image",
    "visual direction",
    "recent user context",
    "user profile cues",
    "binary file",
    "uploaded file",
    "user question",
    "whats this",
    "what's this",
    "without more context",
    "phrase or idiom",
    "conversation volume",
    "top topics",
    "session context",
    "active topics",
    "runtime truth report",
    "configured/requested",
    "effective loaded snapshot",
    "full runtime audit",
    "passed agents",
    "failed agents",
    "hackernews",
    "reddit/r/",
    "news synthesis",
    "generated python script failed",
    "synthesise_from_deterministic_evidence",
    "memory internals report",
    "table                                                        rows",
    "database:",
    "from prompt:",
)


def _eli_v10_norm_clause(text: object) -> str:
    s = str(text or "")
    s = s.replace("\\n", " ")
    s = s.replace("\n", " ")
    s = s.replace("\r", " ")
    s = _eli_v10_re.sub(r"\s+", " ", s)
    s = s.strip(" \t\r\n-•;:,.")
    s = _eli_v10_re.sub(r"\s+\.", ".", s)
    return s.strip()


def _eli_v10_clause_is_rejected(clause: str) -> bool:
    low = clause.lower()
    return any(x in low for x in _ELI_V10_CLAUSE_REJECT)


def _eli_v10_clause_is_durable(clause: str) -> bool:
    low = clause.lower().strip()
    return any(low.startswith(prefix) for prefix in _ELI_V10_DURABLE_PREFIXES)


def _eli_v10_split_candidate_clauses(row: object) -> list[str]:
    raw = str(row or "")

    # Normalize common prompt/list boundaries into extractable clause boundaries.
    raw = raw.replace(";", ". ")
    raw = raw.replace(" | ", ". ")
    raw = raw.replace(" - ", ". ")
    raw = raw.replace("•", ". ")
    raw = raw.replace("\\n", ". ")
    raw = raw.replace("\n", ". ")

    parts = _eli_v10_re.split(r"(?<=[.!?])\s+|\.{2,}|\s{2,}", raw)

    out = []
    for part in parts:
        p = _eli_v10_norm_clause(part)
        if not p:
            continue

        # Also recover embedded "User prefers..." from long text (name-agnostic).
        matches = _eli_v10_re.findall(
            r"(User\s+(?:prefers|values|dislikes|wants|works on|is working on|is actively|is developing|uses|runs)\b[^.;\n]{3,220})",
            p,
            flags=_eli_v10_re.IGNORECASE,
        )
        if matches:
            out.extend(_eli_v10_norm_clause(m) for m in matches)
        else:
            out.append(p)

    return out


def _eli_v10_collect_durable_facts() -> list[str]:
    try:
        raw_texts = _eli_v8_collect_db_texts()  # type: ignore[name-defined]
    except Exception:
        raw_texts = []

    facts = []
    seen = set()

    for row in raw_texts:
        for clause in _eli_v10_split_candidate_clauses(row):
            clause = _eli_v10_norm_clause(clause)
            if not clause:
                continue

            if _eli_v10_clause_is_rejected(clause):
                continue

            if not _eli_v10_clause_is_durable(clause):
                continue

            if len(clause) < 8 or len(clause) > 240:
                continue

            key = _eli_v10_re.sub(r"[^a-z0-9]+", " ", clause.lower()).strip()
            if not key or key in seen:
                continue

            seen.add(key)
            facts.append(clause)

    return facts


def _eli_v10_identity_label() -> tuple[str, str]:
    facts = _eli_v10_collect_durable_facts()

    preferred = []
    names = []

    for fact in facts:
        low = fact.lower()
        if low.startswith("preferred name:"):
            preferred.append(fact.split(":", 1)[1].strip(" ."))
        elif low.startswith("name:"):
            names.append(fact.split(":", 1)[1].strip(" ."))

    if preferred:
        return preferred[0], "local_memory"

    if names:
        return names[0], "local_memory"

    return "", "no_identity"


def _eli_v10_personal_memory_answer(mode_label: str = "") -> str:
    facts = _eli_v10_collect_durable_facts()

    buckets = {
        "identity": [],
        "tone and working style": [],
        "ELI / local assistant engineering": [],
        "research / theory / writing": [],
        "runtime / hardware / OS": [],
        "other stable memory": [],
    }

    identity, source = _eli_v10_identity_label()

    for fact in facts:
        low = fact.lower()

        if low.startswith("preferred name:") or low.startswith("name:"):
            bucket = "identity"
        elif any(k in low for k in (
            "prefers", "values", "dislikes", "direct", "truth", "honest",
            "step-by-step", "diagnostic", "audit", "thorough", "meticulous",
            "vague", "commands", "bash", "terminal", "concrete detail"
        )):
            bucket = "tone and working style"
        elif any(k in low for k in (
            "eli", "eli_v2_0", "assistant", "gguf", "router", "executor",
            "orchestrator", "cognition", "memory", "recall", "sqlite",
            "persona", "runtime"
        )):
            bucket = "ELI / local assistant engineering"
        elif any(k in low for k in (
            "physics", "simulation", "field", "latex", "paper", "theory",
            
        )):
            bucket = "research / theory / writing"
        elif any(k in low for k in (
            "linux", "ubuntu", "fedora", "gpu", "nvidia", "vram",
            "wine", "steam", "ollama"
        )):
            bucket = "runtime / hardware / OS"
        else:
            bucket = "other stable memory"

        buckets[bucket].append(fact)

    if not buckets["identity"]:
        if source == "local_memory":
            buckets["identity"].append(f"Preferred name: {identity}")
        else:
            buckets["identity"].append(f"Current local OS account: {identity}")

    lines = [
        "What I know about this user from local memory:",
        "",
        "This is generated from this installation's local memory/database evidence. Runtime dumps, audits, news rows, uploaded-file events, one-off prompts, image-generation records, and script errors are filtered out.",
        "",
    ]

    emitted = 0
    for title, vals in buckets.items():
        vals = vals[:10]
        if not vals:
            continue
        lines.append(f"## {title}")
        for val in vals:
            lines.append(f"- {val}")
            emitted += 1
        lines.append("")

    if emitted <= 1:
        lines.append("No strong durable profile has been learned yet. Until explicit user facts exist, identify the user only from local account/session evidence.")
        lines.append("")

    lines.append("Operational rule: user identity is learned per installation. Do not package any developer-specific personal facts as defaults.")
    return "\n".join(lines).strip()


# Dead code removed: the v10 layer captured _ELI_V10_PREVIOUS_RENDER_ACTION and defined
# _eli_v14_render_action_legacy but never rebound `render_action` to it (v11 captured v9's), so
# it was never installed or called. render_action output was byte-identical across all
# actions/modes after removal, and the live delegation chain is unchanged.

# Hard rules I enforce on the response surface: never leak the user's real name or OS account name
# into anything user-facing, redact home paths, let quick mode use the instant deterministic
# surfaces, and push non-quick modes through the normal persona/cognition path.

import getpass as _eli_v11_getpass
import re as _eli_v11_re


_ELI_V11_RESPONSE_SURFACE_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "MEMORY_STATUS",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
}


def _eli_v11_user_tokens() -> list[str]:
    toks = []
    try:
        u = _eli_v11_getpass.getuser()
        if u:
            toks.append(str(u))
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    out = []
    seen = set()
    for t in toks:
        t = str(t or "").strip()
        if not t:
            continue
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _eli_v11_redact_user_identity(text: object) -> str:
    s = str(text or "")

    # Redact /home/<user> and terminal-style home paths.
    try:
        os_user = _eli_v11_getpass.getuser()
    except Exception:
        os_user = ""

    if os_user:
        # Linux
        s = s.replace(f"/home/{os_user}/", "/home/<user>/")
        s = s.replace(f"/home/{os_user}", "/home/<user>")
        # macOS (/Users/<user>)
        s = s.replace(f"/Users/{os_user}/", "/Users/<user>/")
        s = s.replace(f"/Users/{os_user}", "/Users/<user>")
        # terminal-style ~<user>
        s = s.replace(f"~{os_user}/", "~<user>/")
        s = s.replace(f"~{os_user}", "~<user>")
        # Windows (C:\Users\<user>) — any drive letter, case-insensitive
        try:
            s = re.sub(rf"(?i)([A-Za-z]:\\Users\\){re.escape(os_user)}", r"\1<user>", s)
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    # Redact known personal tokens as standalone words/phrases.
    for tok in sorted(_eli_v11_user_tokens(), key=len, reverse=True):
        if not tok:
            continue
        s = _eli_v11_re.sub(
            r"(?<![A-Za-z0-9_])" + _eli_v11_re.escape(tok) + r"(?![A-Za-z0-9_])",
            "<user>",
            s,
            flags=_eli_v11_re.IGNORECASE,
        )

    # Clean common ugly double punctuation after redaction.
    s = s.replace("<user> / <user>", "<user>")
    s = s.replace("<user>.", "<user>.")
    return s


def _eli_v11_strip_identity_facts(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        low = line.lower()

        # Remove explicit identity facts from personal-memory surfaces.
        if low.startswith("- preferred name:"):
            continue
        if low.startswith("- name:"):
            continue
        if "current local os account" in low:
            continue
        if "according to this installation" in low and "memory" in low and "you are" in low:
            continue

        out.append(_eli_v11_redact_user_identity(line))
    return out


def _render_v11(prev, action, args=None, user_input="", mode_label=""):
    a = str(action or "").upper()
    args = args or {}

    # Casual identity must never expose name/account.
    if a == "SELF_REPORT" and not _eli_v9_is_runtime_status_question(user_input):  # type: ignore[name-defined]
        return json.dumps(
            {
                "surface": "identity_evidence",
                "identity": {
                    "name": "ELI",
                    "grounding_sources": ["persona", "runtime", "memory", "agents", "tools"],
                },
                "user_identity_redacted": True,
                "mode": str(mode_label or ""),
            },
            ensure_ascii=False,
            default=str,
            indent=2,
        )

    # Personal memory must not include identity names/account names.
    if a == "PERSONAL_MEMORY_DEEP_EXPLAIN":
        q = str((args or {}).get("question") or user_input or "")
        low = q.lower()

        if (
            "internally" in low
            or "which files" in low
            or "db tables" in low
            or "which functions" in low
            or "memory system works" in low
        ):
            return _eli_v11_redact_user_identity(prev(a, args, user_input, mode_label=mode_label))

        try:
            rendered = _eli_v10_personal_memory_answer(mode_label=mode_label)  # type: ignore[name-defined]
        except Exception:
            rendered = "What I know about this user from local memory:\n\nNo durable non-identifying profile facts were available."

        lines = rendered.splitlines()
        lines = _eli_v11_strip_identity_facts(lines)

        # Remove empty identity section if stripping left it blank.
        cleaned = []
        skip_blank_identity = False
        for i, line in enumerate(lines):
            if line.strip().lower() == "## identity":
                # Keep only if next non-empty line is a real bullet.
                has_identity_fact = False
                for nxt in lines[i + 1:i + 5]:
                    if nxt.startswith("- "):
                        has_identity_fact = True
                        break
                    if nxt.startswith("## "):
                        break
                if not has_identity_fact:
                    skip_blank_identity = True
                    continue

            if skip_blank_identity:
                if line.startswith("## "):
                    skip_blank_identity = False
                    cleaned.append(line)
                elif not line.strip():
                    continue
                else:
                    continue
            else:
                cleaned.append(line)

        rendered = "\n".join(cleaned).strip()

        if "- " not in rendered:
            rendered += "\n\nNo durable non-identifying profile facts were available yet."

        return _eli_v11_redact_user_identity(rendered)

    # Everything else: delegate, then redact.
    return _eli_v11_redact_user_identity(prev(a, args, user_input, mode_label=mode_label))


_ELI_V11_PREVIOUS_INSTALL = globals().get("install")



# Tightens the layer above. Quick can still use the short deterministic surfaces, but non-quick
# identity/runtime actions must not go back to the older wrappers, which let the model
# hallucinate its role, model size, names or paths. User identity is never exposed, home paths
# are redacted, and anything from a fallback model path is sanitised before it goes out.

import getpass as _eli_v12_getpass
import re as _eli_v12_re
import sqlite3 as _eli_v12_sqlite3
from pathlib import Path as _EliV12Path


_ELI_V12_SURFACE_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "MEMORY_STATUS",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
}


def _eli_v12_root() -> _EliV12Path:
    try:
        return _EliV12Path(__file__).resolve().parents[2]
    except Exception:
        return _EliV12Path.cwd()


def _eli_v12_db_paths() -> list[_EliV12Path]:
    root = _eli_v12_root()
    return [
        root / "artifacts" / "db" / "user.sqlite3",
        root / "artifacts" / "db" / "agent.sqlite3",
    ]


def _eli_v12_dynamic_identity_tokens() -> list[str]:
    """Build redaction tokens from this installation only.

    No packaged user names. No shipped profile assumptions.
    """

    toks: list[str] = []

    try:
        u = str(_eli_v12_getpass.getuser() or "").strip()
        if u:
            toks.append(u)
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    # Extract explicit learned identity facts from local DB rows, then redact them.
    # This lets each installation protect its own learned user identity without
    # packaging one developer's identity into source.
    patterns = [
        r"\bpreferred[_ -]?name\s*(?:is|:|=)\s*([A-Z][A-Za-z0-9_. -]{1,48})",
        r"\buser'?s preferred name\s*(?:is|:|=)\s*([A-Z][A-Za-z0-9_. -]{1,48})",
        r"\bname\s*(?:is|:|=)\s*([A-Z][A-Za-z0-9_. -]{1,48})",
    ]

    bad = {
        "eli",
        "entropy logical interface",
        "enhanced learning interface",
        "user",
        "local user",
        "current user",
        "assistant",
        "the user",
    }

    for db in _eli_v12_db_paths():
        if not db.exists():
            continue
        try:
            con = _eli_v12_sqlite3.connect(str(db))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            for table in tables:
                if table.startswith("sqlite_") or table.endswith("_fts") or "_fts_" in table:
                    continue
                try:
                    cur.execute(f"PRAGMA table_info({table})")
                    cols = [r[1] for r in cur.fetchall()]
                except Exception:
                    continue

                useful_cols = [c for c in cols if c.lower() in {"text", "content", "value", "observation", "details", "summary"}]
                for col in useful_cols[:4]:
                    try:
                        cur.execute(
                            f"SELECT {col} FROM {table} "
                            f"WHERE {col} IS NOT NULL "
                            f"AND (lower({col}) LIKE '%preferred name%' OR lower({col}) LIKE '%name:%' OR lower({col}) LIKE '%name is%') "
                            f"LIMIT 50"
                        )
                        rows = cur.fetchall()
                    except Exception:
                        continue

                    for (val,) in rows:
                        s = str(val or "")
                        for pat in patterns:
                            for m in _eli_v12_re.finditer(pat, s, flags=_eli_v12_re.I):
                                candidate = m.group(1).strip(" .,:;\"'`")
                                candidate = candidate.split("\n", 1)[0].strip()
                                if not candidate:
                                    continue
                                if candidate.lower() in bad:
                                    continue
                                if len(candidate) > 64:
                                    continue
                                toks.append(candidate)
            con.close()
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    out = []
    seen = set()
    for t in toks:
        t = str(t or "").strip()
        if not t:
            continue
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _eli_v12_redact(text: object) -> str:
    s = str(text or "")

    # Redact /home/<current-user> aggressively.
    try:
        os_user = str(_eli_v12_getpass.getuser() or "").strip()
    except Exception:
        os_user = ""

    if os_user:
        # Linux
        s = s.replace(f"/home/{os_user}/", "/home/<user>/")
        s = s.replace(f"/home/{os_user}", "/home/<user>")
        # macOS (/Users/<user>)
        s = s.replace(f"/Users/{os_user}/", "/Users/<user>/")
        s = s.replace(f"/Users/{os_user}", "/Users/<user>")
        # terminal-style ~<user>
        s = s.replace(f"~{os_user}/", "~<user>/")
        s = s.replace(f"~{os_user}", "~<user>")
        # Windows (C:\Users\<user>) — any drive letter, case-insensitive
        try:
            s = re.sub(rf"(?i)([A-Za-z]:\\Users\\){re.escape(os_user)}", r"\1<user>", s)
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    for tok in sorted(_eli_v12_dynamic_identity_tokens(), key=len, reverse=True):
        if not tok:
            continue
        s = _eli_v12_re.sub(
            r"(?<![A-Za-z0-9_])" + _eli_v12_re.escape(tok) + r"(?![A-Za-z0-9_])",
            "<user>",
            s,
            flags=_eli_v12_re.I,
        )

    # Fix role inversion if GGUF or memory context says the user is ELI.
    s = _eli_v12_re.sub(
        r"\bYou are ELI\b(?:\s*[—-]\s*[^.\n]+)?",
        "",
        s,
        flags=_eli_v12_re.I,
    )
    s = _eli_v12_re.sub(
        r"\bYou are\s+Entropy Logical Interface\b",
        "",
        s,
        flags=_eli_v12_re.I,
    )

    # Remove known hallucinated runtime claims.
    s = _eli_v12_re.sub(
        r"\bMy model size is about\s+\d+\s*GB\b[^.\n]*[.\n]?",
        "",
        s,
        flags=_eli_v12_re.I,
    )

    return s.strip()


def _eli_v12_is_runtime_question(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        "actually running" in low
        or "model, context size" in low
        or "context size" in low and "gpu" in low
        or "gpu layers" in low
        or "runtime" in low and ("model" in low or "ctx" in low or "context" in low)
    )


def _eli_v12_identity_answer(mode_label: str = "") -> str:
    return _eli_v12_redact(json.dumps(
        {
            "surface": "identity_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "runtime", "memory", "agents", "tools"],
            },
            "user_identity_redacted": True,
            "mode": str(mode_label or ""),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    ))


def _render_v12(prev, action: str, args=None, user_input="", mode_label="") -> str:
    a = str(action or "").upper()
    args = args or {}

    if a == "SELF_REPORT":
        if _eli_v12_is_runtime_question(user_input):
            evidence = prev(a, args, user_input, mode_label=mode_label)

            return _eli_v12_redact(json.dumps(
                {
                    "surface": "identity_runtime_evidence",
                    "identity": {
                        "name": "ELI",
                        "grounding_sources": ["persona", "runtime", "memory", "agents", "tools"],
                    },
                    "runtime_evidence": evidence,
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            ))

        return _eli_v12_identity_answer(mode_label)

    return _eli_v12_redact(prev(a, args, user_input, mode_label=mode_label))


def _eli_v12_forced_self_report_from_chat(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        ("answer the question" in low and "you are eli" in low)
        or ("i am not eli" in low and "you are eli" in low)
        or ("who are you" in low and "who am i" in low)
    )


_ELI_V12_PREVIOUS_INSTALL = globals().get("install")



# Fixes a surface issue in the layer above. Quick gets a short deterministic answer; deeper
# modes get a persona answer built from the exact deterministic runtime evidence. No personal
# name exposure, no "You are <user> local user" prose, and SELF_REPORT/runtime-identity
# surfaces aren't handed to the model.

import re as _eli_v13_re


def _eli_v13_safe_redact(text: object) -> str:
    s = str(text or "")

    try:
        s = _eli_v12_redact(s)  # type: ignore[name-defined]
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    # Clean bad identity prose introduced by earlier surfaces.
    s = _eli_v13_re.sub(
        r"\bYou are\s+<user>\s+local user\b\.?",
        "You are the local user of this installation.",
        s,
        flags=_eli_v13_re.I,
    )
    s = _eli_v13_re.sub(
        r"\bYou are\s+<user>\b\.?",
        "You are the local user of this installation.",
        s,
        flags=_eli_v13_re.I,
    )
    s = _eli_v13_re.sub(
        r"\b<user>\s+local user\b",
        "the local user",
        s,
        flags=_eli_v13_re.I,
    )

    # Preserve redacted paths, but avoid identity placeholders in normal prose.
    s = s.replace("You are <user> local user.", "You are the local user of this installation.")
    s = s.replace("You are <user>.", "You are the local user of this installation.")

    return s.strip()


def _eli_v13_previous_self_report(user_input: str, mode_label: str) -> str:
    """SELF_REPORT as rendered by the layers below v13."""
    try:
        return str(_RENDER_BELOW_V13("SELF_REPORT", {}, user_input, mode_label=mode_label))
    except Exception as e:
        return f"Runtime evidence unavailable: {type(e).__name__}: {e}"


def _eli_v13_extract_runtime_block(text: str) -> str:
    s = _eli_v13_safe_redact(text)

    # Strip V12 wrapper prose if present.
    s = _eli_v13_re.sub(
        r"^(?:i\s+am\s+eli)\.\s+You are.*?\n\nCurrent runtime evidence:\n\n",
        "",
        s,
        flags=_eli_v13_re.I | _eli_v13_re.S,
    )
    s = _eli_v13_re.sub(
        r"^(?:i\s+am\s+eli)\.\s+You are.*?Current runtime evidence:\s*",
        "",
        s,
        flags=_eli_v13_re.I | _eli_v13_re.S,
    )

    return s.strip()


def _eli_v13_field(block: str, key: str) -> str:
    # Finds lines like "- n_ctx: 8192" or "project_root: ..."
    pat = r"(?im)^\s*-?\s*" + _eli_v13_re.escape(key) + r"\s*:\s*(.+?)\s*$"
    m = _eli_v13_re.search(pat, block)
    return m.group(1).strip() if m else "unknown"


def _eli_v13_runtime_answer(user_input: str, mode_label: str) -> str:
    previous = _eli_v13_previous_self_report(user_input, mode_label)
    block = _eli_v13_extract_runtime_block(previous)

    provider = _eli_v13_field(block, "provider")
    model_path = _eli_v13_field(block, "model_path")
    configured_ctx = _eli_v13_field(block, "n_ctx")
    configured_layers = _eli_v13_field(block, "n_gpu_layers")
    configured_threads = _eli_v13_field(block, "n_threads")
    configured_batch = _eli_v13_field(block, "batch_size")
    configured_max_tokens = _eli_v13_field(block, "max_tokens")

    # Effective fields appear later with same key names. Extract manually from the effective block.
    eff_block = block
    m = _eli_v13_re.search(r"effective loaded snapshot:\s*(.*?)(?:\n\ngpu:|\Z)", block, flags=_eli_v13_re.I | _eli_v13_re.S)
    if m:
        eff_block = m.group(1)

    effective_ctx = _eli_v13_field(eff_block, "n_ctx")
    effective_layers = _eli_v13_field(eff_block, "n_gpu_layers")
    effective_threads = _eli_v13_field(eff_block, "n_threads")
    effective_batch = _eli_v13_field(eff_block, "n_batch")

    gpu_line = _eli_v13_field(block, "gpu")
    project_root = _eli_v13_field(block, "project_root")
    python_version = _eli_v13_field(block, "python")
    platform = _eli_v13_field(block, "platform")

    return _eli_v13_safe_redact(json.dumps(
        {
            "surface": "runtime_evidence",
            "configured": {
                "provider": provider,
                "model_path": model_path,
                "n_ctx": configured_ctx,
                "n_gpu_layers": configured_layers,
                "n_threads": configured_threads,
                "batch_size": configured_batch,
                "max_tokens": configured_max_tokens,
            },
            "effective": {
                "n_ctx": effective_ctx,
                "n_gpu_layers": effective_layers,
                "n_threads": effective_threads,
                "n_batch": effective_batch,
                "gpu": gpu_line,
            },
            "host": {
                "project_root": project_root,
                "python": python_version,
                "platform": platform,
            },
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    ))


def _eli_v13_identity_answer(mode_label: str = "") -> str:
    return json.dumps(
        {
            "surface": "identity_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "memory", "runtime_state", "local_files"],
            },
            "mode": str(mode_label or ""),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _eli_v13_is_runtime_question(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        "actually running" in low
        or "model, context size" in low
        or "gpu layers" in low
        or ("runtime" in low and ("model" in low or "ctx" in low or "context" in low or "gpu" in low))
        or ("context size" in low and "gpu" in low)
    )


def _eli_v13_forced_identity_question(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        ("who are you" in low and "who am i" in low)
        or ("i am not eli" in low and "you are eli" in low)
        or ("answer the question" in low and "you are eli" in low)
    )


def _render_v13(prev, action, args=None, user_input="", mode_label="") -> str:
    a = str(action or "").upper()
    args = args or {}
    text = str(user_input or "")

    if a == "SELF_REPORT" or _eli_v13_forced_identity_question(text):
        if _eli_v13_is_runtime_question(text):
            return _eli_v13_runtime_answer(text, str(mode_label or ""))
        return _eli_v13_identity_answer(str(mode_label or ""))

    return _eli_v13_safe_redact(prev(a, args, text, mode_label=mode_label))


_ELI_V13_SURFACE_ACTIONS = set(globals().get("_ELI_V12_SURFACE_ACTIONS", set())) | {
    "SELF_REPORT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "MEMORY_STATUS",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
}



# Quick-only bypass rules. The direct deterministic bypass is allowed only in quick mode;
# deeper modes go through CognitiveEngine.process / the persona pipeline. Runtime/identity
# answers are post-validated so nothing hallucinated slips out, and redaction is path/name-safe
# without mangling prose. No "<user>" in prose.

import getpass as _eli_v14_getpass
import json as _eli_v14_json
import re as _eli_v14_re
import socket as _eli_v14_socket
import subprocess as _eli_v14_subprocess
from pathlib import Path as _EliV14Path



from eli.utils.log import get_logger
log = get_logger(__name__)

def _eli_v14_project_root() -> _EliV14Path:
    try:
        return _EliV14Path(__file__).resolve().parents[2]
    except Exception:
        return _EliV14Path.cwd()


def _eli_v14_read_json(path: _EliV14Path) -> dict:
    try:
        if path.exists():
            return _eli_v14_json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    return {}


def _eli_v14_runtime_snapshot() -> dict:
    root = _eli_v14_project_root()
    snap = _eli_v14_read_json(root / "artifacts" / "runtime_snapshot.json")
    if isinstance(snap, dict):
        return snap
    return {}


def _eli_v14_settings() -> dict:
    root = _eli_v14_project_root()
    settings = _eli_v14_read_json(root / "config" / "settings.json")
    if isinstance(settings, dict):
        return settings
    return {}


def _eli_v14_gpu_line() -> str:
    try:
        out = _eli_v14_subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=_eli_v14_subprocess.DEVNULL,
            timeout=3,
        ).strip().splitlines()
        if out:
            return out[0].strip()
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    # Cross-vendor fallback -- see _gpu_line() above for why.
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
        if hw.has_gpu:
            note = " (estimated)" if hw.gpu_detection_uncertain else ""
            return f"{hw.gpu_name}{note}, {hw.total_vram_mb} MiB total (live query unavailable)"
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    return "unavailable"


def _eli_v14_get_runtime_value(data: dict, *keys, default="unknown"):
    cur = data
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    if cur is None or cur == "":
        return default
    return cur


def _eli_v14_runtime_data() -> dict:
    root = _eli_v14_project_root()
    snap = _eli_v14_runtime_snapshot()
    settings = _eli_v14_settings()

    configured = {
        "provider": settings.get("provider") or settings.get("llm_provider") or "custom_gguf",
        "model_path": settings.get("model_path") or settings.get("gguf_model_path") or settings.get("ollama_model") or snap.get("model_path") or "unconfigured",
        "n_ctx": settings.get("n_ctx") or settings.get("ctx") or settings.get("context_size") or 16384,
        "n_gpu_layers": settings.get("n_gpu_layers") or settings.get("gpu_layers") or "unknown",
        "n_threads": settings.get("n_threads") or settings.get("threads") or 4,
        "batch_size": settings.get("batch_size") or settings.get("n_batch") or 512,
        "max_tokens": settings.get("max_tokens") or 512,
    }

    effective = {
        "n_ctx": snap.get("n_ctx") or snap.get("ctx") or snap.get("context_size") or configured["n_ctx"],
        "n_gpu_layers": snap.get("n_gpu_layers") or snap.get("gpu_layers") or configured["n_gpu_layers"],
        "n_threads": snap.get("n_threads") or snap.get("threads") or configured["n_threads"],
        "n_batch": snap.get("n_batch") or snap.get("batch_size") or configured["batch_size"],
    }

    return {
        "project_root": str(root),
        "python": ".".join(map(str, __import__("sys").version_info[:3])),
        "platform": __import__("sys").platform,
        "configured": configured,
        "effective": effective,
        "gpu": _eli_v14_gpu_line(),
    }


def _eli_v14_name_tokens() -> set[str]:
    tokens = set()

    try:
        u = _eli_v14_getpass.getuser()
        if u:
            tokens.add(u)
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    try:
        host = _eli_v14_socket.gethostname()
        if host:
            for part in _eli_v14_re.split(r"[^A-Za-z0-9]+", host):
                if len(part) >= 3:
                    tokens.add(part)
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    # Pull explicit name-like memory facts dynamically from this installation only.
    root = _eli_v14_project_root()
    db = root / "artifacts" / "db" / "user.sqlite3"
    try:
        import sqlite3 as _eli_v14_sqlite3
        if db.exists():
            con = _eli_v14_sqlite3.connect(str(db))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
            if cur.fetchone():
                cols = [r[1] for r in cur.execute("PRAGMA table_info(memories)").fetchall()]
                wanted = [c for c in ("text", "content", "value") if c in cols]
                if wanted:
                    expr = " || ' ' || ".join([f"COALESCE({c}, '')" for c in wanted])
                    for (row_text,) in cur.execute(f"SELECT {expr} FROM memories ORDER BY rowid DESC LIMIT 500"):
                        s = str(row_text or "")
                        for pat in (
                            r"\bpreferred name\s*(?:is|:)\s*([A-Z][A-Za-z0-9_. -]{1,40})",
                            r"\buser'?s name\s*(?:is|:)\s*([A-Z][A-Za-z0-9_. -]{1,40})",
                            r"\bname\s*:\s*([A-Z][A-Za-z0-9_. -]{1,40})",
                        ):
                            m = _eli_v14_re.search(pat, s, flags=_eli_v14_re.I)
                            if m:
                                for part in _eli_v14_re.split(r"[^A-Za-z0-9]+", m.group(1).strip()):
                                    if len(part) >= 3:
                                        tokens.add(part)
            con.close()
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    reject = {
        "user", "local", "home", "desktop", "eli", "eli_v2_0", "root", "python",
        "linux", "model", "runtime", "assistant", "installation", "the",
        "and", "you", "your", "this", "that", "preferred", "name",
    }

    return {t for t in tokens if t and t.lower() not in reject and len(t) >= 3}


def _eli_v14_redact(text: object) -> str:
    s = str(text or "")

    # Path-only redaction. Do NOT replace normal words like "the" or "your".
    s = _eli_v14_re.sub(r"/home/[^/\s]+", "/home/<user>", s)

    # Redact shell prompts / user@host if they leak.
    s = _eli_v14_re.sub(r"\b[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+(?=[:\s])", "<user>@<host>", s)

    # Redact learned local name tokens in normal prose.
    for token in sorted(_eli_v14_name_tokens(), key=len, reverse=True):
        s = _eli_v14_re.sub(
            rf"\b{_eli_v14_re.escape(token)}\b",
            "the local user",
            s,
            flags=_eli_v14_re.I,
        )

    # Clean previous bad placeholder prose.
    s = s.replace("You are <user> local user.", "You are the local user of this installation.")
    s = s.replace("You are <user>.", "You are the local user of this installation.")
    s = s.replace("<user> local assistant", "the local assistant")
    s = s.replace("<user> grounded", "the grounded")
    s = s.replace("<user> loaded", "the loaded")
    s = s.replace("<user> important", "The important")
    s = s.replace("<user> configuration", "the configuration")
    s = s.replace("<user> actual", "the actual")
    s = s.replace("<user> loader", "the loader")
    s = s.replace("<user> larger", "the larger")
    s = s.replace("<user> llama", "the llama")
    s = s.replace("<user> working", "the working")
    s = s.replace("<user> effective", "the effective")
    s = s.replace("of this installation. of this installation.", "of this installation.")

    # Correct identity inversion.
    s = _eli_v14_re.sub(
        r"\bYou are ELI\b",
        "You are the local user of this installation",
        s,
        flags=_eli_v14_re.I,
    )

    return s.strip()


def _eli_v14_is_quick(mode_label: str) -> bool:
    try:
        return bool(_is_quick_mode(mode_label))  # type: ignore[name-defined]
    except Exception:
        return str(mode_label or "").lower().strip() in {
            "quick", "quick_mode", "quick mode", "⚡ quick"
        }


def _eli_v14_runtime_question(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        "actually running" in low
        or "model, context size" in low
        or "gpu layers" in low
        or ("runtime" in low and ("model" in low or "ctx" in low or "context" in low or "gpu" in low))
        or ("context size" in low and "gpu" in low)
    )


def _eli_v14_identity_question(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        ("who are you" in low and "who am i" in low)
        or ("i am not eli" in low and "you are eli" in low)
        or ("answer the question" in low and "you are eli" in low)
    )


def _eli_v14_quick_runtime_answer() -> str:
    d = _eli_v14_runtime_data()
    c = d["configured"]
    e = d["effective"]
    return _eli_v14_redact(json.dumps(
        {
            "surface": "runtime_evidence",
            "configured": c,
            "effective": e,
            "gpu": d["gpu"],
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    ))


def _eli_v14_persona_runtime_answer(mode_label: str = "") -> str:
    d = _eli_v14_runtime_data()
    c = d["configured"]
    e = d["effective"]
    return _eli_v14_redact(json.dumps(
        {
            "surface": "identity_runtime_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "memory", "runtime_state", "local_files"],
            },
            "configured": c,
            "effective": e,
            "gpu": d["gpu"],
            "host": {
                "project_root": d["project_root"],
                "python": d["python"],
                "platform": d["platform"],
            },
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    ))


def _eli_v14_identity_answer(mode_label: str = "") -> str:
    return _eli_v14_redact(json.dumps(
        {
            "surface": "identity_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "memory", "runtime_state", "local_files"],
            },
            "mode": str(mode_label or ""),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    ))


def _eli_v14_bad_self_report_output(text: object) -> bool:
    low = str(text or "").lower()
    return bool(
        not low.strip()
        or "you are eli" in low
        or "180gb" in low
        or "model size is about" in low
        or "<user> local" in low
        or "my god is yahweh" in low
        or "elijah" in low
        or "biblical" in low
    )


def _render_v14(prev, action, args=None, user_input="", mode_label=""):
    a = str(action or "").upper().strip()
    text = str(user_input or "")

    if a == "SELF_REPORT" or _eli_v14_identity_question(text):
        if _eli_v14_runtime_question(text):
            if _eli_v14_is_quick(str(mode_label or "")):
                return _eli_v14_quick_runtime_answer()
            return _eli_v14_persona_runtime_answer(str(mode_label or ""))
        return _eli_v14_identity_answer(str(mode_label or ""))

    try:
        rendered = prev(a, args or {}, text, mode_label=mode_label)
    except Exception as e:
        rendered = json.dumps(
            {"surface": "render_action_failed", "action": a, "error": f"{type(e).__name__}: {e}"},
            ensure_ascii=False,
            default=str,
            indent=2,
        )
    return _eli_v14_redact(rendered)


_ELI_V14_SURFACE_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "MEMORY_STATUS",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
}


def install(CognitiveEngine):  # type: ignore[override]
    """
    Retired public installer.

    This module previously installed global CognitiveEngine.process wrappers.
    That mutation path is now retired. Routing, execution, grounding, and
    user-visible coercion must live in explicit router/executor/engine
    contracts or consumer-boundary helpers, not import-time process wrapping.
    """
    return CognitiveEngine


# ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1: render_action is one explicit, ordered pipeline. Each layer takes
# the renderer below it as its first argument and either answers for itself or delegates and post-processes.
# Innermost first: the response-surface renderer (which falls back to the original), then the v9 personal-memory
# layer, v11 identity redaction, v12 runtime evidence, v13 safe redaction and v14 identity/runtime answers.
def _stack(layer, below):
    def render(action, args=None, user_input="", mode_label=""):
        return layer(below, action, args, user_input, mode_label)
    return render


_ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1 = True      # read by the frontier and identity status reports
_RENDER_BELOW_V13 = _stack(_render_v12, _stack(_render_v11, _stack(_render_v9, _render_v2)))
_RENDER_PIPELINE = _stack(_render_v14, _stack(_render_v13, _RENDER_BELOW_V13))


def render_action(action, args=None, user_input="", mode_label=""):
    return _RENDER_PIPELINE(action, args, user_input, mode_label)
