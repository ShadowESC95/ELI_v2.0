#!/usr/bin/env python3
"""
eli_tools.analyze_pdfs

A robust, dependency-light PDF analysis helper.

Goals:
- Work on a folder of PDFs or a single PDF path.
- Extract text safely with pypdf (preferred) or PyPDF2 fallback.
- Chunk text and optionally store to ELI SQLite memory via MemoryDB (entries table).
- Return machine-friendly results for GUI + executor.

This module is intentionally "boring": predictable, testable, and doesn’t pretend
to do OCR unless explicitly wired to an OCR backend.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re
import json
import time
import hashlib

def _eli_path_get(obj, key, default=None):
    """
    Compatibility helper for ELI path containers.
    Accepts both dict-style path maps and object/namespace-style path maps.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

# Optional imports
_PYPDF_OK = False
try:
    from pypdf import PdfReader  # type: ignore
    _PYPDF_OK = True
except Exception:
    try:
        from PyPDF2 import PdfReader  # type: ignore
        _PYPDF_OK = True
    except Exception:
        _PYPDF_OK = False

def _norm_path(p: str | Path) -> Path:
    return Path(p).expanduser().resolve()

def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"

def _safe_text(s: str) -> str:
    # collapse insane whitespace, keep newlines
    s = s.replace("\x00", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def _chunk(text: str, max_chars: int = 4500, overlap: int = 200) -> List[str]:
    if max_chars <= 0:
        return [text]
    chunks: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + max_chars)
        chunks.append(text[i:j])
        if j >= n:
            break
        i = max(0, j - overlap)
    return chunks

@dataclass
class PDFDoc:
    path: str
    pages: int
    chars: int
    sha1: str
    extracted_at: float

@dataclass
class PDFAnalysis:
    doc: PDFDoc
    preview: str
    chunks: List[str]
    warnings: List[str]

def _sha1_file(path: Path, block: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def extract_text(path: str | Path, max_pages: Optional[int] = None) -> Tuple[str, List[str], int]:
    """
    Returns: (text, warnings, pages_read)
    """
    warnings: List[str] = []
    p = _norm_path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if not _is_pdf(p):
        raise ValueError(f"Not a PDF: {p}")

    if not _PYPDF_OK:
        raise RuntimeError("No PDF reader available. Install 'pypdf' (recommended).")

    reader = PdfReader(str(p))
    total_pages = len(reader.pages)
    pages_to_read = total_pages if max_pages is None else min(total_pages, max(1, int(max_pages)))

    out: List[str] = []
    for i in range(pages_to_read):
        try:
            page = reader.pages[i]
            t = page.extract_text() or ""
            out.append(t)
        except Exception as e:
            warnings.append(f"page {i+1}: {type(e).__name__}: {e}")

    text = _safe_text("\n\n".join(out))
    if not text:
        warnings.append("No extractable text found (PDF may be scanned images). OCR not enabled.")
    return text, warnings, pages_to_read

def analyze(path: str | Path, *,
            max_pages: Optional[int] = None,
            chunk_chars: int = 4500,
            overlap: int = 200,
            preview_chars: int = 800) -> PDFAnalysis:
    p = _norm_path(path)
    text, warnings, pages_read = extract_text(p, max_pages=max_pages)
    chunks = _chunk(text, max_chars=chunk_chars, overlap=overlap) if text else []
    sha1 = _sha1_file(p)
    doc = PDFDoc(path=str(p), pages=pages_read, chars=len(text), sha1=sha1, extracted_at=time.time())
    preview = text[:preview_chars] if text else ""
    return PDFAnalysis(doc=doc, preview=preview, chunks=chunks, warnings=warnings)

def analyze_folder(folder: str | Path, *,
                   recursive: bool = True,
                   limit: Optional[int] = None,
                   **kwargs: Any) -> Dict[str, Any]:
    """
    Analyze all PDFs in a folder.

    Returns dict with keys:
      ok, folder, count, results (list), errors (list)
    """
    root = _norm_path(folder)
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    pdfs = sorted([p for p in (root.rglob("*.pdf") if recursive else root.glob("*.pdf"))])
    if limit is not None:
        pdfs = pdfs[: max(0, int(limit))]

    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for p in pdfs:
        try:
            a = analyze(p, **kwargs)
            results.append({
                "doc": asdict(a.doc),
                "preview": a.preview,
                "chunks": a.chunks,
                "warnings": a.warnings,
            })
        except Exception as e:
            errors.append({"path": str(p), "error": f"{type(e).__name__}: {e}"})

    return {"ok": True, "folder": str(root), "count": len(results), "results": results, "errors": errors}

def store_analysis_to_memory(db_path: str | Path, analysis: PDFAnalysis, *,
                             kind_prefix: str = "pdf",
                             tags: Optional[List[str]] = None,
                             meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Store PDF analysis into the ELI memory DB (entries table).
    Requires _eli_path_get(brain, "memory_db").MemoryDB.
    """
    from eli.memory.habits_memory_db import MemoryDB  # absolute import — tools/analysis has no local memory_db

    tags = tags or []
    meta = meta or {}
    meta = dict(meta)
    meta.update({"pdf": asdict(analysis.doc)})

    db = MemoryDB(db_path)
    doc_id = analysis.doc.sha1[:12]
    base_kind = f"{kind_prefix}:{doc_id}"

    # store a summary entry
    db.add_entry(kind=base_kind, role="system",
                 content=f"PDF {analysis.doc.path}\nPages read: {analysis.doc.pages}\nChars: {analysis.doc.chars}\n\nPreview:\n{analysis.preview}",
                 tags=tags + ["pdf", "preview"], meta=meta)

    # store chunks
    for idx, ch in enumerate(analysis.chunks):
        db.add_entry(kind=f"{base_kind}:chunk:{idx+1}", role="system", content=ch,
                     tags=tags + ["pdf", "chunk"], meta=meta)

    return {"ok": True, "doc_id": doc_id, "chunks": len(analysis.chunks)}
