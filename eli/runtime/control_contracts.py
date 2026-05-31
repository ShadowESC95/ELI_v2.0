from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

CONTROL_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_STATUS",
    "GPU_STATUS",
    "REASONING_MODE_STATUS",
    "USER_IDENTITY_SUMMARY",
    "EXPLAIN_LAST_RESPONSE",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_COGNITION_RUNTIME",
    # EXPLAIN_ALL_REASONING_MODES: executor reads reasoning_modes.py and returns
    # the full multi-paragraph mode descriptions. Must bypass quick-mode 512-token
    # GGUF cap by going through the control evidence path (direct_evidence_actions
    # inside finalise_control_result returns the executor text unchanged).
    "EXPLAIN_ALL_REASONING_MODES",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "GUI_RUNTIME_AUDIT",
    "DIAGNOSE_WRAPPERS",
    "RESOLVE_RUNTIME_PATHS",
    "MEMORY_STATUS",
    "COGNITION_STATUS",
    "MEMORY_RECALL",
    "PERSONAL_MEMORY_SUMMARY",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "ROUTING_FAULT_EXPLAIN",
    "NAME_SOURCE_AUDIT",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
    "SELF_IMPROVEMENT_LOG",
    "SELF_UPDATE",
    "META_DIAGNOSTIC",
    "IMAGE_STATUS",
    "FRONTIER_STATUS",
    "ELI_IDENTITY_AUDIT",
    # Gaze engine control — start/stop/status/calibrate are executor-direct,
    # no GGUF synthesis needed.
    "GAZE_ENABLE",
    "GAZE_DISABLE",
    "GAZE_STATUS",
    "GAZE_CALIBRATE",
}


def _confidence_label_full(score: float) -> str:
    """Five-bucket confidence label. Replaces the old two-bucket
    ('very high' >= 0.9 else 'low') template that hid all middle ground."""
    s = float(score or 0.0)
    if s >= 0.85:
        return "very high"
    if s >= 0.70:
        return "high"
    if s >= 0.50:
        return "medium"
    if s >= 0.30:
        return "low"
    return "very low"

_BAD_PATH_RX = (
    re.compile(r"/home/[^/\s'\"`]+/[^\s'\"`]+"),
    re.compile(r"/data/user/eli[^\s'\"`]*"),
    re.compile(r"/etc/gguf-runtime[^\s'\"`]*"),
    re.compile(r"/usr/local/lib/gguf-runtime[^\s'\"`]*"),
    re.compile(r"\bmy_model\.gguf\b", re.I),
)

_BAD_PHRASES = (
    "based on the grounding evidence provided, i have undergone a self-update",
    "my memory isn't bound to files",
    "my memory isn't stored in files or tables",
    "i don't have access to the actual codebase",
    "confidentiality reasons",
    "no need for you to worry",
)

def normalise_action(action: Any) -> str:
    return str(action or "CHAT").strip().upper() or "CHAT"

def is_control_action(action: Any) -> bool:
    return normalise_action(action) in CONTROL_ACTIONS

