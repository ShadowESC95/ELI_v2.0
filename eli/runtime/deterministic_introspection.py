from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


DIAGNOSTIC_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_STATUS",
    "MEMORY_STATUS",
    "USER_IDENTITY_SUMMARY",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "IMPORT_AUDIT",
    "GUI_RUNTIME_AUDIT",
    "AGENTBUS_STATUS",
    "ORCHESTRATOR_STATUS",
    "OUTPUT_GOVERNOR_STATUS",
}


def classify_diagnostic_action(text: str) -> Optional[str]:
    low = str(text or "").strip().lower()
    if not low:
        return None

    # A request to PRODUCE an artifact about ELI's internals ("generate/write a
    # document/report about your agent bus") is a generative task, NOT a diagnostic
    # status dump — never classify it here, or this gate swallows it before it can
    # route to GENERATE_DOCUMENT (eval-caught: doc-gen returned the agent-bus status).
    if re.search(
        r"\b(generate|create|write|make|draft|produce|compose|prepare|build)\b"
        r".{0,30}\b(document|doc|report|essay|article|paper|write-?up|brief|memo|"
        r"guide|overview|summary|story|blog|post|readme)\b", low):
        return None

    # "who are you" is a persona/identity question — let the LLM answer it
    # in ELI's voice.  Only map *technical* runtime queries to RUNTIME_STATUS.
    if re.search(r"\b(what are you running|runtime status|model.*context|gpu layers|context size)\b", low):
        return "RUNTIME_STATUS"

    if re.search(r"\b(how many memories|memory system|memory runtime|what do you know about me from memory|memory count|stored memories)\b", low):
        return "EXPLAIN_MEMORY_RUNTIME"

    # === PHASE15_REDISTRIBUTABLE_IMPORT_VENV_CLASSIFIER ===
    _eli_phase15_import_subject = bool(re.search(
        r"\b(imports?|modules?|dependencies?|packages?|virtual environments?|venv|\.venv|python environment)\b",
        low,
    ))
    _eli_phase15_import_request = bool(re.search(
        r"\b(status|missing|failing|failure|failures|broken|audit|check|inspect|what is|what are|show me|tell me)\b",
        low,
    ))
    if _eli_phase15_import_subject and _eli_phase15_import_request:
        return "IMPORT_AUDIT"

    # ELI_REASONING_MODE_STATUS_FIX_20260505: exact mode-status request is not a full diagnostic report.
    if re.search(r"\breasoning mode\b", low) and not re.search(r"\b(cognition pipeline|input to output|cognition runtime|diagnostic|diagnostics|audit|every step|explain)\b", low):
        return "REASONING_MODE_STATUS"

    if re.search(r"\b(cognition pipeline|input to output|cognition runtime)\b", low):
        return "EXPLAIN_COGNITION_RUNTIME"

    if re.search(r"\b(confidence in your last|which agents contributed|last response|last answer|why.*cut off|why.*incomplete)\b", low):
        return "EXPLAIN_LAST_RESPONSE"

    if re.search(r"\b(agent bus|agentbus)\b", low):
        return "AGENTBUS_STATUS"

    if re.search(r"\b(orchestrator)\b", low):
        return "ORCHESTRATOR_STATUS"

    if re.search(r"\b(output governor|response governance|governor)\b", low):
        return "OUTPUT_GOVERNOR_STATUS"

    return None


def _route_action(text: str) -> Optional[str]:
    try:
        from eli.execution.router_enhanced import route
        routed = route(text)
        if isinstance(routed, dict):
            action = str(routed.get("action") or "").strip().upper()
            if action in DIAGNOSTIC_ACTIONS:
                return action
    except Exception:
        pass
    return classify_diagnostic_action(text)


def _last_trace(engine: Any) -> Dict[str, Any]:
    for name in ("_last_trace", "last_trace", "_last_response_trace", "last_response_trace"):
        try:
            val = getattr(engine, name, None)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    return {}


def _last_response(engine: Any) -> str:
    for name in ("_last_response", "last_response", "_last_answer", "last_answer"):
        try:
            val = getattr(engine, name, None)
            if val is not None and str(val).strip():
                return str(val)
        except Exception:
            pass
    return ""


