"""What memory retrieval actually did this turn, from telemetry, so ELI never has to guess why."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from eli.core.confidence import confidence_label

_FALSE_DIAGNOSIS = re.compile(
    r"(?i)\b(?:i (?:failed|did(?:n'?t| not)|never|neglected) to (?:query|search|check|look)\b"
    r"|i (?:did(?:n'?t| not) )?(?:query|search|check)(?:ed)? (?:the full|all|every)\b[^.?!]*"
    r"|(?:my|the) (?:previous|earlier|last|first) (?:claim|answer|statement|reply|response)\b[^.?!]*\b(?:was|is) a lie\b"
    r"|i (?:lied|was lying))")


def retrieval_record(keyword: int, semantic: int, kg: int, merged: int, confidence: Optional[float]) -> Dict[str, Any]:
    return {"retrieval_ran": True, "keyword": keyword, "semantic": semantic, "kg": kg,
            "merged": merged, "confidence": confidence}


def block(diag: Optional[Dict[str, Any]]) -> str:
    if not (diag or {}).get("retrieval_ran"):
        return ""
    c = diag.get("confidence")
    conf = f", retrieval confidence {c:.2f} ({confidence_label(c)})" if c is not None else ""
    return (f"Retrieval diagnostics (authoritative): searched keyword={diag['keyword']} "
            f"semantic={diag['semantic']} kg={diag['kg']}, merged {diag['merged']} items{conf}.")


def explanation(diag: Dict[str, Any]) -> str:
    """The true account of a memory search, in plain words."""
    said = f"I searched my stored memories ({diag['merged']} items found"
    c = diag.get("confidence")
    said += f", confidence {confidence_label(c)})" if c is not None else ")"
    before, after = diag.get("context_before"), diag.get("context_after")
    if before and after and after < before:
        said += f"; {before - after} of {before} characters of that context were cut to fit the window"
    return said + "."


def drop_false_diagnosis(text: str, diag: Optional[Dict[str, Any]]) -> str:
    """When retrieval ran, remove sentences claiming it didn't or that ELI lied; state what happened."""
    if not (diag or {}).get("retrieval_ran") or not _FALSE_DIAGNOSIS.search(text or ""):
        return text
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [p for p in parts if not _FALSE_DIAGNOSIS.search(p)]
    return " ".join([explanation(diag)] + kept).strip()
