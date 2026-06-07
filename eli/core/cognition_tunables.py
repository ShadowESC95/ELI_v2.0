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

    # ── Per-reasoning-mode agent time budgets (% of base agent timeouts) ──────
    Tunable("cog.mode_budget_quick", "Mode budget · Quick (%)",
            "Agent time-budget for Quick mode as a % of base. Lower = faster/cheaper.",
            100, 25, 300, 5, "Reasoning-mode budgets"),
    Tunable("cog.mode_budget_normal", "Mode budget · Normal (%)",
            "Agent time-budget for Normal mode (% of base).",
            100, 25, 400, 5, "Reasoning-mode budgets"),
    Tunable("cog.mode_budget_advanced", "Mode budget · Advanced (%)",
            "Agent time-budget for Advanced mode (% of base) — more time to gather.",
            150, 25, 400, 5, "Reasoning-mode budgets"),
    Tunable("cog.mode_budget_research", "Mode budget · Research (%)",
            "Agent time-budget for Research mode (% of base) — deep gathering.",
            200, 25, 600, 5, "Reasoning-mode budgets"),
    Tunable("cog.mode_budget_expert", "Mode budget · Expert (%)",
            "Agent time-budget for Expert mode (% of base) — maximum rigor.",
            250, 25, 600, 5, "Reasoning-mode budgets"),

    # ── Background deepening (Stage 3b) ──────────────────────────────────────
    Tunable("cog.background_deepen", "Background deepening (0=off, 1=on)",
            "When a Quick answer is poorly grounded on a checkable factual turn, "
            "keep gathering on a background thread and surface a better answer in "
            "the Proactive panel. 0 disables. (env ELI_BACKGROUND_DEEPEN=0 also off.)",
            1, 0, 1, 1, "Reasoning-mode budgets"),

    # ── Auto-scaling for bigger models (model-tier aware) ────────────────────
    Tunable("cog.synth_cap_auto", "Synthesis cap: auto-scale to model (0/1)",
            "When on, the synthesis prompt cap is derived from the loaded model's "
            "context window × its capability tier (never below the fixed cap), so "
            "a larger/longer-context model is fed more automatically. 0 = use the "
            "fixed cap above.", 1, 0, 1, 1, "Auto-scaling (model tier)"),
    Tunable("cog.gather_auto_scale", "Gather limits: auto-scale to model (0/1)",
            "When on, the count-based gather limits scale with the loaded model's "
            "capability tier (small=1.0× → unchanged; bigger models gather more, "
            "clamped to each limit's max). 0 = use the fixed limits.",
            1, 0, 1, 1, "Auto-scaling (model tier)"),
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


# Count-based gather keys that scale with the model-capability tier when
# auto-scaling is on (a bigger model gathers proportionally more evidence).
_GATHER_COUNT_KEYS = (
    "cog.mem_semantic_recall", "cog.mem_semantic_shown",
    "cog.mem_conv_recall", "cog.mem_conv_shown",
    "cog.mem_recent_turns", "cog.mem_summaries_recall",
    "cog.mem_summaries_shown", "cog.mem_hop2_recall", "cog.mem_merge_cap",
    "cog.kg_max_chars", "cog.orch_keyword_limit", "cog.orch_semantic_limit",
    "cog.orch_rag_limit", "cog.rerank_top_k", "cog.personal_facts_max",
)


def snapshot() -> Dict[str, int]:
    """All tunables in ONE settings read — use on the hot path (per request).

    When `cog.gather_auto_scale` is on (default) and the loaded model is a larger
    tier, the count-based gather limits are scaled by the tier factor (clamped to
    each tunable's max), so a bigger brain automatically gathers more. For the
    current small model the factor is 1.0 → values are unchanged.
    """
    out: Dict[str, int] = {}
    try:
        from eli.core.runtime_settings import load_settings as _ls
        s = _ls() or {}
    except Exception:
        s = {}
    for t in TUNABLES:
        out[t.key] = _clamp(t, s.get(t.key, t.default))

    if out.get("cog.gather_auto_scale", 1):
        try:
            from eli.core.model_tier import tier_scale
            _mult = tier_scale()
        except Exception:
            _mult = 1.0
        if _mult and _mult != 1.0:
            for _k in _GATHER_COUNT_KEYS:
                t = _BY_KEY.get(_k)
                if t is None:
                    continue
                out[_k] = max(t.minimum, min(t.maximum, int(round(out[_k] * _mult))))
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
