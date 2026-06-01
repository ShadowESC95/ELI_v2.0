"""Cost estimation + the "should this run in the background?" decision.

Heavy coding work (deep search, multi-component DAG builds, simulations,
optimisation) can take a while. Rather than block, the agent estimates cost and
backgrounds the task when it's heavy — or when the user explicitly asks for
foreground/background. This is the deterministic estimator + decision; the
agent's planner output can also be folded in by the caller for an LLM-informed
estimate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

# Signals that a task is computationally/structurally heavy.
_HEAVY_RE = re.compile(
    r"\b(?:simulat\w*|monte\s*carlo|optimi[sz]\w*|benchmark\w*|train\w*|"
    r"dijkstra|a\*|shortest\s+path|backtrack\w*|np-?hard|sat\b|solver|"
    r"parallel|multiprocess\w*|concurren\w*|throughput|profil\w*|"
    r"large\s+(?:dataset|input|scale)|exhaustive|brute[\s-]?force|"
    r"deep\s+(?:search|reasoning)|thorough\w*|fine[\s-]?tun\w*|"
    r"machine\s+learning|neural|gradient|regression|clustering)\b", re.I)

# Signals of multi-component work (favours the subtask DAG → more nodes → slower).
_MULTI_RE = re.compile(
    r"\b(?:pipeline|end[\s-]?to[\s-]?end|multiple\s+|several\s+|"
    r"then\s+\w+\s+(?:that|which)|and\s+then\b)", re.I)

# Open-ended / hard / research-grade tasks: long, many candidates, often
# unsolvable — should NOT block the UI. (This is what "solve the P vs NP
# problem" tripped over: no heavy-compute keyword matched, so it ran foreground.)
_OPEN_ENDED_RE = re.compile(
    r"\bp\s*(?:vs\.?|versus)\s*np\b|\bopen\s+problem\b|\bnp[\s-]?(?:complete|hard)\b|"
    r"\b(?:solve|prove|design|architect|build|implement)\b[^.?!]*"
    r"\b(?:problem|theorem|conjecture|system|framework|engine|architecture|"
    r"compiler|interpreter|from\s+scratch|end[\s-]?to[\s-]?end)\b", re.I)

_FOREGROUND_RE = re.compile(
    r"\b(?:right\s+now|immediately|don'?t\s+background|in\s+the\s+foreground|"
    r"wait\s+for\s+it|quick(?:ly)?|just\s+do\s+it\s+now)\b", re.I)

_BACKGROUND_RE = re.compile(
    r"\b(?:in\s+the\s+background|background\s+(?:this|it|task)|run\s+it\s+in\s+the\s+background|"
    r"don'?t\s+wait|while\s+i\s+|come\s+back\s+to\s+me|notify\s+me\s+when|take\s+your\s+time)\b", re.I)


@dataclass
class CostEstimate:
    score: float                       # 0..1 heaviness
    level: str                         # light | moderate | heavy
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {"score": round(self.score, 3), "level": self.level, "reasons": self.reasons}


def estimate_cost(task: str, *, language: str = "python", plan_steps: int = 0) -> CostEstimate:
    t = task or ""
    s = 0.0
    reasons: List[str] = []
    _heavy_hits = _HEAVY_RE.findall(t)
    if _heavy_hits:
        s += min(0.6, 0.3 * len(_heavy_hits))
        reasons.append(f"{len(_heavy_hits)} heavy-compute signal(s)")
    if _MULTI_RE.search(t):
        s += 0.3; reasons.append("multi-component")
    if _OPEN_ENDED_RE.search(t):
        s += 0.45; reasons.append("open-ended/hard")
    if len(t) > 240:
        s += 0.15; reasons.append("long/detailed spec")
    if plan_steps >= 4:
        s += 0.2; reasons.append(f"{plan_steps} planned steps")
    # crude: many "and"s implies several requirements
    if len(re.findall(r"\band\b", t, re.I)) >= 3:
        s += 0.1; reasons.append("many conjunctions")
    s = min(1.0, s)
    level = "heavy" if s >= 0.6 else ("moderate" if s >= 0.3 else "light")
    return CostEstimate(score=s, level=level, reasons=reasons)


def explicit_background(task: str) -> bool:
    return bool(_BACKGROUND_RE.search(task or ""))


def explicit_foreground(task: str) -> bool:
    return bool(_FOREGROUND_RE.search(task or ""))


def should_background(task: str, *, language: str = "python", plan_steps: int = 0) -> Dict:
    """Decide whether to run in the background. Explicit phrasing wins; otherwise
    background heavy tasks. Returns {background: bool, reason: str, estimate: {...}}."""
    if explicit_foreground(task):
        return {"background": False, "reason": "user asked to run now", "estimate": estimate_cost(task, language=language, plan_steps=plan_steps).to_dict()}
    if explicit_background(task):
        return {"background": True, "reason": "user asked to background it", "estimate": estimate_cost(task, language=language, plan_steps=plan_steps).to_dict()}
    est = estimate_cost(task, language=language, plan_steps=plan_steps)
    # Open-ended / hard / research-grade work is inherently slow (many candidates,
    # often unsolvable) — always background so it never blocks the UI.
    if _OPEN_ENDED_RE.search(task or ""):
        return {"background": True, "reason": "open-ended/hard task", "estimate": est.to_dict()}
    if est.level == "heavy":
        return {"background": True, "reason": "estimated heavy: " + ", ".join(est.reasons), "estimate": est.to_dict()}
    return {"background": False, "reason": f"estimated {est.level}", "estimate": est.to_dict()}