def route_control_text(user_input: Any, current_action: Any = None) -> str | None:
    low = re.sub(r"\s+", " ", str(user_input or "").strip().lower())
    act = normalise_action(current_action)

    if re.fullmatch(r"(?:self[- ]?update|update yourself|refresh yourself|refresh all overlays)", low):
        return "SELF_UPDATE"

    if re.search(r"\b(confidence in (?:your|my) last response|which agents contributed|what agents contributed|last response trace|previous response trace|last turn trace)\b", low):
        return "EXPLAIN_LAST_RESPONSE"

    # Questions about identity/persona change over time are conversational —
    # let them stay as CHAT so the LLM can reflect on them naturally.
    _is_change_query = bool(re.search(
        r"\b(changed?|changing|shift(?:ed|ing)?|different\s+since|evolv(?:ed|ing)|alter(?:ed|ing)|adapt(?:ed|ing)|grown?|has\s+(?:it|your|the)\s+\w+\s+changed?)\b",
        low,
    ))
    # Conversational persona/relationship questions ("your likes", "our
    # interactions", "how you feel", "your personality") want a reflective
    # CHAT answer, not a runtime status dump. SELF_REPORT cannot produce these.
    _is_conversational_persona = bool(re.search(
        r"\b(your\s+(?:likes?|dislikes?|favou?rites?|hobbies|interests?|"
        r"feelings?|personality|opinion|thoughts?|mood)|"
        r"our\s+(?:interactions?|conversations?|chats?|relationship|history|"
        r"discussions?|talks?)|"
        r"how\s+(?:do\s+)?you\s+feel|what\s+do\s+you\s+(?:like|think|enjoy)|"
        r"about\s+(?:us|me\s+and\s+you|you\s+and\s+(?:me|i)))\b",
        low,
    ))
    if not _is_change_query and not _is_conversational_persona and re.search(
        r"\b("
        r"who are you"
        r"|who you are"
        # PHASE16C_IDENTITY_WHAT_ARE_YOU_BOUNDARY_FIX
        # Match identity questions such as "what are you?" or
        # "what are you exactly?", but do not match conversational
        # continuations such as "what are you talking about?".
        r"|what are you(?=\s*(?:[?!.,]*\s*$|(?:exactly|really|actually)[?!.,]*\s*$))"
        r"|do you know who you are"
        r"|tell me about yourself"
        r"|tell me .{0,40}who you are"
        r"|as (?:a |an )?(?:person|entity)"
        r"|your identity"
        r"|your persona"
        r"|persona evolved"
        r"|identity evolved"
        r"|defined with .{0,80}memories"
        r"|how .{0,80}(?:persona|identity).{0,80}(?:evolved|defined)"
        r")\b",
        low,
    ):
        return "SELF_REPORT"

    if re.search(
        r"\b("
        r"(?:what|which|latest|current|recent|last).{0,40}(?:image|images|picture|visual|render).{0,40}(?:status|update|job|output|processing|processed|generated)"
        r"|(?:image|images|picture|visual|render).{0,30}(?:status|update|job|processing|processed|generated)"
        r")\b",
        low,
    ):
        return "IMAGE_STATUS"

    if re.search(
        r"\b("
        r"eli identity audit"
        r"|classif(?:y|ication) (?:eli|yourself|you)"
        r"|what (?:exactly )?is eli"
        r"|what should eli be classified as"
        r"|what are you classified as"
        r"|verified (?:eli )?(?:identity|classification) audit"
        r")\b",
        low,
    ):
        return "ELI_IDENTITY_AUDIT"

    if re.search(
        r"\b("
        r"frontier status"
        r"|full system (?:status|audit|wiring|matrix)"
        r"|cross[- ]system (?:status|audit|wiring|matrix)"
        r"|full (?:project|eli) (?:audit|wiring|matrix)"
        r"|memory.*self[- ]aware.*proactive.*image.*world.*labs"
        r"|chat flow.*memory.*self.*proactive.*image.*world.*labs"
        r")\b",
        low,
    ):
        return "FRONTIER_STATUS"

    if re.search(r"\bwhat image (?:is|was|are|were).{0,30}(?:process|processed|processing|generated)\b", low):
        return "IMAGE_STATUS"

    if re.search(r"\b(show me the resolved runtime paths|resolved runtime paths|runtime paths for every critical file|critical file you depend on)\b", low):
        return "RESOLVE_RUNTIME_PATHS"

    if re.search(r"\b(explain|break down|show)\b", low) and re.search(r"\b(cognition|memory|agent|gui|router|executor|pipeline|faiss|faiis|fts5|hyde|rag|sqlite|wal|semantic|canonical)\b", low):
        return "EXPLAIN_COGNITION_RUNTIME"

    if re.search(r"\b(self[- ]?improvement|improvement)\s+log\b", low) or (
        re.search(r"\bexact\s+error\s+message\b", low)
        and re.search(r"\blast\s+failure\b", low)
    ):
        return "SELF_IMPROVEMENT_LOG"

    if re.search(r"\b(run a full runtime audit|run full runtime audit|runtime audit|system audit|health check|diagnostics?|what'?s actually broken|what is actually broken)\b", low):
        return "RUNTIME_AUDIT"

    # META_DIAGNOSTIC: clarification requests about ELI's own background activity.
    # The bare "what updates?" branch requires a disambiguation word (talking about,
    # mean, referring to, doing, going on) so "What updates have you performed?"
    # or "What updates and checks have you performed as of late?" route to SELF_REPORT
    # instead of being misidentified as a confused clarification request.
    if re.search(
        r"\b("
        r"what (?:updates?|changes?|routine checks?)\s+(?:are you|do you mean|did you mean|is that|is this|was that)"
        r"|what (?:updates?|changes?|routine checks?)\s+(?:talking about|mean|refer)"
        r"|what do you mean .{0,80}(?:updates?|processing|routine check|up and running|go live)"
        r"|what .{0,80}(?:updates?|processing|routine check|up and running|go live).{0,80}(?:talking about|mean)"
        r"|what (?:the )?(?:fuck|hell|heck) .{0,80}(?:updates?|processing|routine check|up and running|go live)"
        r")\b",
        low,
    ):
        return "META_DIAGNOSTIC"

    if re.search(r"\b(explain exactly how your memory system works internally|memory system works internally|which files.*which db tables.*which functions|memory runtime surface|memory runtime)\b", low):
        return "EXPLAIN_MEMORY_RUNTIME"

    if re.search(r"\b(what do you know about me|what have you stored about me|what do you remember about me|what you actually remember)\b", low):
        if re.search(r"\b(full|in[- ]?depth|which files|db tables|functions|internally|cognition pipeline)\b", low):
            return "PERSONAL_MEMORY_DEEP_EXPLAIN"
        return "PERSONAL_MEMORY_SUMMARY"

    if re.search(r"\bwhy\b.*\b(browser|web|online|search)\b", low):
        return "ROUTING_FAULT_EXPLAIN"

    if (
        ("how do you know" in low and "name" in low)
        or ("where" in low and "name" in low and ("file" in low or "stored" in low or "located" in low))
        or ("which file" in low and "name" in low)
    ):
        return "NAME_SOURCE_AUDIT"

    if re.search(r"\b(explain your cognition pipeline|cognition pipeline from input to output|input to output.*every step|cognitive pipeline)\b", low):
        return "EXPLAIN_COGNITION_RUNTIME"

    if act in CONTROL_ACTIONS:
        return act

    # === PHASE15_REDISTRIBUTABLE_META_DIAGNOSTIC_GATE ===
    # Do not convert ordinary conversational confusion into internal diagnostics.
    # META_DIAGNOSTIC is reserved for prompts that explicitly refer to ELI's
    # response/output/runtime/tooling and ask for fault explanation or tracing.
    _eli_phase15_meta_referent = bool(re.search(
        r"\b(response|answer|output|runtime|pipeline|router|executor|orchestrator|agent|tool|memory|browser|web|online|search|diagnostic|audit|system|eli)\b",
        low,
    ))
    _eli_phase15_meta_failure = bool(re.search(
        r"\b(wrong|broken|failed|failing|failure|issue|problem|root cause|empty|terrible|awful|bad|incorrect|drift|leak|leaking|happening|going on)\b",
        low,
    ))
    _eli_phase15_meta_request = bool(re.search(
        r"\b(debug|diagnose|diagnostic|audit|trace|inspect|explain|why|what)\b",
        low,
    ))
    _eli_phase15_browser_fault = bool(re.search(
        r"\bwhy\b.{0,80}\b(browser|web|online|search|youtube)\b",
        low,
    ))

    if (
        _eli_phase15_browser_fault
        or (
            _eli_phase15_meta_referent
            and _eli_phase15_meta_failure
            and _eli_phase15_meta_request
        )
    ):
        return "META_DIAGNOSTIC"

    return None

