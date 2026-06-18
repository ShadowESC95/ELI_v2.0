"""Evidence planner + gatherer — the DAG/plan principle for generative & grounded tasks.

Before ELI writes a document / script (or any grounded synthesis) it must INTUIT
what evidence the task needs, run the real agents/tools to gather it, and
synthesise from THAT — never from generic priors. This is the hybrid mechanism
the design requires:

  1. plan_channels(): the model proposes which evidence channels THIS task needs
     (intuition/awareness), over a fixed set of *real* evidence sources. A
     deterministic, signal-based floor guarantees the obvious channel is always
     chosen even if the model step is skipped (quick mode) or fails — so it is
     reliable without hardcoding the OUTPUT.
  2. gather(): runs the real agent/tool per channel — the SAME agents the bus
     uses — in the live process, and returns grounded evidence + sources.

Channels (each backed by a real tool):
  • code    → code_examiner (tier-1/2 always; tier-3 LLM logic review in deeper
              modes) + a file_code repo scan + the self-improvement failure/proposal
              signals + the architecture blueprint. This is the "actually analyse
              the files to see what can be upgraded" path.
  • web     → WEB_SEARCH (net-gated; no-ops offline).
  • memory  → memory recall (user/project facts).
  • runtime → live runtime/system status.

Mode-aware (deeper modes gather deeper), bounded, exception-isolated. No hardcoded
output: the planner only ever chooses among real evidence sources.
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

KNOWN_CHANNELS = ("code", "web", "memory", "runtime")
_DEEP_MODES = {"self_consistency", "tree_of_thoughts", "constitutional_ai"}
_PER_CHANNEL_CAP = 1800
_TOTAL_CAP = 5200


# --------------------------------------------------------------------------- #
# Planning                                                                    #
# --------------------------------------------------------------------------- #
def _deterministic_channels(action: str, query: str) -> List[str]:
    """Signal-based FLOOR — guarantees the obvious channel is gathered even when
    the model planning step is skipped/fails. Not the final word; unioned with the
    model's proposal in plan_channels()."""
    low = (query or "").lower()
    chans: List[str] = []
    self_code = bool(re.search(
        r"\b(yourself|your own|\beli\b|upgrade|improve|refactor|optimi[sz]e|"
        r"your (?:code|architecture|capabilit\w*|design|system|runtime|brain|agents?|memory))\b",
        low))
    code_topic = self_code or bool(re.search(
        r"\b(code|codebase|module|function|class|repo|repository|pipeline|agent|"
        r"router|executor|gguf|inference|architecture|subsystem)\b", low))
    personal = bool(re.search(r"\b(my|mine|our|i|me|we)\b", low))
    if code_topic:
        chans.append("code")
    if self_code:
        chans.append("runtime")
    if personal:
        chans.append("memory")
    # A non-code, non-personal subject is an external-world topic → web (net-gated).
    if not code_topic and not personal:
        chans.append("web")
    return list(dict.fromkeys(chans))  # dedupe, keep order


def _model_channels(action: str, query: str) -> List[str]:
    """Ask the model which evidence channels THIS task needs (intuition). Returns a
    validated subset of KNOWN_CHANNELS, or [] on any failure. Best-effort + cheap."""
    try:
        from eli.cognition import gguf_inference as _g
        if _g.load_model() is None:
            return []
        sys = (
            "You are ELI's evidence planner. Given a task, decide which evidence "
            "sources ELI should gather BEFORE writing, choosing only from this set:\n"
            "  code    – analyse ELI's own source code / architecture (for tasks about "
            "ELI, its upgrades, its code)\n"
            "  web     – search the web (for external/world facts)\n"
            "  memory  – recall stored user/project memories (for personal/'my' tasks)\n"
            "  runtime – read ELI's live runtime/system status\n"
            "Reply with ONLY a JSON array of the needed channel names, e.g. [\"code\",\"runtime\"]. "
            "Choose the minimal set that actually grounds the task."
        )
        out = _g.chat_completion(f"Task ({action}): {query}", system=sys,
                                 max_tokens=40, temperature=0.0, top_p=0.9)
        import json as _json
        m = re.search(r"\[.*?\]", str(out or ""), re.S)
        if not m:
            return []
        picked = _json.loads(m.group(0))
        return [c for c in picked if isinstance(c, str) and c in KNOWN_CHANNELS]
    except Exception as e:
        log.debug(f"[EVIDENCE] model planning skipped: {e}")
        return []