def _format_jsonish(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def _explain_last_response(engine: Any) -> str:
    trace = _last_trace(engine)
    response = _last_response(engine)
    agents = None
    confidence = None
    if trace:
        agents = (
            trace.get("agents_used")
            or trace.get("agents")
            or trace.get("agent_results")
            or trace.get("bus_agents")
        )
        confidence = (
            trace.get("answer_confidence")
            or trace.get("evidence_confidence")
            or trace.get("confidence")
            or trace.get("bus_confidence")
            or trace.get("route_confidence")
        )
    # Human-readable summary, not a raw JSON trace dump into chat.
    # (Fix: issue #4 raw-JSON dump — previously this returned json.dumps(...).)
    _agent_list = agents
    if isinstance(_agent_list, (list, tuple)):
        _agent_str = ", ".join(str(a) for a in _agent_list) or "none"
    elif _agent_list:
        _agent_str = str(_agent_list)
    else:
        _agent_str = "none recorded"
    _conf_str = (f"{confidence}" if confidence is not None else "not recorded")
    lines = ["My last response:"]
    if response:
        _prev = response.strip().replace("\n", " ")
        lines.append(f'- text: "{_prev[:240]}{"…" if len(_prev) > 240 else ""}"')
    else:
        lines.append("- text: (none recorded)")
    lines.append(f"- agents that contributed: {_agent_str}")
    lines.append(f"- route/bus confidence: {_conf_str} "
                 "(note: this is routing/evidence confidence, not a guarantee the answer is factually correct)")
    return "\n".join(lines)


def _cognition_report(engine: Any) -> str:
    lines = []
    lines.append("Cognition runtime report")
    lines.append("")
    lines.append("Deterministic pipeline currently enforced for diagnostic actions:")
    lines.append("1. Receive text from GUI/STT/chat.")
    lines.append("2. Route/classify the action.")
    lines.append("3. If the action is diagnostic, bypass GGUF generation.")
    lines.append("4. Read runtime/memory/import state directly from Python, SQLite, FAISS metadata, settings, env, and engine attributes.")
    lines.append("5. Return the report directly.")
    lines.append("")
    lines.append("For non-diagnostic actions, existing router/executor/orchestrator flow remains active.")
    lines.append("")
    lines.append(f"Engine class: {type(engine).__name__ if engine is not None else None}")
    for attr in ("reasoning_mode", "mode", "_reasoning_mode", "_last_action"):
        try:
            if hasattr(engine, attr):
                lines.append(f"{attr}: {getattr(engine, attr)}")
        except Exception:
            pass
    return "\n".join(lines)


def _module_status(module_name: str) -> str:
    try:
        mod = __import__(module_name, fromlist=["*"])
        path = getattr(mod, "__file__", None)
        return f"{module_name}: OK ({path})"
    except Exception as exc:
        return f"{module_name}: FAIL {type(exc).__name__}: {exc}"


def _import_audit() -> str:
    # === PHASE14B_IMPORT_AUDIT_VENV_PACKAGE_EVIDENCE ===
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    venv_dir = project_root / ".venv"

    venv_python_candidates = [
        venv_dir / "bin" / "python",
        venv_dir / "bin" / "python3",
    ]
    venv_python = next((p for p in venv_python_candidates if p.exists()), None)

    venv_python_version = ""
    if venv_python is not None:
        try:
            venv_python_version = subprocess.check_output(
                [str(venv_python), "--version"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=4,
            ).strip()
        except Exception as exc:
            venv_python_version = f"ERROR: {type(exc).__name__}: {exc}"

    modules = [
        "eli.kernel.engine",
        "eli.execution.router_enhanced",
        "eli.execution.executor_enhanced",
        "eli.execution.portable_intent_contract",
        "eli.system.portable_app_control",
        "eli.cognition.gguf_inference",
        "eli.cognition.orchestrator",
        "eli.cognition.context_synthesiser",
        "eli.cognition.response_governance",
        "eli.memory.memory_truth",
        "eli.runtime.truth_report",
    ]

    requirement_files = [
        str(p.relative_to(project_root))
        for p in sorted(project_root.glob("requirements*.txt"))
    ]
    if (project_root / "pyproject.toml").exists():
        requirement_files.append("pyproject.toml")

    payload = {
        "surface": "import_audit_evidence",
        "modules": {mod: _module_status(mod) for mod in modules},
        "environment": {
            "project_root": str(project_root),
            "sys_executable": str(sys.executable),
            "sys_python_version": sys.version.split()[0],
            "virtual_env_env": os.environ.get("VIRTUAL_ENV", ""),
            "pythonpath_env": os.environ.get("PYTHONPATH", ""),
            "venv_dir": str(venv_dir),
            "venv_exists": venv_dir.exists(),
            "venv_python_exists": venv_python is not None,
            "venv_python": str(venv_python) if venv_python is not None else "",
            "venv_python_version": venv_python_version,
            "requirements_files": requirement_files,
        },
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        indent=2,
    )



def _component_status(name: str) -> str:
    lookup = {
        "AGENTBUS_STATUS": [
            "eli.cognition.agent_bus",
            "eli.cognition.orchestrator",
        ],
        "ORCHESTRATOR_STATUS": [
            "eli.cognition.orchestrator",
        ],
        "OUTPUT_GOVERNOR_STATUS": [
            "eli.cognition.response_governance",
            "eli.cognition.output_governor",
        ],
    }
    lines = [name.replace("_", " ").title(), ""]
    for mod in lookup.get(name, []):
        lines.append("- " + _module_status(mod))
    return "\n".join(lines)


def handle_diagnostic_action(action: str, text: str, engine: Any = None) -> Optional[str]:
    action = str(action or "").strip().upper()
    if action not in DIAGNOSTIC_ACTIONS:
        return None

    if action == "REASONING_MODE_STATUS":
        try:
            from eli.runtime.reasoning_status import current_reasoning_mode_text
            return current_reasoning_mode_text(engine)
        except Exception:
            return "Current reasoning mode: Quick"

    if action in {"SELF_REPORT", "RUNTIME_STATUS", "GUI_RUNTIME_AUDIT"}:
        from eli.runtime.truth_report import runtime_truth_report, format_runtime_truth
        from eli.runtime.user_visible_response_surface import coerce_user_visible
        return coerce_user_visible(
            format_runtime_truth(runtime_truth_report(engine=engine))
        )

    if action == "USER_IDENTITY_SUMMARY":
        try:
            from eli.runtime.personal_memory_surface import personal_memory_surface
            return str(personal_memory_surface(text))
        except Exception as exc:
            return f"User identity summary unavailable: {type(exc).__name__}: {exc}"

    if action in {"MEMORY_STATUS", "EXPLAIN_MEMORY_RUNTIME"}:
        from eli.memory.memory_truth import memory_truth_report, format_memory_truth
        return format_memory_truth(memory_truth_report())

    if action == "EXPLAIN_LAST_RESPONSE":
        return _explain_last_response(engine)

    if action == "EXPLAIN_COGNITION_RUNTIME":
        # Return None so quick-mode falls through to the LLM pipeline.
        # The static _cognition_report() only describes the bypass mechanism
        # itself — not the actual 12-stage pipeline the user is asking about.
        # Non-quick modes use gather_evidence() + LLM synthesis (correct path).
        return None

    if action == "IMPORT_AUDIT":
        return _import_audit()

    if action in {"AGENTBUS_STATUS", "ORCHESTRATOR_STATUS", "OUTPUT_GOVERNOR_STATUS"}:
        return _component_status(action)

    return None


def maybe_handle(text: str, engine: Any = None) -> Optional[str]:
    action = _route_action(text)
    if not action:
        return None
    return handle_diagnostic_action(action, text, engine=engine)


def detect_action(text: str) -> Optional[str]:
    """Public alias for diagnostic-action classification (router-aware)."""
    return _route_action(text)


def gather_evidence(action: str, text: str, engine: Any = None) -> Dict[str, Any]:
    """
    Gather deterministic diagnostic data WITHOUT formatting it as the final
    chat response. Used by non-quick reasoning modes so the LLM can answer
    in ELI's voice grounded in real runtime facts.
    """
    action = str(action or "").strip().upper()
    evidence: Dict[str, Any] = {"action": action, "query": str(text or "")}

    if action in {"SELF_REPORT", "RUNTIME_STATUS", "GUI_RUNTIME_AUDIT"}:
        try:
            from eli.runtime.truth_report import runtime_truth_report
            evidence["runtime"] = runtime_truth_report(engine=engine)
        except Exception as exc:
            evidence["runtime_error"] = repr(exc)

    if action == "USER_IDENTITY_SUMMARY":
        try:
            from eli.runtime.personal_memory_surface import personal_memory_surface
            evidence["personal_memory_summary"] = str(personal_memory_surface(text))
        except Exception as exc:
            evidence["personal_memory_error"] = repr(exc)

    if action in {"MEMORY_STATUS", "EXPLAIN_MEMORY_RUNTIME"}:
        try:
            from eli.memory.memory_truth import memory_truth_report
            evidence["memory"] = memory_truth_report()
        except Exception as exc:
            evidence["memory_error"] = repr(exc)

    if action == "EXPLAIN_LAST_RESPONSE":
        evidence["last_response"] = _last_response(engine)
        evidence["last_trace"] = _last_trace(engine)

    if action == "EXPLAIN_COGNITION_RUNTIME":
        evidence["cognition_summary"] = _cognition_report(engine)

    if action == "IMPORT_AUDIT":
        evidence["import_audit"] = _import_audit()

    if action == "REASONING_MODE_STATUS":
        try:
            from eli.runtime.reasoning_status import current_reasoning_mode_text
            evidence["reasoning_mode_text"] = current_reasoning_mode_text(engine)
        except Exception as exc:
            evidence["reasoning_mode_error"] = repr(exc)

    if action in {"AGENTBUS_STATUS", "ORCHESTRATOR_STATUS", "OUTPUT_GOVERNOR_STATUS"}:
        evidence["component_status"] = _component_status(action)

    return evidence


def _summarize_runtime(runtime: Dict[str, Any]) -> str:
    if not isinstance(runtime, dict):
        return ""
    parts = []
    for key in ("project_root", "python"):
        v = runtime.get(key)
        if v is not None:
            parts.append(f"{key}: {v}")
    plat = runtime.get("platform") or {}
    if isinstance(plat, dict):
        sysname = plat.get("system")
        rel = plat.get("release")
        mach = plat.get("machine")
        if sysname or rel or mach:
            parts.append(f"platform: {sysname} {rel} {mach}".strip())
    git = runtime.get("git") or {}
    if isinstance(git, dict):
        for k in ("branch", "commit"):
            v = git.get(k)
            if v:
                parts.append(f"git.{k}: {v}")
        dirty = git.get("dirty_files") or []
        if dirty:
            parts.append(f"git.dirty_count: {len(dirty)}")
    cfg = runtime.get("settings") or {}
    if isinstance(cfg, dict):
        for key in ("provider", "model_path", "n_ctx", "n_gpu_layers", "n_threads", "batch_size", "max_tokens"):
            v = cfg.get(key)
            if v is not None:
                parts.append(f"requested.{key}: {v}")
    eff = runtime.get("runtime_snapshot") or {}
    if isinstance(eff, dict):
        for key in ("n_ctx", "n_gpu_layers", "n_threads", "n_batch"):
            v = eff.get(key)
            if v is not None:
                parts.append(f"effective.{key}: {v}")
    gpu = runtime.get("gpu") or {}
    if isinstance(gpu, dict) and gpu.get("available"):
        for k_in, k_out in (
            ("name", "name"),
            ("memory_total_mib", "total_mib"),
            ("memory_free_mib", "free_mib"),
            ("driver", "driver"),
        ):
            v = gpu.get(k_in)
            if v is not None:
                parts.append(f"gpu.{k_out}: {v}")
    gguf = runtime.get("gguf") or {}
    if isinstance(gguf, dict):
        live = gguf.get("live_override") or gguf.get("effective") or {}
        if isinstance(live, dict):
            for k in ("n_ctx", "n_gpu_layers", "n_threads", "n_batch"):
                v = live.get(k)
                if v is not None:
                    parts.append(f"gguf.live.{k}: {v}")
    health = runtime.get("import_health")
    if isinstance(health, dict) and health:
        ok = sum(1 for v in health.values() if isinstance(v, dict) and v.get("ok"))
        bad = [k for k, v in health.items() if isinstance(v, dict) and not v.get("ok")]
        parts.append(f"import_health: {ok}/{len(health)} OK")
        if bad:
            parts.append("import_failures: " + ", ".join(bad))
    return "\n".join(parts)


def _summarize_memory(memory: Dict[str, Any]) -> str:
    if not isinstance(memory, dict):
        return ""
    parts = []
    summary = memory.get("summary") or {}
    if isinstance(summary, dict):
        for k in (
            "user_memories",
            "user_memory_fts",
            "user_conversation_turns",
            "user_conversations",
            "user_observations",
            "user_recall_log",
            "agent_memories",
            "agent_observations",
            "vector_ntotal",
            "vector_meta_len",
        ):
            v = summary.get(k)
            if v is not None:
                parts.append(f"summary.{k}: {v}")
    dbs = memory.get("databases") or {}
    if isinstance(dbs, dict):
        for db_name, db in dbs.items():
            if not isinstance(db, dict):
                continue
            path = db.get("path")
            exists = db.get("exists")
            parts.append(f"db.{db_name}.path: {path}")
            parts.append(f"db.{db_name}.exists: {exists}")
            counts = db.get("counts") or {}
            if isinstance(counts, dict):
                shown = 0
                for tname, rc in counts.items():
                    if shown >= 12:
                        break
                    if str(tname).endswith(("_fts_config", "_fts_data", "_fts_docsize", "_fts_idx")):
                        continue
                    parts.append(f"  db.{db_name}.{tname}: {rc} rows")
                    shown += 1
    vec = memory.get("vector_store") or {}
    if isinstance(vec, dict):
        for k in ("index_path", "meta_path", "vector_count", "ntotal"):
            v = vec.get(k)
            if v is not None:
                parts.append(f"vector_store.{k}: {v}")
    return "\n".join(parts)


def format_evidence_block(evidence: Dict[str, Any]) -> str:
    """
    Render gathered evidence as a compact GROUNDED_DIAGNOSTIC_EVIDENCE block
    suitable for injection into the persona handoff. The LLM is instructed
    elsewhere to use these as authoritative facts and answer in ELI's voice.
    """
    if not isinstance(evidence, dict) or not evidence:
        return ""
    action = evidence.get("action") or "DIAGNOSTIC"
    sections = [f"GROUNDED_DIAGNOSTIC_EVIDENCE (action={action} — these are real runtime facts; answer using these, do not invent):"]

    runtime = evidence.get("runtime")
    if runtime:
        summary = _summarize_runtime(runtime)
        if summary:
            sections.append("[runtime]\n" + summary)

    memory = evidence.get("memory")
    if memory:
        summary = _summarize_memory(memory)
        if summary:
            sections.append("[memory]\n" + summary)

    last_resp = evidence.get("last_response")
    if last_resp:
        sections.append("[last_response_preview]\n" + str(last_resp)[:600])

    last_trace = evidence.get("last_trace")
    if isinstance(last_trace, dict) and last_trace:
        trace_lines = []
        for k in ("action", "agents_used", "confidence_label", "reasoning_mode", "request_id"):
            v = last_trace.get(k)
            if v is not None:
                trace_lines.append(f"{k}: {v}")
        if trace_lines:
            sections.append("[last_trace]\n" + "\n".join(trace_lines))

    cog = evidence.get("cognition_summary")
    if cog:
        sections.append("[cognition_pipeline]\n" + str(cog))

    imp = evidence.get("import_audit")
    if imp:
        sections.append("[import_audit]\n" + str(imp))

    rmode = evidence.get("reasoning_mode_text")
    if rmode:
        sections.append("[reasoning_mode]\n" + str(rmode))

    comp = evidence.get("component_status")
    if comp:
        sections.append("[component_status]\n" + str(comp))

    return "\n\n".join(sections).strip()
