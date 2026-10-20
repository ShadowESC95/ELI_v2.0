#!/usr/bin/env python3
"""
eli_tools.analyze_pdfs

A robust, dependency-light PDF analysis helper.

One PDF at a time (ANALYZE_PDF): text extracted with pypdf (or PyPDF2), cut into chunks. A folder is read
through the document index instead (eli/runtime/folder_analysis.py).

This module is intentionally "boring": predictable, testable, and doesn’t pretend
to do OCR unless explicitly wired to an OCR backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import re
import time
import hashlib


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