def _root() -> Path:
    return Path(__file__).resolve().parents[2]

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}

def runtime_paths() -> Dict[str, Any]:
    root = _root()
    snap = _read_json(root / "artifacts" / "runtime_snapshot.json")
    cfg = _read_json(root / "config" / "settings.json")

    model_path = str(
        snap.get("model_path")
        or cfg.get("model_path")
        or cfg.get("custom_model_path")
        or cfg.get("bundled_model_path")
        or ""
    ).strip()

    if model_path and not Path(model_path).expanduser().is_absolute():
        candidates = [
            (root / model_path).resolve(),
            (root / "models" / model_path).resolve(),
            (root / "models" / "gguf" / "base" / Path(model_path).name).resolve(),
        ]
        model_path = str(next((p for p in candidates if p.exists()), candidates[0]))

    return {
        "project_root": str(root),
        "python": str((root / ".venv" / "bin" / "python3").resolve()),
        "runtime_snapshot": str(root / "artifacts" / "runtime_snapshot.json"),
        "config_settings": str(root / "config" / "settings.json"),
        "model_path": model_path,
        "models_dir": str(root / "models"),
        "user_db": str(root / "artifacts" / "db" / "user.sqlite3"),
        "agent_db": str(root / "artifacts" / "db" / "agent.sqlite3"),
        "persona_base": str(root / "eli" / "cognition" / "persona.txt"),
        "persona_auto": str(root / "eli" / "cognition" / "persona.auto.txt"),
        "snapshot": snap,
    }

