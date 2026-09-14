"""Gate when past-session plans/projects may enter the persona handoff.

Soft "only if relevant" instructions are ignored by small local models: they
volunteer Saturday travel plans into a GPU-layer rant. Hard-gate injection
instead — and treat this-turn corrections as authoritative over stored rows.
"""
from __future__ import annotations

import re
from typing import Optional

# User is explicitly asking about stored personal continuity / plans / memory.
_ASKS_STORED_PERSONAL_RE = re.compile(
    r"\b("
    r"my (?:plans?|schedule|projects?|agenda|trip|travel)|"
    r"(?:what(?:'s| is)|whats) (?:my|on my) (?:plan|plans|schedule|agenda)|"
    r"what (?:am i|are we) (?:doing|planning)|"
    r"(?:do you )?(?:remember|recall) (?:my |about )?(?:plans?|schedule|projects?|trip)|"
    r"what do you (?:know|remember) about (?:me|my)|"
    r"(?:active )?projects?|"
    r"personal memory|what(?:'s| is) (?:on )?(?:my )?plate|"
    r"where (?:am i|are we) (?:going|headed)|"
    r"who (?:am i|are we) (?:collecting|picking|meeting)"
    r")\b",
    re.I,
)

# Near-term schedule / travel language — ages out faster than general projects.
_TRAVEL_OR_SCHEDULE_RE = re.compile(
    r"\b("
    r"collect(?:ing)?|pick(?:ing)?\s*up|pickup|drive|driving|travel|trip|"
    r"tomorrow|tonight|this (?:morning|afternoon|evening|weekend)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"appointment|meetup|meet(?:ing)? (?:up|with)|"
    r"bring(?:ing)? (?:him|her|them) back|headed (?:to|for)|going to"
    r")\b",
    re.I,
)

# Explicit near-term plan stated THIS turn (authoritative over stored memory).
_CURRENT_PLAN_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:i(?:'m| am)|we(?:'re| are)|i(?:'ll| will)|we(?:'ll| will))\s+"
    r"(?:(?:just|still|only|actually|now)\s+)*"
    r"(?:collecting|picking\s+up|driving|heading|going|bringing|meeting|"
    r"planning\s+to|supposed\s+to)|"
    r"(?:plans?\s+(?:are|is|for)|my plan(?:\s+is)?)\s+"
    r")(.+?)(?:[.!?\n]|$)"
)


def asks_about_stored_personal_context(user_input: str) -> bool:
    """True when the user is asking about plans, projects, or remembered life context."""
    text = str(user_input or "").strip()
    if not text:
        return False
    return bool(_ASKS_STORED_PERSONAL_RE.search(text))


def looks_like_travel_or_schedule(text: str) -> bool:
    return bool(_TRAVEL_OR_SCHEDULE_RE.search(str(text or "")))


def extract_current_user_plan(user_input: str) -> str:
    """Return a near-term plan stated this turn, or ''."""
    m = _CURRENT_PLAN_RE.search(str(user_input or ""))
    if not m:
        return ""
    plan = (m.group(1) or "").strip().rstrip(".,!? ")
    # Reject tiny / non-plan fragments.
    if len(plan) < 8 or len(plan.split()) < 2:
        return ""
    return plan[:240]


def continuity_guard_block(user_input: str = "") -> Optional[str]:
    """Always-on rule: do not volunteer past-session plans on unrelated turns."""
    if asks_about_stored_personal_context(user_input):
        return None
    return (
        "[CONTINUITY GUARD] Do NOT mention the user's schedule, travel plans, "
        "appointments, weekend plans, who they are collecting/picking up, or "
        "past-session projects unless they asked about those this turn. If they "
        "correct a plan this turn, that correction wins over older memory — do "
        "not keep restating the superseded version. "
        "Do NOT volunteer GPU layer counts, VRAM %, load parameters, or "
        "prior-session runtime numbers unless they asked about GPU/status/"
        "hardware this turn. Never invent or reuse historical layer counts "
        "(e.g. 26/28) — if asked, cite LIVE SELF-STATUS / GPU_STATUS only."
    )


def strip_focus_lines_from_brief(brief: str) -> str:
    """Drop 'Currently focused on' / Goals from a USER MODEL brief for unrelated turns."""
    lines = []
    for line in str(brief or "").splitlines():
        low = line.strip().lower()
        if low.startswith("currently focused on:") or low.startswith("goals:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def strip_recalled_projects_from_profile_text(profile: str) -> str:
    """Drop 'Recalled past topics/research' sections from get_user_profile_text()."""
    out: list[str] = []
    skipping = False
    for line in str(profile or "").splitlines():
        low = line.strip().lower()
        if low.startswith("recalled past topics") or low.startswith("recalled research"):
            skipping = True
            continue
        if skipping:
            if line.startswith("  - ") or not line.strip():
                continue
            skipping = False
        out.append(line)
    return "\n".join(out).strip()
