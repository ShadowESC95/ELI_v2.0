"""Structured decomposition — planner / implementer separation.

`plan_task` decomposes a coding task into an explicit approach + ordered steps
(the *planner*). `implement` writes code against that plan, optionally refining
prior code given repair feedback (the *implementer*). Both take an injected
`generate` callable so they are testable without a model and model-agnostic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

GenerateFn = Callable[..., str]


@dataclass
class Plan:
    approach: str
    steps: List[str] = field(default_factory=list)
    raw: str = ""

    def as_prompt_block(self) -> str:
        lines = [f"APPROACH: {self.approach}"] if self.approach else []
        for i, s in enumerate(self.steps, 1):
            lines.append(f"  {i}. {s}")
        return "PLAN:\n" + "\n".join(lines) if lines else ""


def _strip_code_fences(text: str) -> str:
    t = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", (text or "").strip(), flags=re.MULTILINE)
    t = re.sub(r"\n?```\s*$", "", t.strip(), flags=re.MULTILINE)
    return t.strip()


def plan_task(task: str, generate: Optional[GenerateFn] = None, *,
              context: str = "", language: str = "python", max_tokens: int = 1536) -> Plan:
    # NOTE: budget is deliberately > the no-think suppression threshold (1024) so a
    # reasoning model THINKS through the plan — the planning step is where reasoning
    # helps most, yet at 700 tokens the no-think prefill was suppressing it. (Advancement A.)
    """Decompose `task` into an approach + ordered steps. Deterministic single-step
    fallback when no model is available or parsing fails."""
    if generate is None:
        return Plan(approach=task.strip()[:200], steps=[task.strip()])
    prompt = (
        f"You are a senior {language} architect. Decompose this coding task into a SHORT, "
        "concrete implementation plan — not code.\n\n"
        f"TASK:\n{task}\n"
        + (f"\nCONTEXT:\n{context}\n" if context else "")
        + "\nRespond with ONLY JSON: {\"approach\": \"one sentence\", "
        "\"steps\": [\"concrete step\", ...]}. 3-7 steps. No prose outside the JSON."
    )
    try:
        raw = generate(prompt, system="You decompose problems precisely.",
                       max_tokens=max_tokens, temperature=0.2) or ""
        m = re.search(r"\{[\s\S]+\}", raw)
        if m:
            data = json.loads(m.group(0))
            steps = [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()]
            return Plan(approach=str(data.get("approach") or task)[:300],
                        steps=steps or [task.strip()], raw=raw)
    except Exception as exc:
        log.debug(f"[PLANNER] plan parse failed, using single-step plan: {exc}")
    return Plan(approach=task.strip()[:200], steps=[task.strip()], raw="")


_IMPLEMENT_RULES = (
    "HARD RULES — any violation is failure:\n"
    "- Output ONLY raw {lang} code: no markdown fences, no prose, no explanation.\n"
    "- Complete and runnable end-to-end with NO required CLI args (sensible defaults).\n"
    "- Decompose into cohesive functions; a main()/entry orchestrates them.\n"
    "- Use real libraries for real work; never substitute prose/stubs for computation.\n"
    "- Imports at top; guard I/O with try/except; include an `if __name__ == \"__main__\":` guard.\n"
)


def implement(task: str, plan: Optional[Plan], generate: GenerateFn, *,
              language: str = "python", feedback: str = "", prior_code: str = "",
              context: str = "", temperature: float = 0.2, max_tokens: int = 4000) -> str:
    """Write (or refine) a solution. When `feedback`+`prior_code` are supplied this
    is a patch-style refinement: fix the specific problem, keep what works. `context` is
    relevant EXISTING repo code (imports, surrounding scope, symbol defs) so the model
    matches real APIs/patterns instead of guessing — (Advancement C)."""
    parts = [
        f"You are a senior {language} engineer writing frontier-quality, runnable code.",
        f"\nTASK:\n{task}",
    ]
    if context:
        parts.append(
            "\nEXISTING CODE FROM THIS PROJECT (match these real names/imports/signatures; "
            "do NOT invent names that aren't shown here):\n" + context[:6000])
    if plan and (plan.approach or plan.steps):
        parts.append("\n" + plan.as_prompt_block())
    if prior_code and feedback:
        parts.append(
            "\nYou previously produced this solution:\n```\n" + prior_code[:6000] + "\n```\n"
            "It was REJECTED for this reason — fix exactly this, change as little else as possible:\n"
            + feedback[:1500]
        )
    elif feedback:
        parts.append("\nPREVIOUS ATTEMPT FEEDBACK (fix specifically):\n" + feedback[:1500])
    parts.append("\n" + _IMPLEMENT_RULES.format(lang=language))
    prompt = "\n".join(parts)
    raw = generate(
        prompt,
        system=(f"You are an expert {language} engineer. Output only raw {language} "
                "code, no markdown, no commentary."),
        max_tokens=max_tokens, temperature=temperature,
    ) or ""
    return _strip_code_fences(raw)