def _json_block(title: str, payload: Dict[str, Any]) -> str:
    return title + "\n" + json.dumps(payload, indent=2, ensure_ascii=False, default=str)

def _last_trace(engine: Any = None) -> Dict[str, Any]:
    try:
        meta = dict(getattr(engine, "_last_request_meta", {}) or {}) if engine is not None else {}
        if meta:
            return meta
    except Exception:
        pass

    try:
        from eli.runtime.last_trace import load_last_trace
        return dict(load_last_trace() or {})
    except Exception:
        return {}

def _trace_text(trace: Dict[str, Any]) -> str:
    if not trace:
        return "Previous-response trace evidence:\n- trace_available: false"

    agents = trace.get("agents_used") or trace.get("agents") or []

    agg = trace.get("aggregated_confidence")
    if agg is None:
        agg = trace.get("confidence")
    try:
        agg_val = float(agg) if agg is not None else None
    except (TypeError, ValueError):
        agg_val = None

    if agg_val is None:
        label = trace.get("confidence_label") or ""
    else:
        try:
            from eli.cognition.agent_bus import _confidence_label as _lbl
            label = _lbl(agg_val)
        except Exception:
            label = trace.get("confidence_label") or ""

    grounding = trace.get("grounding_confidence")
    conf_str = "" if agg_val is None else f"{agg_val:.2f}"

    return "\n".join([
        "Previous-response trace evidence:",
        f"- request_id: {trace.get('request_id') or ''}",
        f"- route_action: {trace.get('route_action') or trace.get('intent') or trace.get('action') or ''}",
        f"- result_action: {trace.get('result_action') or trace.get('action') or ''}",
        f"- confidence: {conf_str} (aggregated)",
        f"- confidence_label: {label}",
        f"- grounding_confidence: {grounding if grounding is not None else 'n/a'}",
        f"- agents_used: {', '.join(map(str, agents)) if agents else 'none recorded'}",
        f"- plan: {trace.get('plan') or trace.get('orchestrator_plan') or 'none'}",
        f"- evidence_used: {trace.get('evidence_used')}",
        f"- grounded: {trace.get('grounded')}",
    ])

def _recent_conversation_rows(engine: Any = None, limit: int = 12) -> list[Dict[str, Any]]:
    try:
        memory = getattr(engine, "memory", None)
        user_id = getattr(engine, "user_id", "default")
        if memory is not None and hasattr(memory, "get_recent_conversation"):
            rows = memory.get_recent_conversation(limit=int(limit), user_id=user_id)
            return [dict(row) for row in list(rows or [])]
    except Exception:
        pass
    return []

def _meta_diagnostic_report(engine: Any, action: str, user_input: Any, intent: Dict[str, Any] | None, bus_result: Any = None, trace: Dict[str, Any] | None = None) -> Dict[str, Any]:
    recent_rows = _recent_conversation_rows(engine, limit=16)
    last_trace = trace or _last_trace(engine)
    report: Dict[str, Any] = {
        "ok": True,
        "action": action,
        "question": str(user_input or ""),
        "route": {
            "current_action": normalise_action(action),
            "intent_action": normalise_action((intent or {}).get("action")),
            "matched_by": ((intent or {}).get("meta") or {}).get("matched_by"),
            "allow_chat_without_evidence": ((intent or {}).get("meta") or {}).get("allow_chat_without_evidence"),
        },
        "last_trace": last_trace,
        "recent_turn_diagnostics": {},
        "bus": {
            "agents_used": list(getattr(bus_result, "agents_used", []) or []) if bus_result is not None else [],
            "aggregated_confidence": getattr(bus_result, "aggregated_confidence", None) if bus_result is not None else None,
            "confidence_label": getattr(bus_result, "confidence_label", None) if bus_result is not None else None,
            "action_result": getattr(bus_result, "action_result", None) if bus_result is not None else None,
        },
        "runtime_paths": runtime_paths(),
        "image_status": None,
    }

    try:
        from eli.runtime.diagnostic_patterns import recent_turn_diagnostics
        report["recent_turn_diagnostics"] = recent_turn_diagnostics(recent_rows)
    except Exception as exc:
        report["recent_turn_diagnostics"] = {"error": repr(exc)}

    needs_image_status = False
    text = str(user_input or "").lower()
    if any(word in text for word in ("image", "picture", "visual", "render")):
        needs_image_status = True
    try:
        dyn = report.get("recent_turn_diagnostics") or {}
        if dyn.get("dynamic_status_claims") or dyn.get("challenge_after_dynamic_status_claim"):
            needs_image_status = True
    except Exception:
        pass

    if needs_image_status:
        try:
            from eli.runtime.evidence_ledger import status_evidence
            report["image_status"] = status_evidence(str(user_input or "image status"))
        except Exception as exc:
            report["image_status"] = {"ok": False, "error": repr(exc)}

    return report