def plan_channels(action: str, query: str, mode: str = "quick") -> List[str]:
    """Hybrid plan: deterministic floor ∪ model proposal. The model proposes only
    in non-quick modes (keeps the quick hot-path fast); the floor always applies."""
    chans = _deterministic_channels(action, query)
    if str(mode or "quick").strip().lower() != "quick":
        for c in _model_channels(action, query):
            if c not in chans:
                chans.append(c)
    return chans or ["web"]


# --------------------------------------------------------------------------- #
# Gathering — each channel runs the REAL agent/tool                            #
# --------------------------------------------------------------------------- #
def _gather_code(query: str, mode: str, session_id: str, user_id: str) -> Tuple[str, List[str]]:
    blocks: List[str] = []
    src: List[str] = []
    deep = str(mode or "quick").strip().lower() in _DEEP_MODES
    # (a) real code analysis — "what could actually be upgraded": syntax/lint
    #     (+ LLM logic review in deeper modes) over resolved targets.
    try:
        from eli.runtime import code_examiner as _ce
        targets = _ce.resolve_targets(query)
        if targets:
            findings = _ce.examine(targets, run_tier3=deep)
            report = _ce.format_report(targets, findings)
            if report and report.strip():
                blocks.append("Code analysis (real findings from a repo scan):\n" + report.strip()[:2000])
                src.append("code_examiner")
    except Exception as e:
        log.debug(f"[EVIDENCE] code_examiner failed: {e}")
    # (b) self-improvement signals — real failures + pending upgrade proposals.
    try:
        from eli.runtime.self_improvement import get_self_improvement
        fails = get_self_improvement().analyze_failures(limit=8, days=21, min_cluster_size=1) or []
        fl = []
        for f in fails[:8]:
            if isinstance(f, dict):
                s = str(f.get("summary") or f.get("pattern") or f.get("user_input")
                        or f.get("error") or "").strip()
                if s:
                    fl.append("  - " + s[:160])
        if fl:
            blocks.append("ELI failure / improvement signals (self-improvement engine):\n" + "\n".join(fl))
            src.append("self_improvement")
    except Exception:
        pass
    # (c) file_code repo scan — real source lines from core subsystems.
    try:
        from eli.cognition.agent_bus import FileCodeAgent
        fcq = query
        if not re.search(r"\b(code|module|agent|router|executor|memory|pipeline|gguf|inference)\b",
                         (query or "").lower()):
            fcq = query + " agent_bus router executor memory orchestrator gguf inference pipeline"
        r = FileCodeAgent().run(fcq, {"action": "CHAT"}, session_id, user_id)
        snips = ((getattr(r, "data", None) or {}).get("snippets")) or []
        if snips:
            blocks.append("Source-code evidence (file:line: content):\n"
                          + "\n".join(str(s) for s in snips[:10]))
            src.append("file_code")
    except Exception:
        pass
    # (d) latest test-suite report — so upgrade proposals cite real correctness state.
    try:
        from pathlib import Path as _P
        rep = _P(__file__).resolve().parents[2] / "artifacts" / "test_report.md"
        if rep.is_file():
            txt = rep.read_text(encoding="utf-8", errors="ignore").strip()
            if txt:
                blocks.append("Latest test-suite report (artifacts/test_report.md):\n" + txt[:1200])
                src.append("test_report")
    except Exception:
        pass
    # (e) architecture grounding (concise; last).
    try:
        from eli.execution.executor_enhanced import _eli_self_description_block
        arch = _eli_self_description_block(1400)
        if arch:
            blocks.append("ELI architecture (blueprints/what_eli_is.md):\n" + arch)
            src.append("blueprints")
    except Exception:
        pass
    return _join(blocks), src


def _gather_web(query: str) -> Tuple[str, List[str]]:
    try:
        from eli.execution.executor_enhanced import _execute_impl
        res = _execute_impl("WEB_SEARCH", {"query": query})
        if isinstance(res, dict) and res.get("web_grounded") and res.get("results"):
            return str(res.get("content") or "").strip(), ["web_search"]
    except Exception:
        pass
    return "", []


