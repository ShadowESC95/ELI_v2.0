from __future__ import annotations

from typing import List

from eli.runtime.response_packets import FinalAnswerRequest


def build_fastpath_context(req: FinalAnswerRequest) -> str:
    if not req.quick:
        return ""
    lines: List[str] = [
        "FASTPATH_RESPONSE_CONTEXT",
        f"- action: {req.action}",
        f"- provider: {req.provider}",
        f"- style_hint: {req.style_hint}",
        f"- evidence_count: {req.evidence_count}",
        "- Use a direct answer. For opinion/banter, answer in ELI persona while separating facts from judgement.",
        "- Do not narrate internal pipeline stages.",
        "- Do not invent missing facts.",
        "",
        "USER_FACING_PROMPT",
        req.user_prompt,
    ]
    return "\n".join(lines)