def build_control_evidence(engine: Any, action: Any, args: Dict[str, Any] | None, user_input: Any, intent: Dict[str, Any] | None = None, bus_result: Any = None, trace: Dict[str, Any] | None = None) -> Dict[str, Any]:
    act = normalise_action(action)

    if act == "EXPLAIN_LAST_RESPONSE":
        prev = _last_trace(engine)
        text = _trace_text(prev)
        return {
            "ok": bool(prev),
            "action": act,
            "content": text,
            "response": text,
            "report": prev,
            "evidence_source": "last_trace",
        }

    if act == "META_DIAGNOSTIC":
        report = _meta_diagnostic_report(engine, act, user_input, intent, bus_result, trace)
        text = _json_block("Meta diagnostic evidence packet:", report)
        return {
            "ok": True,
            "action": act,
            "content": text,
            "response": text,
            "report": report,
            "evidence_source": "meta_diagnostic",
        }

    if act == "IMAGE_STATUS":
        try:
            from eli.runtime.evidence_ledger import status_evidence
            report = status_evidence(str(user_input or "image status"))
        except Exception as exc:
            report = {"ok": False, "error": repr(exc), "question": str(user_input or "")}
        text = _json_block("Image/status evidence packet:", report)
        return {
            "ok": bool(report.get("ok", True)),
            "action": act,
            "content": text,
            "response": text,
            "report": report,
            "evidence_source": "evidence_ledger",
        }

    if act == "SELF_UPDATE":
        report: Dict[str, Any] = {
            "ok": True,
            "action": act,
            "paths": runtime_paths(),
            "changed": {},
            "errors": [],
        }

        try:
            from eli.runtime.self_model_refresh import refresh_all_overlays_nonfatal, refresh_world_model_runtime
            report["changed"]["overlays"] = refresh_all_overlays_nonfatal(reason="user_self_update")
            report["changed"]["world_model_runtime"] = bool(refresh_world_model_runtime())
        except Exception as exc:
            report["ok"] = False
            report["errors"].append(repr(exc))

        text = _json_block("Self-update evidence packet:", report)
        return {
            "ok": bool(report.get("ok")),
            "action": act,
            "content": text,
            "response": text,
            "report": report,
            "evidence_source": "self_model_refresh",
        }

    if act == "USER_IDENTITY_SUMMARY":
        try:
            from eli.runtime.live_introspection import build_report
            rep = build_report(act)
            text = str((rep or {}).get("content") or (rep or {}).get("response") or "")
            if text.strip():
                return {
                    "ok": True,
                    "action": act,
                    "content": text,
                    "response": text,
                    "report": (rep or {}).get("report") or {"source": "live_introspection"},
                    "evidence_source": "live_introspection",
                }
        except Exception:
            pass
        try:
            from eli.runtime.personal_memory_surface import personal_memory_surface
            text = str(personal_memory_surface(user_input))
            return {
                "ok": True,
                "action": act,
                "content": text,
                "response": text,
                "report": {"source": "personal_memory_surface"},
                "evidence_source": "personal_memory_surface",
            }
        except Exception:
            pass

    try:
        ar = getattr(bus_result, "action_result", None) if bus_result is not None else None
        if isinstance(ar, dict) and ar.get("ok") is True:
            text = str(ar.get("content") or ar.get("response") or ar.get("result") or "").strip()
            if text:
                return {
                    "ok": True,
                    "action": act,
                    "content": text,
                    "response": text,
                    "report": ar.get("report") or ar,
                    "evidence_source": "agent_bus.action_result",
                }
    except Exception:
        pass

    try:
        from eli.execution.executor_enhanced import execute
        raw = execute(act, dict(args or {}))
        if isinstance(raw, dict):
            text = str(raw.get("content") or raw.get("response") or raw.get("result") or "").strip()
            if raw.get("ok") is True and text and "Unsupported executor action" not in text:
                return {
                    "ok": True,
                    "action": act,
                    "content": text,
                    "response": text,
                    "report": raw.get("report") or raw,
                    "evidence_source": "executor",
                }
    except Exception:
        pass

    try:
        from eli.runtime.live_introspection import build_report
        live = build_report(act, str(user_input or ""))
        if isinstance(live, dict):
            text = str(live.get("content") or live.get("response") or "").strip()
            if live.get("ok") and text:
                return {
                    "ok": True,
                    "action": act,
                    "content": text,
                    "response": text,
                    "report": live.get("report") or live,
                    "evidence_source": "live_introspection",
                }
    except Exception:
        pass

    fail = {
        "ok": False,
        "action": act,
        "error": "no_valid_control_evidence",
        "paths": runtime_paths(),
    }
    text = _json_block("control_action_evidence_failure", fail)

    return {
        "ok": False,
        "action": act,
        "content": text,
        "response": text,
        "report": fail,
        "evidence_source": "failure",
    }


