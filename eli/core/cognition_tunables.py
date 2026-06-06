"""Central registry of user-tunable cognition / knowledge-gathering parameters.

Single source of truth: the GUI (Advanced Settings → Cognition) renders a control
for every entry here, and the cognition code reads the live value via
`get_tunable()` / `snapshot()`. All values persist to settings.json (via
`eli.core.config`) and are clamped to safe ranges. Changing a value takes effect
on the NEXT request — no restart needed — because the cognition paths read it at
call time.

Why this exists: the knowledge-gathering limits (how many memory facts, KG chars,
rerank depth, the synthesis prompt cap) were hardcoded. Exposing them gives the
user full control + visibility, and lets the limits scale up together with a
larger-context local model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Tunable:
    key: str            # config / settings.json key
    label: str          # GUI label
    help: str           # GUI tooltip / description
    default: int
    minimum: int
    maximum: int
    step: int = 1
    group: str = "Knowledge gathering"


# NOTE: defaults here MUST match the shipped hardcoded values so behaviour is
# identical until the user changes something.
TUNABLES: List[Tunable] = [
    # ── Model context budget ────────────────────────────────────────────────
    Tunable(
        "cog.synth_max_prompt_chars", "Synthesis prompt cap (characters)",
        "Hard ceiling on the characters fed to the model for ONE answer. Higher = "
        "more context, but the local model degenerates into '-' fragments above "
        "~30k. 0 disables the cap (only sensible with a large-context model). "
        "The env var ELI_SYNTH_MAX_PROMPT_CHARS overrides this when set.",
        28000, 0, 80000, 1000, "Model context budget"),

    # ── Memory agent gathering ──────────────────────────────────────────────
    Tunable("cog.mem_semantic_recall", "Memory · semantic facts recalled",
            "How many durable facts the memory agent pulls from the vector/FTS "
            "store per query (the search pool).", 24, 1, 100, 1, "Memory gathering"),
    Tunable("cog.mem_semantic_shown", "Memory · semantic facts shown",
            "How many of the recalled facts are actually placed into the prompt.",
            24, 1, 100, 1, "Memory gathering"),
    Tunable("cog.mem_fact_chars", "Memory · characters per fact",
            "Truncation length for each semantic fact. Lower = fit more facts; "
            "higher = more detail each.", 200, 60, 800, 10, "Memory gathering"),
    Tunable("cog.mem_conv_recall", "Memory · conversation hits recalled",
            "Search-pool size for matching past conversation turns.",
            14, 1, 80, 1, "Memory gathering"),
    Tunable("cog.mem_conv_shown", "Memory · conversation hits shown",
            "How many matched conversation turns go into the prompt.",
            12, 1, 80, 1, "Memory gathering"),
    Tunable("cog.mem_conv_chars", "Memory · characters per conversation hit",
            "Truncation length per matched conversation turn.",
            150, 60, 600, 10, "Memory gathering"),
    Tunable("cog.mem_recent_turns", "Memory · recent turns",
            "How many of the most recent conversation turns are included for "
            "continuity.", 24, 0, 80, 1, "Memory gathering"),
    Tunable("cog.mem_recent_chars", "Memory · characters per recent turn",
            "Truncation length per recent turn.", 140, 60, 600, 10, "Memory gathering"),
    Tunable("cog.mem_summaries_recall", "Memory · session summaries recalled",
            "Search pool of prior-session summaries.", 6, 0, 40, 1, "Memory gathering"),
    Tunable("cog.mem_summaries_shown", "Memory · session summaries shown",
            "How many session summaries go into the prompt.", 5, 0, 40, 1, "Memory gathering"),
    Tunable("cog.mem_summary_chars", "Memory · characters per summary",
            "Truncation length per session summary.", 260, 80, 800, 10, "Memory gathering"),
    Tunable("cog.mem_hop2_recall", "Memory · multi-hop deepen pool",
            "When the first recall is thin, a second hop re-queries using the top "
            "hit's terms; this is that hop's pool size.", 12, 0, 60, 1, "Memory gathering"),
    Tunable("cog.mem_merge_cap", "Memory · max merged hits",
            "Upper bound on total semantic hits after the multi-hop merge.",
            28, 1, 120, 1, "Memory gathering"),

    # ── Knowledge graph ─────────────────────────────────────────────────────
    Tunable("cog.kg_max_chars", "Knowledge graph · context (characters)",
            "Characters of knowledge-graph facts placed into the prompt.",
            2200, 0, 8000, 100, "Knowledge graph"),

    # ── Retrieval pipeline (full 12-stage, standard mode) ───────────────────
    Tunable("cog.orch_keyword_limit", "Pipeline · keyword search limit",
            "FTS5 keyword hits retrieved in the full pipeline (standard mode).",
            24, 1, 80, 1, "Retrieval pipeline"),
    Tunable("cog.orch_semantic_limit", "Pipeline · semantic search limit",
            "FAISS vector hits retrieved (standard mode).", 24, 1, 80, 1, "Retrieval pipeline"),
    Tunable("cog.orch_rag_limit", "Pipeline · RAG recall limit",
            "Memory recall hits retrieved (standard mode).", 16, 1, 80, 1, "Retrieval pipeline"),
    Tunable("cog.rerank_top_k", "Pipeline · reranked hits kept",
            "After cross-encoder reranking, how many top hits are kept for the "
            "prompt.", 20, 1, 80, 1, "Retrieval pipeline"),

    # ── Personal-memory report ──────────────────────────────────────────────
    Tunable("cog.personal_facts_max", "“What do you know about me” · max facts",
            "Maximum facts listed in the personal-memory report (verbatim, not "
            "synthesised).", 40, 1, 200, 1, "Personal memory report"),
]

_BY_KEY: Dict[str, Tunable] = {t.key: t for t in TUNABLES}


def _clamp(t: Tunable, value) -> int:
    try:
        v = int(value)
    except Exception:
        v = t.default
    return max(t.minimum, min(t.maximum, v))


def get_tunable(key: str) -> int:
    """Live value for one tunable (one settings.json read). Clamped to range."""
    t = _BY_KEY.get(key)
    if t is None:
        raise KeyError(f"unknown cognition tunable: {key!r}")
    try:
        from eli.core.config import get as _get
        return _clamp(t, _get(key, t.default))
    except Exception:
        return t.default


def snapshot() -> Dict[str, int]:
    """All tunables in ONE settings read — use on the hot path (per request)."""
    out: Dict[str, int] = {}
    try:
        from eli.core.runtime_settings import load_settings as _ls
        s = _ls() or {}
    except Exception:
        s = {}
    for t in TUNABLES:
        out[t.key] = _clamp(t, s.get(t.key, t.default))
    return out


def set_tunable(key: str, value) -> bool:
    """Persist one tunable (clamped) to settings.json."""
    t = _BY_KEY.get(key)
    if t is None:
        return False
    try:
        from eli.core.config import set as _set
        return bool(_set(key, _clamp(t, value)))
    except Exception:
        return False


def reset_defaults() -> None:
    """Restore all tunables to their shipped defaults."""
    for t in TUNABLES:
        set_tunable(t.key, t.default)


def groups() -> Dict[str, List[Tunable]]:
    """Tunables grouped by `group`, preserving declaration order."""
    out: Dict[str, List[Tunable]] = {}
    for t in TUNABLES:
        out.setdefault(t.group, []).append(t)
    return out


__all__ = [
    "Tunable", "TUNABLES", "get_tunable", "snapshot", "set_tunable",
    "reset_defaults", "groups",
]
