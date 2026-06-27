"""Local research corpus workspaces.

Ingest documents (PDF / text / Markdown) into an **isolated, searchable** index and
answer questions over them with source provenance. 100% local — text extraction +
the *same* nomic embedder ELI already loaded + FAISS. No network, no external surface.
Each corpus is its own index under ``artifacts/research/<name>/`` (separate from ELI's
personal memory), so your physics corpus and your chat memory never mix.

Never raises into callers — every entry point returns ``{"ok": bool, ...}``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_SUPPORTED = {".pdf", ".txt", ".md", ".markdown", ".rst", ".text"}


def _root() -> Path:
    from eli.core.paths import get_paths
    p = Path(get_paths().artifacts_dir) / "research"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "").strip()).strip("_")
    return s or "default"


def _corpus_dir(name: str) -> Path:
    d = _root() / _safe_name(name)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Embedding (reuse ELI's already-loaded nomic model) ──────────────────────
def _embedder():
    try:
        from eli.memory.vector_store import get_vector_store
        vs = get_vector_store()
        return vs._get_embedder() if vs else None
    except Exception:
        log.debug("research_corpus: embedder unavailable", exc_info=True)
        return None


def _embed_doc(text: str) -> Optional[list]:
    emb = _embedder()
    if emb is None:
        return None
    try:
        return emb.embed("search_document: " + text)
    except Exception:
        log.debug("research_corpus: doc embed failed", exc_info=True)
        return None


def _embed_query(text: str) -> Optional[list]:
    emb = _embedder()
    if emb is None:
        return None
    try:
        return emb.embed(text)  # shim auto-prefixes "search_query: "
    except Exception:
        log.debug("research_corpus: query embed failed", exc_info=True)
        return None


# ── Text extraction + chunking ──────────────────────────────────────────────
def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except Exception:
                return ""
        try:
            r = PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in r.pages)
        except Exception:
            log.debug("research_corpus: pdf read failed %s", path, exc_info=True)
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _chunk(text: str, size: int = 1200, overlap: int = 150) -> List[str]:
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    if not text:
        return []
    out, i, step = [], 0, max(1, size - overlap)
    while i < len(text):
        out.append(text[i:i + size])
        i += step
    return out


# ── Public API ──────────────────────────────────────────────────────────────
def ingest(corpus: str, path: str) -> Dict[str, Any]:
    """Ingest a file or folder of documents into ``corpus`` (append-only)."""
    import numpy as np
    import faiss
    src = Path(path).expanduser()
    if not src.exists():
        return {"ok": False, "error": f"path not found: {src}"}
    files = ([src] if src.is_file()
             else sorted(p for p in src.rglob("*") if p.is_file()))
    files = [f for f in files if f.suffix.lower() in _SUPPORTED]
    if not files:
        return {"ok": False, "error": "no supported documents (.pdf/.txt/.md) found"}

    d = _corpus_dir(corpus)
    idx_path, meta_path = d / "index.faiss", d / "chunks.jsonl"
    vecs: List[list] = []
    metas: List[dict] = []
    docs, skipped, dim = 0, [], None
    for f in files:
        chunks = _chunk(_extract_text(f))
        if not chunks:
            skipped.append(f.name)
            continue
        added = 0
        for c in chunks:
            v = _embed_doc(c)
            if v is None:
                return {"ok": False, "error": "embedder unavailable (nomic embed model not loaded)"}
            dim = len(v)
            vecs.append(v)
            metas.append({"source": f.name, "path": str(f), "text": c})
            added += 1
        if added:
            docs += 1
    if not vecs:
        return {"ok": False, "error": "no extractable text in the supplied documents"}

    arr = np.array(vecs, dtype="float32")
    if idx_path.exists():
        index = faiss.read_index(str(idx_path))
    else:
        index = faiss.IndexFlatL2(int(dim))
    index.add(arr)
    faiss.write_index(index, str(idx_path))
    with meta_path.open("a", encoding="utf-8") as fh:
        for m in metas:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    return {"ok": True, "corpus": _safe_name(corpus), "docs_added": docs,
            "chunks_added": len(vecs), "total_chunks": int(index.ntotal),
            "skipped": skipped}


def corpora() -> List[Dict[str, Any]]:
    """List all corpora with document + chunk counts."""
    out: List[Dict[str, Any]] = []
    try:
        for d in sorted(_root().iterdir()):
            if not d.is_dir():
                continue
            meta = d / "chunks.jsonl"
            n, srcs = 0, set()
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    n += 1
                    try:
                        srcs.add(json.loads(line).get("source"))
                    except Exception:
                        pass
            out.append({"corpus": d.name, "chunks": n, "documents": len(srcs)})
    except Exception:
        log.debug("research_corpus: list failed", exc_info=True)
    return out


def query(corpus: str, question: str, k: int = 6) -> Dict[str, Any]:
    """Retrieve the top-k most relevant chunks (with source + score) for a question."""
    import numpy as np
    import faiss
    d = _corpus_dir(corpus)
    idx_path, meta_path = d / "index.faiss", d / "chunks.jsonl"
    if not idx_path.exists() or not meta_path.exists():
        return {"ok": False, "error": f"corpus '{_safe_name(corpus)}' is empty — ingest documents first"}
    qv = _embed_query(question or "")
    if qv is None:
        return {"ok": False, "error": "embedder unavailable"}
    try:
        metas = [json.loads(line) for line in meta_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        index = faiss.read_index(str(idx_path))
        if index.ntotal == 0:
            return {"ok": True, "hits": []}
        D, I = index.search(np.array([qv], dtype="float32"), min(int(k), index.ntotal))
    except Exception as e:
        return {"ok": False, "error": str(e)}
    hits = []
    for dist, i in zip(D[0], I[0]):
        if 0 <= i < len(metas):
            m = metas[i]
            hits.append({"source": m.get("source"), "text": (m.get("text") or ""),
                         "score": round(float(1.0 / (1.0 + dist)), 4)})
    return {"ok": True, "hits": hits}