_DYNAMIC_FALSE_CLAIMS = (
    "updated my model",
    "updating my model",
    "new settings include updating my model",
    "configured my environment",
    "no memory mapping",
    "no mmap",
    "mlock is being used",
    "no mlock",
    "python 3.12 is my interpreter",
    "i have undergone a self-update",
    "i've just completed a self-update process",
    "how can i assist you today",
    "i'd be happy to",
    "i will conduct",
    "i'll conduct",
    "i will perform",
    "i'll perform",
    "i will run",
    "i'll run",
    "let's start",
    "i'll report back",
    "i will report back",
    "once the audit is complete",
    "what specific information were you looking for",
    "what specific aspect",
    "please clarify",
    "if you need details, please specify",
    "you may need to ask eli directly",
    "i don't have information about a person named eli",
    "your state isn't felt or expressed",
    "feel free to ask",
    "let me know if",
)


# === ELI_PHASE19_CONTROL_TRUTH_LOCK_V1 ===
_ELI_PHASE19_LINE_CLAIM_RX = re.compile(
    r"\blines?\s+((?:\d+\s*(?:(?:,|/|-|and|or)\s*)?)+)",
    re.IGNORECASE,
)
_ELI_PHASE19_MUTATION_CLAIM_RX = re.compile(
    r"\b(?:"
    r"i(?:'|’)?ll\s+(?:delete|remove|fix|patch|edit|change|apply)"
    r"|i\s+will\s+(?:delete|remove|fix|patch|edit|change|apply)"
    r"|i(?:'|’)?ve\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r"|i\s+have\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r"|i\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r"|already\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r")\b",
    re.IGNORECASE,
)

def _eli_phase19_line_claims_supported(out: str, ev: str) -> bool:
    for match in _ELI_PHASE19_LINE_CLAIM_RX.finditer(str(out or "")):
        numbers = re.findall(r"\d+", match.group(1) or "")
        if numbers and any(num not in str(ev or "") for num in numbers):
            return False
    return True

def _eli_phase19_mutation_claim_supported(out: str, ev: str) -> bool:
    m = _ELI_PHASE19_MUTATION_CLAIM_RX.search(str(out or ""))
    if not m:
        return True
    phrase = re.sub(r"\s+", " ", m.group(0).lower()).strip()
    ev_low = re.sub(r"\s+", " ", str(ev or "").lower()).strip()
    return bool(phrase and phrase in ev_low)

# === END ELI_PHASE19_CONTROL_TRUTH_LOCK_V1 ===

