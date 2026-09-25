"""Sizing and trimming the memory block that goes into a prompt."""
from __future__ import annotations

import os
import re
from typing import List, Optional

CHARS_PER_TOKEN = 3.5
HEADROOM = 0.20
MIN_MEMORY_CHARS = 400
_BLOCK_PRIORITY = ("retrieval diagnostics", "verified stored memories", "reranked evidence", "recent turns")
_KEEP_TAIL = ("recent turns",)

_RECALL_RE = re.compile(
    r"\b(remember|recall|remind me|what (?:was|were) (?:i|we)|what did (?:i|we)|did i (?:tell|say|mention)|"
    r"(?:last|past|previous) (?:night|week|month|weekend|time|session|few days)|yesterday|earlier|"
    r"the other day|a while ago|months? ago|weeks? ago|days? ago|history|memories)\b", re.I)


def is_recall_question(text: str) -> bool:
    return bool(_RECALL_RE.search(str(text or "")))


def output_reserve_tokens(max_tokens: int, n_ctx: int) -> int:
    """Reply tokens held back when sizing memory: an eighth of the window, never above max_tokens."""
    env = os.environ.get("ELI_OUTPUT_RESERVE_TOKENS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    ceiling = int(max_tokens) if int(max_tokens or 0) > 0 else max(256, int(n_ctx) // 4)
    return max(1, min(ceiling, max(256, int(n_ctx) // 8)))


_MEASURED: dict = {}
_SAMPLE = ("The meeting moved to Tuesday, so please send the report before noon. def load(path): "
           "return json.loads(open(path).read()) # 42 rows, 3.5 MB. I work nights now; my dog is called Max. ")


def chars_per_token() -> float:
    """Characters per token for the loaded model, measured with its own tokenizer, else the default."""
    try:
        from eli.cognition import gguf_inference as _gi
        llm = getattr(_gi, "_llm", None)
        if llm is None:
            return CHARS_PER_TOKEN
        key = id(llm)
        if key not in _MEASURED:
            text = _SAMPLE * 8
            n = len(llm.tokenize(text.encode("utf-8", errors="ignore"), add_bos=False))
            _MEASURED.clear()
            _MEASURED[key] = min(6.0, max(2.0, len(text) / n)) if n else CHARS_PER_TOKEN
        return _MEASURED[key]
    except Exception:
        return CHARS_PER_TOKEN


def memory_char_budget(n_ctx: int, fixed_chars: int, max_tokens: int, *,
                       wanted_chars: Optional[int] = None, protect_memory: bool = False) -> int:
    """Chars of memory that fit beside `fixed_chars` of persona and prompt.

    With protect_memory (recall questions) memory keeps at least a third of the window.
    """
    n_ctx = max(1, int(n_ctx))
    cpt = chars_per_token()
    total = int(n_ctx * cpt * (1.0 - HEADROOM))
    reserve = int(output_reserve_tokens(max_tokens, n_ctx) * cpt)
    budget = max(MIN_MEMORY_CHARS, total - int(fixed_chars) - reserve)
    if protect_memory:
        floor = total // 3
        if wanted_chars is not None:
            floor = min(floor, int(wanted_chars))
        budget = max(budget, floor)
    return budget


def _split_blocks(ctx: str) -> List[List[str]]:
    blocks: List[List[str]] = []
    cur: List[str] = []
    for line in ctx.split("\n"):
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _rank(header: str) -> int:
    h = header.strip().lower()
    return next((i for i, name in enumerate(_BLOCK_PRIORITY) if h.startswith(name)), len(_BLOCK_PRIORITY))


def trim_memory_context(ctx: str, budget: int) -> str:
    """Fit ctx into budget by dropping whole lines: weakest ranked hits first, oldest turns first."""
    ctx = str(ctx or "")
    budget = max(MIN_MEMORY_CHARS, int(budget))
    if len(ctx) <= budget:
        return ctx
    blocks = _split_blocks(ctx)
    kept = {i: [] for i in range(len(blocks))}
    used = 0
    for i in sorted(range(len(blocks)), key=lambda i: (_rank(blocks[i][0]), i)):
        header, body = blocks[i][0], blocks[i][1:]
        keep_tail = header.strip().lower().startswith(_KEEP_TAIL)
        if not body:
            header, body = "", [header]
        room = budget - used - (len(header) + 1 if header else 0)
        take: List[str] = []
        for ln in (reversed(body) if keep_tail else body):
            if len(ln) + 1 <= room:
                take.append(ln)
                room -= len(ln) + 1
            elif not take and room > 80:
                take.append(ln[:room - 1].rstrip())
                break
            else:
                break
        if not take:
            continue
        if keep_tail:
            take.reverse()
        kept[i] = ([header] if header else []) + take
        used += sum(len(x) + 1 for x in kept[i]) + 1
    return "\n\n".join("\n".join(kept[i]) for i in range(len(blocks)) if kept[i])
