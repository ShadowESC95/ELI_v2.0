"""Local screen analysis — depth modes, memory recall, research context.

All processing stays on-device: screenshot → local VL + OCR → optional
memory/RAG fusion. No network unless the user has lifted the Net toggle.
"""
from __future__ import annotations

import re
from typing import Any

from eli.utils.log import get_logger

log = get_logger(__name__)

_DEPTH_PROMPTS = {
    "quick": (
        "You are ELI looking at the user's screen. In 2-4 sentences, say what app "
        "is focused, what the user appears to be doing, and any obvious errors or "
        "important on-screen text. Only describe what you can actually see."
    ),
    "standard": (
        "You are ELI looking at the user's screen. Describe: (1) focused application "
        "and window layout, (2) what the user is doing, (3) all important visible text, "
        "code, numbers, errors, and UI state, (4) anything that needs attention. "
        "Be specific; never invent."
    ),
    "deep": (
        "You are ELI performing a thorough, grounded screen audit. Describe in detail: "
        "every visible application and panel; the user's apparent task step-by-step; "
        "all readable text (including small labels, status bars, tabs, URLs, file names); "
        "code snippets or data if visible; errors, warnings, or incomplete states; "
        "relationships between on-screen elements. Structure your answer with short "
        "sections. If something is unreadable, say so — never guess or invent."
    ),
}


def _cfg(key: str, default: Any = None) -> Any:
    try:
        from eli.core.runtime_settings import load_settings
        return load_settings().get(key, default)
    except Exception:
        return default


def analysis_depth_from_text(text: str) -> str | None:
    """Infer depth override from natural language."""
    raw = str(text or "").lower()
    if re.search(r"\b(in\s+depth|deep(?:ly)?|full(?:y)?|exhaustive|comprehensive|"
                 r"everything|exact(?:ly)?|complete)\b.*\b(screen|display|monitor|desktop)\b",
                 raw):
        return "deep"
    if re.search(r"\b(screen|display|monitor|desktop)\b.*\b(in\s+depth|deep(?:ly)?|"
                 r"full(?:y)?|exhaustive|comprehensive|everything|exact(?:ly)?)\b", raw):
        return "deep"
    if re.search(r"\bexactly\s+what(?:'s|\s+is)\s+on\b", raw):
        return "deep"
    return None


def wants_research_link(text: str) -> bool:
    raw = str(text or "").lower()
    return bool(re.search(
        r"\b(research|paper|thesis|project|study|literature|hypothesis|experiment)\b", raw))


def wants_prior_screen_recall(text: str) -> bool:
    raw = str(text or "").lower()
    return bool(re.search(
        r"\b(remember|recall|previous\s+session|earlier|before|last\s+time|"
        r"seen\s+this|saw\s+this|have\s+you\s+seen)\b", raw))


def _prior_screen_memories(query: str, limit: int = 6) -> list[str]:
    hits: list[str] = []
    try:
        from eli.memory.memory import get_memory
        mem = get_memory()
        for q in (query, "screen glance ambient vision", "screen_awareness"):
            try:
                rows = mem.search_memories(q, limit=limit) or []
            except Exception:
                rows = mem.recall_memory(q, limit=limit) or []
            for row in rows:
                if isinstance(row, dict):
                    body = str(row.get("content") or row.get("text") or row.get("memory") or "")
                    tags = row.get("tags") or []
                else:
                    body = str(row)
                    tags = []
                tag_str = " ".join(str(t) for t in tags).lower()
                if "screen" in body.lower() or "screen" in tag_str or "glance" in body.lower():
                    snippet = body.strip()[:500]
                    if snippet and snippet not in hits:
                        hits.append(snippet)
            if hits:
                break
    except Exception:
        log.debug("prior screen memory lookup failed", exc_info=True)
    return hits[:limit]


def _research_context(query: str, limit: int = 5) -> list[str]:
    hits: list[str] = []
    try:
        from eli.memory.memory import get_memory
        mem = get_memory()
        for q in (query, "research project topic"):
            try:
                rows = mem.search_memories(q, limit=limit) or []
            except Exception:
                rows = mem.recall_memory(q, limit=limit) or []
            for row in rows:
                body = str(
                    (row.get("content") if isinstance(row, dict) else row) or ""
                ).strip()
                if body and body not in hits:
                    hits.append(body[:600])
    except Exception:
        log.debug("research context lookup failed", exc_info=True)
    try:
        from eli.memory.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        for ent in kg.search_entities(query, limit=4) or []:
            name = str(ent.get("name") or ent.get("label") or "")
            desc = str(ent.get("description") or ent.get("summary") or "")
            if name:
                hits.append(f"{name}: {desc}".strip()[:400])
    except Exception:
        log.debug("kg research lookup failed", exc_info=True)
    return hits[:limit]


def build_screen_analysis_prompt(
    user_text: str = "",
    *,
    explicit_prompt: str = "",
    depth: str | None = None,
    use_memory: bool | None = None,
    use_research: bool | None = None,
) -> str:
    """Compose the vision prompt for SCREEN_READ_ANALYZE."""
    if explicit_prompt:
        base = explicit_prompt.strip()
    else:
        d = depth or analysis_depth_from_text(user_text) or str(
            _cfg("screen_analysis_depth", "standard") or "standard"
        )
        base = _DEPTH_PROMPTS.get(d, _DEPTH_PROMPTS["standard"])

    parts = [base]
    ut = str(user_text or "").strip()
    if ut and not explicit_prompt:
        parts.append(f'\nThe user asked: "{ut}"\nAnswer that question from the screenshot.')

    if use_memory is None:
        use_memory = bool(_cfg("screen_analysis_use_memory", True))
    if use_research is None:
        use_research = bool(_cfg("screen_analysis_use_research", True))

    if use_memory and (wants_prior_screen_recall(ut) or bool(_cfg("screen_analysis_always_memory", False))):
        prior = _prior_screen_memories(ut or "screen")
        if prior:
            parts.append(
                "\n--- Prior screen memories (from earlier glances/sessions; cite only if relevant) ---\n"
                + "\n".join(f"- {p}" for p in prior)
            )

    if use_research and wants_research_link(ut):
        research = _research_context(ut)
        if research:
            parts.append(
                "\n--- User research/project context (relate the screen ONLY where grounded) ---\n"
                + "\n".join(f"- {r}" for r in research)
            )

    parts.append(
        "\nRules: describe ONLY what is visible in the screenshot. "
        "If prior memories contradict the current screen, trust the screenshot."
    )
    return "\n".join(parts)


def prefer_fast_for_depth(depth: str) -> bool:
    return depth == "quick"


__all__ = [
    "analysis_depth_from_text",
    "build_screen_analysis_prompt",
    "prefer_fast_for_depth",
    "wants_prior_screen_recall",
    "wants_research_link",
]
