"""Reading a folder of PDFs: every file kept whole in the document index, a summary that covers all of
them, and the result as a PDF with its formulas typeset.

It used to parse every page with its own reader and file each 4,500-character piece as a personal
memory (2,399 of 2,929 memories on one machine after one 349-PDF folder), summarise from the opening
of the first 17 documents only, and end the summary at the reply limit in mid-list.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# What one call has always read and written. Kept as it was: a call sized to the whole window took
# 32,000 tokens and a quarter of an hour on a processor. A big folder takes more calls instead.
PART_CHARS = 14000
SUMMARY_TOKENS = 700
PER_FILE_TOKENS = 520

_SYSTEM = "You are a precise technical analyst summarising a collection of research PDFs."
_PART_ASK = ("Below are the opening pages of {n} PDF documents from the folder “{folder}”{part}. Write a "
             "concise, technical summary of what they cover: the central topics, methods/formalism, and how "
             "the documents relate. Be specific and grounded ONLY in the text shown; do not invent results. "
             "Write formulas in LaTeX between $ signs.\n\n")
_JOIN_ASK = ("Below are {n} summaries, each of a share of the {docs} documents in the folder “{folder}”. Write "
             "one technical summary of the whole folder: the central topics, methods/formalism, and how the "
             "documents relate. Use only what the summaries say, and do not mention the summaries or how the "
             "folder was split. Write formulas in LaTeX between $ signs.\n\n")
_FILE_ASK = ("Summarise this single research document titled “{name}”. Cover: (1) the central topic/claim, "
             "(2) the methods/formalism used, (3) key findings or conclusions, and (4) any notable equations "
             "or results named in the text. Be specific and grounded ONLY in the text below; do not invent "
             "results or citations. Write formulas in LaTeX between $ signs.\n\n")


def _model():
    """The loaded model's call and the characters one call may read, or (None, 0): one document's own
    summary may use the window (as before); a part of the folder summary reads PART_CHARS."""
    from eli.cognition import gguf_inference as gi
    from eli.cognition.context_budget import chars_per_token
    try:
        if gi.load_model() is None:
            return None, 0
    except Exception:
        log.debug("no model for the folder summary", exc_info=True)
        return None, 0

    def call(text: str, reply_tokens: int) -> str:
        return finished(gi.chat_completion(text, system=_SYSTEM, max_tokens=reply_tokens, temperature=0.3) or "")

    room = int(max(0, int(gi.context_window() or 0) - SUMMARY_TOKENS) * float(chars_per_token())) - len(_SYSTEM)
    return call, room


_LONE_MARKER = re.compile(r"^\s*(?:#{1,6}|[-*+]|\d+[.)])?\s*\**\s*$")


def _line_done(line: str) -> bool:
    s = line.rstrip()
    return (not _LONE_MARKER.match(s) and s.count("**") % 2 == 0
            and bool(re.search(r"[.!?)\]}$`\"”’|]$|\*\*$", s)))


def finished(text: str) -> str:
    """A reply that hit its token limit ends mid-line ("4.  **"): end it at the last finished line."""
    whole = str(text or "").rstrip()
    lines = whole.split("\n")
    if _line_done(lines[-1]):
        return whole
    lines.pop()
    while lines and (not lines[-1].strip() or _LONE_MARKER.match(lines[-1])):
        lines.pop()
    return "\n".join(lines).rstrip() or (whole + "…" if whole else "")


def _pack(items: List[str], limit: int) -> List[List[str]]:
    parts: List[List[str]] = [[]]
    size = 0
    for item in items:
        if parts[-1] and size + len(item) > limit:
            parts.append([])
            size = 0
        parts[-1].append(item)
        size += len(item)
    return parts


def _summary(openings: List[str], folder: str, call, room: int, report) -> str:
    """One summary over every document: in parts of what a call can read, then the parts joined."""
    parts = _pack(openings, max(1, room - len(_PART_ASK)))
    notes = []
    for i, part in enumerate(parts, 1):
        report(i - 1, len(parts), "summarising")
        where = f" (part {i} of {len(parts)})" if len(parts) > 1 else ""
        notes.append(call(_PART_ASK.format(n=len(part), folder=folder, part=where) + "\n\n".join(part),
                          SUMMARY_TOKENS))
    report(len(parts), len(parts), "summarising")
    while len(notes) > 1:
        groups = _pack(notes, max(1, room - len(_JOIN_ASK)))
        if len(groups) == len(notes):
            break       # each summary alone fills a call: nothing left to join
        notes = [call(_JOIN_ASK.format(n=len(g), folder=folder, docs=len(openings)) + "\n\n---\n\n".join(g),
                      SUMMARY_TOKENS) for g in groups]
    return "\n\n".join(notes)


def analyse(folder: Any, *, recursive: bool = True, limit: Optional[int] = None, per_file: bool = False,
            user_id: str = "", fmt: str = "pdf",
            progress: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
    """`progress` defaults to the background job this runs in (its "check job" answer and ETA)."""
    from eli.memory.document_index import _PASSAGE_CHARS, document_files, get_document_index
    from eli.runtime.background_tasks import report as job_report
    from eli.runtime.rich_document import write_document

    def report(done: int, total: int, stage: str) -> None:
        try:
            (progress or job_report)(done, total, stage)
        except Exception:
            log.debug("progress report failed", exc_info=True)

    root = Path(str(folder)).expanduser()
    name = root.name or str(root)
    files = document_files(root, (".pdf",), recursive)
    if limit:
        files = files[: int(limit)]
    call, room = _model()
    # every document's opening gets an equal share of one call, and at least one whole passage
    share = max(_PASSAGE_CHARS, PART_CHARS // max(1, len(files))) if not per_file else max(_PASSAGE_CHARS, room)
    index = get_document_index()
    docs: List[Dict[str, Any]] = []
    unreadable: List[tuple] = []
    for n, path in enumerate(files):
        report(n, len(files), "reading")
        if index is not None:
            res = index.add(path, user_id=user_id, source="folder analysis", embed=False)
            if res.get("ok"):
                docs.append(index.outline(res["doc_id"], share))
            else:
                unreadable.append((path.name, res.get("error") or "unreadable"))
            continue
        from eli.plugins.document_reader.plugin import document_sections
        parts = document_sections(path)
        if not parts:
            unreadable.append((path.name, "no readable text"))
            continue
        text = "\n".join(t for _, t in parts)
        docs.append({"title": path.name, "path": str(path), "chars": len(text),
                     "pages": sum(1 for where, _ in parts if where.startswith("p. ")), "opening": text[:share]})
    report(len(files), len(files), "reading")
    if not docs:
        msg = (f"No readable PDF text found in “{name}” ({len(unreadable)} unreadable). The PDFs may be "
               "image-only/scanned (need OCR) or the folder has none.")
        return {"ok": True, "count": 0, "unreadable": [n for n, _ in unreadable], "content": msg}

    if per_file:
        blocks = []
        for i, d in enumerate(docs):
            report(i, len(docs), "summarising")
            text = call(_FILE_ASK.format(name=d["title"]) + d["opening"], PER_FILE_TOKENS) if call else ""
            blocks.append(f"## {d['title']}\n_{d['pages'] or '?'} pages_\n\n"
                          + (text or "(No model loaded: no summary.)"))
        report(len(docs), len(docs), "summarising")
        summary = "\n\n".join(blocks)
    elif call and docs:
        summary = _summary([f"### {d['title']}\n{d['opening']}" for d in docs], name, call, PART_CHARS, report)
    else:
        summary = "No model is loaded, so there is no summary; the documents are in the index."

    when = time.strftime("%d %B %Y")
    rows = "\n".join(f"| {i} | {d['title'].replace('|', '/')} | {d['pages'] or ''} | {d['chars']:,} |"
                     for i, d in enumerate(docs, 1))
    md = (f"{len(docs)} of {len(files)} documents read on {when}"
          + (f"; {len(unreadable)} could not be read." if unreadable else ".")
          + f"\n\n## {'Summaries' if per_file else 'Summary'}\n\n{summary}\n\n"
          + f"## Documents\n\n| # | Document | Pages | Characters |\n|---|---|---|---|\n{rows}\n")
    if unreadable:
        md += "\n## Could not be read\n\n" + "\n".join(f"- {n}: {why}" for n, why in unreadable) + "\n"
    title = f"{name}: {'each document' if per_file else 'what the documents cover'}"
    try:
        from eli.core.paths import data_dir
        out_dir = Path(data_dir()) / "documents"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M")
        suffix = "docx" if str(fmt).lower().lstrip(".") == "docx" else "pdf"
        path = write_document(md, out_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '_', name)}_{stamp}.{suffix}", title=title)
    except Exception:
        log.warning("folder summary not saved", exc_info=True)
        path = None
    if index is not None:
        for d in docs:          # meaning search: embedded by the index's worker, which yields to chat
            index.note(d["path"], user_id=user_id, source="folder analysis")
    return {"ok": True, "count": len(docs), "unreadable": [n for n, _ in unreadable], "document_path": str(path or ""),
            "content": md + (f"\nSaved as {path}" if path else ""), "title": title, "markdown": md}