def output_violates_evidence(text: Any, evidence_text: Any = "") -> bool:
    out = str(text or "")
    ev = str(evidence_text or "")

    if not out.strip():
        return True

    stripped = out.strip()
    low = out.lower()
    ev_low = ev.lower()

    if stripped.endswith("?") and re.match(
        r"(?is)^\s*(who|what|when|where|why|how|do|does|did|is|are|can|could|should|would)\b",
        stripped,
    ):
        return True

    if any(p in low for p in _BAD_PHRASES):
        return True

    if any(p in low for p in _DYNAMIC_FALSE_CLAIMS):
        return True

    if "memory_entries" in ev_low and re.search(
        r"(?is)\b(?:does not provide|cannot provide|don'?t have)\b.{0,80}\b(?:specific count|count of memories|how many memories)\b",
        out,
    ):
        return True

    if (
        "i am eli" in ev_low
        or '"name": "eli"' in ev_low
        or "'name': 'eli'" in ev_low
    ) and re.search(r"\byour (?:identity|persona)\b", low):
        return True

    for rx in _BAD_PATH_RX:
        for match in rx.findall(out):
            if str(match) not in ev:
                return True

    # If the answer mentions a concrete runtime parameter, the supporting value
    # must already exist in the evidence packet. This blocks polished guesses.
    concrete_terms = [
        "n_ctx", "context size", "gpu layers", "batch size", "cpu threads",
        "temperature", "mmap", "mlock", "model path", "provider",
        "user database", "agent database", "runtime snapshot",
    ]
    for term in concrete_terms:
        if term in low and term not in ev_low:
            if term in {"context size", "gpu layers", "batch size", "cpu threads", "model path", "user database", "agent database"}:
                continue
            return True

    # ELI_PHASE19_CONTROL_TRUTH_CHECKS_V1
    # Exact line references and claims of code mutation are not allowed unless
    # the deterministic evidence packet supports them.
    if not _eli_phase19_line_claims_supported(out, ev):
        return True
    if not _eli_phase19_mutation_claim_supported(out, ev):
        return True

    return False