def _gather_memory(query: str) -> Tuple[str, List[str]]:
    try:
        from eli.memory import get_memory
        hits = get_memory().recall_memory(query, limit=8) or []
        ml = []
        for h in hits[:8]:
            t = h.get("text") if isinstance(h, dict) else str(h)
            if t and str(t).strip():
                ml.append("  - " + str(t).strip()[:180])
        if ml:
            return "Relevant stored memories:\n" + "\n".join(ml), ["memory.recall"]
    except Exception:
        pass
    return "", []


def _gather_runtime(query: str) -> Tuple[str, List[str]]:
    try:
        from eli.execution.executor_enhanced import _execute_impl
        res = _execute_impl("RUNTIME_STATUS", {})
        body = str((res or {}).get("content") or (res or {}).get("response") or "").strip()
        if body:
            return "ELI live runtime status:\n" + body[:1400], ["runtime_status"]
    except Exception:
        pass
    return "", []


def _join(blocks: List[str]) -> str:
    return "\n\n".join(b for b in blocks if b and b.strip()).strip()


def _channel_fn(ch: str, query: str, mode: str, session_id: str, user_id: str):
    if ch == "code":
        return _gather_code(query, mode, session_id, user_id)
    if ch == "web":
        return _gather_web(query)
    if ch == "memory":
        return _gather_memory(query)
    if ch == "runtime":
        return _gather_runtime(query)
    return "", []


def gather(channels: List[str], query: str, mode: str = "quick",
           session_id: str = "", user_id: str = "") -> Tuple[str, List[str]]:
    """Run the real agent/tool for each planned channel and merge. The channels are
    independent, so they run in PARALLEL on the DAG orchestrator (per-channel isolated
    — one failing yields no evidence, never blocks the others). Results are merged in
    deterministic KNOWN_CHANNELS order regardless of completion order. Falls back to a
    sequential sweep if the orchestrator is unavailable."""
    sel = [c for c in channels if c in KNOWN_CHANNELS]
    if not sel:
        return "", []
    outcomes: Dict[str, Tuple[str, List[str]]] = {}
    try:
        from eli.core.dag import Task, Orchestrator
        tasks = [
            Task(id=ch, critical=False,
                 run=(lambda c, _ch=ch: _channel_fn(_ch, query, mode, session_id, user_id)))
            for ch in sel
        ]
        report = Orchestrator(max_workers=max(2, len(sel))).run(tasks)
        for ch in sel:
            o = report.outcomes.get(ch)
            if o is not None and o.ok and o.result:
                outcomes[ch] = o.result
    except Exception as e:
        log.debug(f"[EVIDENCE] parallel gather failed ({e}); sequential fallback")
        for ch in sel:
            try:
                outcomes[ch] = _channel_fn(ch, query, mode, session_id, user_id)
            except Exception:
                outcomes[ch] = ("", [])

    parts: List[str] = []
    sources: List[str] = []
    for ch in KNOWN_CHANNELS:                       # deterministic merge order
        if ch not in outcomes:
            continue
        ev, s = outcomes[ch]
        if ev:
            parts.append(ev[:_PER_CHANNEL_CAP])
            sources.extend(s or [])
    return _join(parts)[:_TOTAL_CAP], list(dict.fromkeys(sources))


def plan_and_gather(action: str, query: str, mode: str = "quick",
                    session_id: str = "", user_id: str = "") -> Tuple[str, List[str]]:
    """Plan the evidence channels for this task, then gather them. The one entry
    point callers use. Returns (evidence_text, sources)."""
    if os.environ.get("ELI_EVIDENCE_PLANNER", "1").strip().lower() in ("0", "false", "no", "off"):
        return "", []
    try:
        channels = plan_channels(action, query, mode)
        log.debug(f"[EVIDENCE] action={action} mode={mode} channels={channels}")
        return gather(channels, query, mode, session_id, user_id)
    except Exception as e:
        log.debug(f"[EVIDENCE] plan_and_gather failed: {e}")
        return "", []


__all__ = ["plan_channels", "gather", "plan_and_gather", "KNOWN_CHANNELS"]
