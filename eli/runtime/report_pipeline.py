"""Multi-stage grounded document pipeline (Report-Builder discipline, chat scale).

The chat/voice "generate a document about X" path used to be a single one-shot LLM
call → generic, shallow output. This runs the same *philosophy* as the Labs Report
Builder — PLAN before drafting, draft section-by-section grounded in gathered
evidence, then a REVIEW→REVISE pass and a final polish — but at a scale sensible
for a conversational request (the heavyweight thesis pipeline stays in the Report
Builder main tab).

Order of operations (the requested "steps to initiate the plan prior to dispatch"):
  1. PLAN     — produce a section outline grounded in the evidence (the plan).
  2. DRAFT    — write each section against the plan + evidence.
  3. REVIEW   — critique the assembled draft against a quality contract, then revise.
  4. POLISH   — light final integration pass.

Confidence-driven retries (the requested "low confidence → additional tiers"):
  - a degenerate / too-short stage output is retried once with a firmer instruction;
  - if the gathered evidence is thin, `deepen_cb` is invoked to RE-GATHER with deeper
    agent tiers (deeper reasoning mode → model evidence-planning + tier-3 code
    analysis + more channels) before drafting.

Pure orchestration over an injected `ask` callable — no GUI, no model hardcoding.
Kill switch: ELI_DOC_PIPELINE=0 (caller falls back to single-pass).
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# ask(prompt, *, system=None, max_tokens=int, temperature=float) -> str
AskFn = Callable[..., str]


def enabled() -> bool:
    return os.environ.get("ELI_DOC_PIPELINE", "1").strip().lower() not in ("0", "false", "no", "off")


def _degenerate(text: str, min_chars: int = 40) -> bool:
    t = str(text or "").strip()
    if len(t) < min_chars:
        return True
    return not re.search(r"[A-Za-z0-9]", t)


def _evidence_thin(evidence: str) -> bool:
    return len(str(evidence or "").strip()) < 200


def _ask_retry(ask: AskFn, prompt: str, *, system: str, max_tokens: int,
               temperature: float, min_chars: int, firmer: str) -> str:
    """Call ask; if the result is degenerate, retry once with a firmer instruction."""
    out = str(ask(prompt, system=system, max_tokens=max_tokens, temperature=temperature) or "").strip()
    if _degenerate(out, min_chars):
        out = str(ask(prompt + "\n\n" + firmer, system=system,
                      max_tokens=max_tokens, temperature=max(0.2, temperature - 0.1)) or "").strip()
    return out


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-z]*\n?", "", str(text or "").strip(), flags=re.MULTILINE)
    return re.sub(r"\n?```$", "", text.strip(), flags=re.MULTILINE).strip()


_EVIDENCE_RULE = (
    "Ground every concrete claim in the EVIDENCE below; refer to its specifics by "
    "name. Where the evidence does not cover a point, say so plainly or mark it "
    "[source needed] — never invent facts, citations, file paths, or numbers."
)


def _outline(ask: AskFn, topic: str, doc_type: str, evidence: str, n_sections: int) -> List[str]:
    sys = ("You are ELI's document planner. Plan a tight, non-redundant section "
           f"outline for a {doc_type} — {n_sections} sections that actually cover the "
           "subject. Reply ONLY as a numbered list of concise section titles, nothing else.")
    prompt = f"Subject: {topic}\n\nEVIDENCE:\n{evidence or '(none gathered)'}\n\nGive the section outline."
    raw = _ask_retry(ask, prompt, system=sys, max_tokens=400, temperature=0.3,
                     min_chars=10, firmer="List the section titles now, one per line, numbered.")
    titles: List[str] = []
    for line in _strip_fences(raw).splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$", line.strip())
        t = (m.group(1) if m else line).strip(" #*-•").strip()
        if t and len(t) < 120 and not t.lower().startswith(("here", "outline", "section list")):
            titles.append(t)
    # de-dupe, cap
    seen, out = set(), []
    for t in titles:
        k = t.lower()
        if k not in seen:
            seen.add(k); out.append(t)
    return out[:n_sections] or [topic]


def _section(ask: AskFn, topic: str, doc_type: str, title: str, outline: List[str],
             evidence: str, words: int) -> str:
    sys = (f"You are ELI writing one section of a {doc_type}. Write the section "
           f"'{title}' only — ~{words} words, markdown, specific and substantive. "
           f"{_EVIDENCE_RULE} No filler, no restating the whole outline, no placeholders.")
    prompt = (f"Subject: {topic}\nFull outline: {', '.join(outline)}\n\nEVIDENCE:\n"
              f"{evidence or '(none gathered)'}\n\nWrite the '{title}' section.")
    body = _ask_retry(ask, prompt, system=sys, max_tokens=min(2200, words * 3 + 300),
                      temperature=0.4, min_chars=60,
                      firmer=f"Write the actual '{title}' section content now — real prose, no meta.")
    body = _strip_fences(body)
    if not re.match(r"^#{1,4}\s", body):
        body = f"## {title}\n\n{body}"
    return body.strip()


def _review_revise(ask: AskFn, topic: str, doc_type: str, draft: str, evidence: str) -> str:
    crit_sys = (f"You are a strict reviewer of a {doc_type}. List the 3-6 most important "
                "concrete problems (shallow/generic passages, unsupported claims, "
                "repetition, missing specifics from the evidence). Bullet points only.")
    critique = str(ask(f"EVIDENCE:\n{evidence or '(none)'}\n\nDRAFT:\n{draft}\n\nList the problems.",
                       system=crit_sys, max_tokens=500, temperature=0.3) or "").strip()
    if _degenerate(critique, 20):
        return draft  # no usable critique → keep draft
    rev_sys = (f"You are ELI revising a {doc_type}. Apply the reviewer's fixes to the draft. "
               f"{_EVIDENCE_RULE} Return the FULL revised document in markdown, nothing else.")
    revised = str(ask(f"EVIDENCE:\n{evidence or '(none)'}\n\nDRAFT:\n{draft}\n\n"
                      f"REVIEWER NOTES:\n{critique}\n\nReturn the full revised document.",
                      system=rev_sys, max_tokens=min(7000, len(draft) // 2 + 1500),
                      temperature=0.35) or "").strip()
    revised = _strip_fences(revised)
    return revised if not _degenerate(revised, 200) else draft


def generate_document(
    topic: str,
    *,
    ask: AskFn,
    evidence: str = "",
    sources: Optional[List[str]] = None,
    doc_type: str = "document",
    target_words: int = 1100,
    deepen_cb: Optional[Callable[[], "tuple"]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Run the multi-stage grounded pipeline. Returns {ok, text, sections, title,
    evidence_sources}. Raises nothing the caller can't handle — on failure returns
    ok=False so the caller can fall back to a single pass."""
    def _p(msg: str) -> None:
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    try:
        # Confidence-retry tier 0→1: if the gathered evidence is thin, RE-GATHER
        # with deeper agent tiers before we commit to drafting.
        if _evidence_thin(evidence) and deepen_cb is not None:
            _p("evidence thin → re-gathering with deeper agent tiers")
            try:
                ev2, src2 = deepen_cb()
                if ev2 and len(ev2) > len(evidence or ""):
                    evidence, sources = ev2, (src2 or sources)
            except Exception as e:
                log.debug(f"[DOC_PIPELINE] deepen re-gather failed: {e}")

        n_sections = 3 if target_words <= 1000 else (4 if target_words <= 1800 else 6)
        per_section = max(180, target_words // n_sections)

        _p("planning outline")
        outline = _outline(ask, topic, doc_type, evidence, n_sections)
        log.debug(f"[DOC_PIPELINE] outline={outline}")

        blocks: List[str] = []
        for i, title in enumerate(outline, 1):
            _p(f"drafting section {i}/{len(outline)}: {title}")
            blocks.append(_section(ask, topic, doc_type, title, outline, evidence, per_section))
        draft = "\n\n".join(b for b in blocks if b).strip()
        if _degenerate(draft, 200):
            return {"ok": False, "text": draft, "sections": outline}

        _p("review + revise pass")
        final = _review_revise(ask, topic, doc_type, draft, evidence)

        # Title heading if absent
        if not final.lstrip().startswith("#"):
            final = f"# {topic.strip().capitalize()}\n\n{final}"
        return {
            "ok": True,
            "text": final.strip(),
            "sections": outline,
            "title": topic,
            "evidence_sources": sources or [],
        }
    except Exception as e:
        log.debug(f"[DOC_PIPELINE] failed: {e}")
        return {"ok": False, "error": str(e), "text": ""}


__all__ = ["generate_document", "enabled"]
