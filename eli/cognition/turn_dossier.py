"""Turn dossier — single assembly point for awareness, memory, and cognition context.

Extends existing primitives (retrieve_for_turn, user_model, insight cache, proactive
artifacts) without duplicating storage. Every CHAT turn gets a dossier; downstream
paths may compress presentation (phatic) but must not zero the underlying knowledge.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_PHATIC_SEMANTIC_LIMIT = 4
_PHATIC_CONV_LIMIT = 4
_NORMAL_SEMANTIC_LIMIT = 12
_NORMAL_CONV_LIMIT = 8


@dataclass
class TurnDossier:
    query: str = ""
    query_class: str = "GENERAL"
    reasoning_mode: str = "quick"
    identity_block: str = ""
    user_brief: str = ""
    retrieval_text: str = ""
    semantic_hits: List[Dict[str, Any]] = field(default_factory=list)
    proactive_block: str = ""
    insight_block: str = ""
    deepening_block: str = ""
    session_opener: str = ""
    emotion_trend: str = ""
    working_memory_block: str = ""
    provenance: List[str] = field(default_factory=list)

    def awareness_blocks(self) -> List[str]:
        """Ordered blocks for persona handoff injection."""
        out: List[str] = []
        if self.session_opener:
            out.append(self.session_opener)
        if self.identity_block:
            out.append(self.identity_block)
        if self.user_brief:
            out.append(self.user_brief)
        if self.working_memory_block:
            out.append(self.working_memory_block)
        if self.insight_block:
            out.append(self.insight_block)
        if self.proactive_block:
            out.append(self.proactive_block)
        if self.deepening_block:
            out.append(self.deepening_block)
        if self.emotion_trend:
            out.append(self.emotion_trend)
        if self.retrieval_text:
            out.append(self.retrieval_text)
        return [b for b in out if str(b or "").strip()]

    def memory_context(self) -> str:
        """Compact memory string for bus/orchestrator fallback."""
        parts = [p for p in (
            self.user_brief,
            self.working_memory_block,
            self.retrieval_text,
        ) if str(p or "").strip()]
        return "\n\n".join(parts).strip()


def _read_fresh_artifact(path, max_age_s: float) -> str:
    try:
        p = path
        if not p.exists():
            return ""
        if (time.time() - p.stat().st_mtime) > max_age_s:
            return ""
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def build_session_opener(engine: Any) -> str:
    """One-line proactive opener for first substantive turn after idle."""
    try:
        from eli.runtime.pending_proposal import get_pending_proposal
        pending = get_pending_proposal()
        if pending and pending.get("summary"):
            return (
                "[SESSION OPENER — ELI initiated]\n"
                + str(pending.get("summary") or "").strip()[:400]
            )
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    try:
        mem = getattr(engine, "memory", None)
        if mem is not None:
            rows = mem.recall_memory(
                "morning_report proactive briefing",
                limit=1,
                tags=["morning_report"],
            ) or []
            if rows:
                text = str(rows[0].get("text") or rows[0].get("content") or "").strip()
                if text and len(text) > 40:
                    return f"[SESSION OPENER — overnight briefing]\n{text[:500]}"
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return ""


def assemble_turn_dossier(
    engine: Any,
    query: str,
    *,
    query_class: str = "GENERAL",
    reasoning_mode: str = "quick",
    session_id: str = "",
    user_id: str = "",
    working_memory: Any = None,
    include_session_opener: bool = False,
) -> TurnDossier:
    """Populate turn knowledge from existing subsystems (read-only assembly)."""
    dossier = TurnDossier(
        query=str(query or "").strip(),
        query_class=str(query_class or "GENERAL").upper(),
        reasoning_mode=str(reasoning_mode or "quick"),
    )
    phatic = dossier.query_class == "PHATIC"

    # Identity + user brief (always)
    try:
        from eli.kernel.state import get_user_name, get_user_profile_text
        name = (get_user_name() or "").strip()
        profile = (get_user_profile_text() or "").strip()
        if name:
            dossier.identity_block = f"[USER IDENTITY — verified]\nName: {name}"
            dossier.provenance.append("kernel.state")
        if profile:
            dossier.user_brief = f"[USER PROFILE — structured snapshot]\n{profile[:1200]}"
            dossier.provenance.append("user_profile.json")
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    try:
        from eli.runtime.user_model import get_user_brief
        brief = (get_user_brief() or "").strip()
        if brief:
            dossier.user_brief = (
                (dossier.user_brief + "\n\n" if dossier.user_brief else "")
                + f"[USER MODEL — dynamic brief]\n{brief[:900]}"
            )
            dossier.provenance.append("user_model")
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    if working_memory is not None:
        try:
            wm_block = working_memory.context_block()
            if wm_block:
                dossier.working_memory_block = wm_block
                dossier.provenance.append("working_memory")
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    # Shared retrieval (light for phatic, full otherwise)
    mem = getattr(engine, "memory", None)
    if mem is not None and dossier.query:
        try:
            from eli.memory.retrieval import retrieve_for_turn
            sem_lim = _PHATIC_SEMANTIC_LIMIT if phatic else _NORMAL_SEMANTIC_LIMIT
            conv_lim = _PHATIC_CONV_LIMIT if phatic else _NORMAL_CONV_LIMIT
            result = retrieve_for_turn(
                mem,
                dossier.query,
                user_id=user_id or getattr(engine, "user_id", "") or "",
                session_id=session_id or getattr(engine, "session_id", "") or "",
                semantic_limit=sem_lim,
                conv_limit=conv_lim,
                recent_limit=6 if phatic else 12,
                summary_limit=2 if phatic else 4,
                enable_hop2=not phatic,
                rerank=True,
            )
            dossier.semantic_hits = list(result.semantic_hits or [])
            lines: List[str] = []
            if phatic:
                lines.append(
                    "[MEMORY — light recall for rapport; do not dump unprompted biography]"
                )
            else:
                lines.append("[MEMORY — retrieved for this turn]")
            for hit in (result.semantic_hits or [])[:sem_lim]:
                text = str(hit.get("text") or hit.get("content") or "").strip()
                if text:
                    prov = str(hit.get("provenance_kind") or hit.get("source") or "")
                    tag = f" ({prov})" if prov else ""
                    lines.append(f"  • {text[:280]}{tag}")
            for hit in (result.conv_hits or [])[:3]:
                text = str(hit.get("text") or hit.get("content") or hit.get("snippet") or "").strip()
                if text:
                    lines.append(f"  • [past turn] {text[:220]}")
            if len(lines) > 1:
                dossier.retrieval_text = "\n".join(lines)
                dossier.provenance.append("retrieve_for_turn")
            if working_memory is not None and dossier.semantic_hits:
                try:
                    working_memory.absorb_memory_hits(dossier.semantic_hits)
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
        except Exception as exc:
            log.debug("[TURN_DOSSIER] retrieval skipped: %s", exc)

    # Background cognition artifacts
    try:
        from eli.core.paths import get_paths
        art = get_paths().artifacts_dir
        pro_text = _read_fresh_artifact(art / "proactive" / "latest_context.txt", 1800)
        if pro_text:
            dossier.proactive_block = f"[PROACTIVE AWARENESS]\n{pro_text}"
            dossier.provenance.append("latest_context.txt")
        deep_text = _read_fresh_artifact(art / "proactive" / "latest_deepening.txt", 3600)
        if deep_text:
            dossier.deepening_block = f"[PRIOR DEEPENING — related turn]\n{deep_text[:800]}"
            dossier.provenance.append("latest_deepening.txt")
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    try:
        from eli.planning.insight_synthesis import get_cached_insight
        insight = (get_cached_insight() or "").strip()
        if insight:
            dossier.insight_block = f"[BACKGROUND REFLECTION — synthesised insight]\n{insight[:500]}"
            dossier.provenance.append("reflection_insight.json")
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    try:
        from eli.cognition.emotion_timeline import trend_line
        trend = (trend_line(limit=4) or "").strip()
        if trend:
            dossier.emotion_trend = f"[EMOTION TREND — recent register]\n{trend[:400]}"
            dossier.provenance.append("emotion_timeline")
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    if include_session_opener:
        opener = build_session_opener(engine)
        if opener:
            dossier.session_opener = opener
            dossier.provenance.append("session_opener")

    return dossier


def handoff_blocks_from_dossier(
    dossier: Optional[TurnDossier],
    *,
    phatic: bool = False,
    max_chars: int = 0,
) -> List[str]:
    """Compress dossier awareness for persona/phatic handoff injection."""
    if dossier is None:
        return []
    blocks = list(dossier.awareness_blocks() or [])
    if not blocks:
        return []
    if phatic:
        # Keep rapport-oriented awareness; full retrieval dump stays in dossier_context.
        trimmed: List[str] = []
        for block in blocks:
            if block.startswith("[MEMORY — retrieved for this turn]"):
                continue
            trimmed.append(block)
        blocks = trimmed or blocks[:4]
    if max_chars <= 0:
        return blocks
    out: List[str] = []
    total = 0
    for block in blocks:
        chunk = str(block or "").strip()
        if not chunk:
            continue
        if total + len(chunk) > max_chars:
            remain = max_chars - total
            if remain > 80:
                out.append(chunk[:remain] + "…")
            break
        out.append(chunk)
        total += len(chunk) + 2
    return out


def attach_dossier_to_working_memory(working_memory: Any, dossier: TurnDossier) -> None:
    """Store dossier on WorkingMemory for handoff/bus/orchestrator consumers."""
    if working_memory is None:
        return
    try:
        setattr(working_memory, "turn_dossier", dossier)
        setattr(working_memory, "dossier_context", dossier.memory_context())
        setattr(working_memory, "reranked_hits", list(dossier.semantic_hits or []))
    except Exception:
        log.debug("suppressed exception", exc_info=True)