def compact_evidence_answer(action: str, evidence_result: Dict[str, Any]) -> str:
    act = normalise_action(action)
    report = evidence_result.get("report")
    content = str(evidence_result.get("content") or evidence_result.get("response") or "").strip()

    if act == "SELF_UPDATE" and isinstance(report, dict):
        paths = report.get("paths") or {}
        changed = report.get("changed") or {}
        errors = report.get("errors") or []
        lines = [
            "Self-update result:",
            f"- ok: {bool(report.get('ok'))}",
            f"- project_root: {paths.get('project_root', '')}",
            f"- model_path: {paths.get('model_path', '')}",
            f"- runtime_snapshot: {paths.get('runtime_snapshot', '')}",
            f"- user_db: {paths.get('user_db', '')}",
            f"- agent_db: {paths.get('agent_db', '')}",
            f"- persona_base: {paths.get('persona_base', '')}",
            f"- persona_auto: {paths.get('persona_auto', '')}",
            f"- overlay_refresh: {changed.get('overlays', {})}",
            f"- world_model_runtime_refreshed: {changed.get('world_model_runtime', False)}",
            f"- errors: {errors}",
            "No model path, runtime path, or configuration value is reported as changed unless the evidence above says so.",
        ]
        return "\n".join(lines)

    if act == "EXPLAIN_LAST_RESPONSE" and isinstance(report, dict):
        agents = report.get("agents_used") or report.get("agents") or []
        return "\n".join([
            "Last-response trace:",
            f"- request_id: {report.get('request_id', '')}",
            f"- route_action: {report.get('route_action') or report.get('intent') or report.get('action') or ''}",
            f"- result_action: {report.get('result_action') or report.get('action') or ''}",
            f"- confidence: {report.get('confidence') or report.get('aggregated_confidence') or ''}",
            f"- confidence_label: {report.get('confidence_label') or ''}",
            f"- agents_used: {', '.join(map(str, agents)) if agents else 'none recorded'}",
            f"- plan: {report.get('plan') or report.get('orchestrator_plan') or 'none'}",
            f"- evidence_used: {report.get('evidence_used')}",
            f"- grounded: {report.get('grounded')}",
        ])

    if content:
        return content

    return json.dumps(
        {
            "surface": "missing_control_evidence",
            "action": act,
            "reason": "no_usable_grounded_evidence",
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )

def finalise_control_result(engine: Any, user_input: Any, action: str, evidence_result: Dict[str, Any], trace: Dict[str, Any] | None = None, bus_result: Any = None, synthesized_text: Any = None) -> Dict[str, Any]:
    act = normalise_action(action)
    evidence_text = str(evidence_result.get("content") or evidence_result.get("response") or "").strip()
    compact = compact_evidence_answer(action, evidence_result)
    final_text = str(synthesized_text or "").strip()

    if output_violates_evidence(final_text, evidence_text + "\n" + compact):
        final_text = ""

    direct_evidence_actions = {
        "SELF_REPORT",
        "RUNTIME_STATUS",
        "GPU_STATUS",
        "REASONING_MODE_STATUS",
        "USER_IDENTITY_SUMMARY",
        "EXPLAIN_LAST_RESPONSE",
        "EXPLAIN_MEMORY_RUNTIME",
        "EXPLAIN_COGNITION_RUNTIME",
        # Returns full multi-paragraph mode descriptions from reasoning_modes.py —
        # must not be truncated by quick-mode GGUF synthesis (512 tok cap).
        "EXPLAIN_ALL_REASONING_MODES",
        "RUNTIME_AUDIT",
        "IMPORT_AUDIT",
        "GUI_RUNTIME_AUDIT",
        "RESOLVE_RUNTIME_PATHS",
        "MEMORY_STATUS",
        "COGNITION_STATUS",
        "FRONTIER_STATUS",
        "ELI_IDENTITY_AUDIT",
        "MEMORY_RECALL",
        "SELF_ANALYZE",
        "SELF_IMPROVE",
        "SELF_IMPROVEMENT_LOG",
        "SELF_UPDATE",
        # Gaze engine — executor returns status text directly, no GGUF pass.
        "GAZE_ENABLE",
        "GAZE_DISABLE",
        "GAZE_STATUS",
        "GAZE_CALIBRATE",
    }
    # Mode contract:
    #   * Quick mode → engine passes synthesized_text="" so compact (deterministic
    #     evidence) becomes the answer. Quick is evidence-final by design.
    #   * Non-quick modes (CoT/ToT/Self-C/Constitutional) → engine runs a
    #     dedicated single-call control synthesis with evidence as immutable
    #     ground truth, then the governor validates. Synthesized text that
    #     passes the governor is the answer; if it failed/was empty, compact
    #     is the fallback.
    if act in direct_evidence_actions and not final_text:
        final_text = compact

    # For control actions, do not let the output governor re-expand with generic chat.
    ok = bool(evidence_result.get("ok", False))
    if not final_text:
        ok = False
    agents = list(getattr(bus_result, "agents_used", []) or [])

    if not agents:
        source = str(evidence_result.get("evidence_source") or "executor")
        agents = ["introspection"] if "runtime" in source or "introspection" in source else [source]

    # Confidence: ONLY the bus-aggregated value. No synthetic fallback —
    # if the bus produced no measurement, label it 'unmeasured' rather
    # than fabricate 0.96 from `ok`. The 0.96/0.25 stub previously here
    # was responsible for the "very high (0.96)" label appearing on
    # turns where no real agent evidence was collected.
    raw_conf = getattr(bus_result, "aggregated_confidence", None)
    if raw_conf is None:
        confidence = None
        confidence_label = "unmeasured"
    else:
        confidence = float(raw_conf or 0.0)
        confidence_label = _confidence_label_full(confidence)

    meta = {
        "request_id": (trace or {}).get("request_id") if isinstance(trace, dict) else "",
        "route_action": action,
        "result_action": action,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "agents_used": agents,
        "plan": getattr(bus_result, "orchestrator_plan", None) or "control_evidence_contract",
        "evidence_used": True,
        "grounded": True,
        "evidence_source": evidence_result.get("evidence_source"),
    }

    try:
        engine._last_request_meta = dict(meta)
        from eli.runtime.last_trace import save_last_trace
        save_last_trace(meta)
    except Exception:
        pass

    try:
        if hasattr(engine, "_store_assistant_turn"):
            engine._store_assistant_turn(final_text)
    except Exception:
        pass

    # Keep the structured `report` and full `meta` blocks INSIDE the envelope
    # for downstream telemetry/learning, but ensure `content`/`response` are
    # always plain text so any caller that str()s the result will still emit
    # the user-facing answer rather than the entire envelope.
    if not final_text:
        final_text = json.dumps(
            {
                "surface": "control_result_without_visible_synthesis",
                "action": action,
                "reason": "empty_final_text",
            },
            ensure_ascii=False,
            default=str,
            indent=2,
        )

    return {
        "ok": ok,
        "action": action,
        "content": final_text,
        "response": final_text,
        "confidence": confidence,
        "confidence_score": confidence,
        "evidence_used": True,
        "grounded": True,
        "report": evidence_result.get("report"),
        "meta": {
            "reasoning": {
                "confidence": confidence,
                "grounded": True,
                "evidence_used": True,
            },
            "trace": trace or {},
            "control_contract": meta,
        },
        "trace": trace,
    }
