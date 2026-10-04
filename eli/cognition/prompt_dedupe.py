"""One copy of each line of evidence or dialogue per prompt.

The memory block, the persona handoff brief and the history put in front of the user's
message are built separately, and each renders the same turns and memories in its own format.
A quick-mode prompt carried the recent dialogue four times and the reranked evidence four
times: ~37k characters, ~10k tokens, 110-150 s per reply on a CPU-offloaded MoE model, and an
overflow cut that dropped the evidence the question needed.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Set, Tuple

# Leading list marks, numbering, date/source tags and speaker labels differ between the
# builders ("- [today 19:40] user: x", "[2026-10-03 Sat, today] User: x", "03. [fts5 | ...] x").
_PREFIX = re.compile(
    r"^\s*(?:[-•*]\s*)?(?:\d{1,3}\.\s*)?(?:\[[^\]]{0,120}\]\s*)*"
    r"(?:(?:user|you|eli|assistant)\s*(?:said)?\s*:\s*)?", re.I)
_MIN_CHARS = 24
_KEY_CHARS = 48
# A document passage ("[policy.pdf | p. 3, part 26 of 35] ..."). Passages overlap and pages share
# running headers, so two can open with the same words and still be different text: the passage
# that answered the question was dropped as a copy of the one before it.
_PASSAGE = re.compile(r"^\s*\[[^\]]*\bpart \d+ of \d+\]")


def line_key(line: str) -> str:
    """What a line says, without its formatting; '' for headers and short lines."""
    if _is_header(line) or _PASSAGE.match(str(line or "")):
        return ""
    body = _PREFIX.sub("", str(line or ""), count=1)
    body = re.sub(r"\s+", " ", body).strip().lower()
    return body[:_KEY_CHARS].rstrip() if len(body) >= _MIN_CHARS else ""


def _is_header(line: str) -> bool:
    """A section or sub-section title: "GROUNDED FACTS:", "- Reranked evidence:"."""
    stripped = str(line or "").strip().lstrip("-•* ").strip()
    return bool(stripped) and stripped.endswith(":") and len(stripped) < 140 and not stripped.startswith("[")


def keys_of(*texts: str) -> Set[str]:
    out: Set[str] = set()
    for text in texts:
        for line in str(text or "").splitlines():
            k = line_key(line)
            if k:
                out.add(k)
    return out


def dedupe(text: str, seen: Optional[Set[str]] = None) -> Tuple[str, Set[str]]:
    """Drop lines whose content is already in `seen` (or earlier in `text`); a title whose
    lines all went goes with them. Returns the text and the updated set."""
    seen = set() if seen is None else seen
    out = []
    # Titles waiting for a kept line: [line, lost_a_line]. A blank line ends the section, and a
    # title that lost lines and kept none is dropped with it.
    pending: list = []

    def flush(keep_lost: bool) -> None:
        out.extend(h for h, lost in pending if keep_lost or not lost)
        pending.clear()

    for line in str(text or "").split("\n"):
        k = line_key(line)
        if not k:
            if _is_header(line):
                pending.append([line, False])
            else:
                # a blank line or a short untitled line: the section before it is over
                flush(keep_lost=False)
                out.append(line)
            continue
        if k in seen:
            for h in pending:
                h[1] = True
            continue
        seen.add(k)
        flush(keep_lost=True)
        out.append(line)
    flush(keep_lost=False)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")
    return result, seen


def dedupe_prompt_parts(memory_context: str, situation_brief: str,
                        others: Iterable[str] = ()) -> Tuple[str, str]:
    """The memory block and the brief, each without what the user message (history included)
    already carries, and the brief without what the memory block carries."""
    seen = keys_of(*others)
    memory_context, seen = dedupe(memory_context, seen)
    situation_brief, _ = dedupe(situation_brief, seen)
    return memory_context, situation_brief
