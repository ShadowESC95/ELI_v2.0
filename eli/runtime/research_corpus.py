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
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _audit_research(action: str, corpus: str, user: str, detail: str = "") -> None:
    """Record a research collaboration event into the tamper-evident audit ledger
    (who did what, in which corpus). Best-effort — never raises into callers."""
    try:
        from eli.runtime.evidence_ledger import record_event
        record_event("research", source="research", action=action,
                     subject=_safe_name(corpus), content=detail,
                     user_id=(user or "anon"), reusable=False)
    except Exception:
        log.debug("research_corpus: audit failed", exc_info=True)

_SUPPORTED = {".pdf", ".txt", ".md", ".markdown", ".rst", ".text"}

# Hard caps on a single ingest so a directory walk can't exhaust CPU/RAM/disk
# (override via env for power users with large local corpora).
_MAX_FILES = int(os.environ.get("ELI_RESEARCH_MAX_FILES", "2000"))
_MAX_BYTES = int(os.environ.get("ELI_RESEARCH_MAX_BYTES", str(512 * 1024 * 1024)))  # 512 MB


def _root() -> Path:
    from eli.core.paths import get_paths
    p = Path(get_paths().artifacts_dir) / "research"
    p.mkdir(parents=True, exist_ok=True)
    return p


def research_source_root() -> Path:
    """The ONLY directory ingest may read documents from. Confines the file-read
    primitive: a client (possibly remote, over the LAN) can never make the server
    embed and echo back arbitrary host files (~/.config, exported data, /etc, …).

    Defaults to ``artifacts/research/_sources`` (the leading underscore can never
    collide with a sanitised corpus-index dir); override with ``ELI_RESEARCH_ROOT``
    to point at your own documents folder (e.g. a papers/PDF library)."""
    env = os.environ.get("ELI_RESEARCH_ROOT", "").strip()
    root = Path(env).expanduser() if env else (_root() / "_sources")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _resolve_within_root(path: str) -> Path:
    """Resolve a caller-supplied path against the research root and REJECT anything
    that escapes it (absolute paths outside, ``..`` traversal, or symlink escapes —
    ``resolve()`` collapses all three before the containment check)."""
    root = research_source_root()
    p = Path(path or "").expanduser()
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    try:
        p.relative_to(root)  # raises if p is not root or beneath it
    except ValueError:
        raise ValueError(f"path is outside the research root ({root}); "
                         f"set ELI_RESEARCH_ROOT or place documents under it")
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


def _gather_files(src: Path, root: Path):
    """Collect supported documents under ``src`` (already confined to ``root``),
    bounded by file-count and total-byte caps and safe against symlink escapes.
    Returns a list of Paths, or a ``{"ok": False, "error": ...}`` dict if a cap is hit."""
    if src.is_file():
        candidates = [src]
    else:
        candidates = []
        # followlinks=False: a symlinked subdirectory can't redirect the walk outside root.
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
            for fn in sorted(filenames):
                fp = Path(dirpath) / fn
                if fp.suffix.lower() not in _SUPPORTED:
                    continue
                candidates.append(fp)
                if len(candidates) > _MAX_FILES:
                    return {"ok": False, "error": (
                        f"too many documents (> {_MAX_FILES}); narrow the path or raise "
                        f"ELI_RESEARCH_MAX_FILES")}

    files: List[Path] = []
    total = 0
    for fp in candidates:
        if fp.suffix.lower() not in _SUPPORTED:
            continue
        try:
            rp = fp.resolve()
            rp.relative_to(root)  # reject individual files that symlink outside root
            sz = rp.stat().st_size
        except (ValueError, OSError):
            continue
        total += sz
        if total > _MAX_BYTES:
            return {"ok": False, "error": (
                f"total document size exceeds {_MAX_BYTES} bytes; narrow the path or raise "
                f"ELI_RESEARCH_MAX_BYTES")}
        files.append(fp)
    return files


# ── Public API ──────────────────────────────────────────────────────────────
def _append(corpus: str, vecs: List[list], metas: List[dict], dim: int) -> int:
    """Append vectors + metadata to a corpus index (append-only). Returns total chunks."""
    import numpy as np
    import faiss
    d = _corpus_dir(corpus)
    idx_path, meta_path = d / "index.faiss", d / "chunks.jsonl"
    arr = np.array(vecs, dtype="float32")
    index = faiss.read_index(str(idx_path)) if idx_path.exists() else faiss.IndexFlatL2(int(dim))
    index.add(arr)
    faiss.write_index(index, str(idx_path))
    with meta_path.open("a", encoding="utf-8") as fh:
        for m in metas:
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
    return int(index.ntotal)


def ingest(corpus: str, path: str, user: str = "") -> Dict[str, Any]:
    """Ingest a file or folder of documents into ``corpus`` (append-only), attributed
    to ``user`` so collaborators can see who contributed what.

    The source path is confined to the research root (see ``research_source_root``)
    — caller-supplied paths that escape it are rejected — and the walk is bounded by
    ``_MAX_FILES`` / ``_MAX_BYTES`` so a directory ingest cannot walk the whole disk."""
    try:
        src = _resolve_within_root(path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not src.exists():
        return {"ok": False, "error": f"path not found within research root: {path}"}

    root = research_source_root()
    files = _gather_files(src, root)
    if isinstance(files, dict):  # cap/error sentinel
        return files
    if not files:
        return {"ok": False, "error": "no supported documents (.pdf/.txt/.md) found within the research root"}

    now = time.time()
    by = (user or "anon")
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
            metas.append({"source": f.name, "path": str(f), "text": c,
                          "added_by": by, "added_at": now})
            added += 1
        if added:
            docs += 1
    if not vecs:
        return {"ok": False, "error": "no extractable text in the supplied documents"}

    total = _append(corpus, vecs, metas, dim)
    _audit_research("INGEST", corpus, by, f"{docs} document(s), {len(vecs)} chunk(s)")
    return {"ok": True, "corpus": _safe_name(corpus), "docs_added": docs,
            "chunks_added": len(vecs), "total_chunks": total, "skipped": skipped}


def add_note(corpus: str, title: str, text: str, user: str = "") -> Dict[str, Any]:
    """Create a text 'note' document directly in a corpus — collaborative create/share
    without a file. Re-adding the same title replaces the old note (simple edit)."""
    title = (title or "").strip() or "note"
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty note text"}
    # Edit semantics: drop any existing note with this title first.
    existing = {m.get("source") for m in _read_metas(corpus)}
    if title in existing:
        remove_document(corpus, title, user=user, _silent=True)
    chunks = _chunk(text)
    now = time.time()
    by = (user or "anon")
    vecs, metas, dim = [], [], None
    for c in chunks:
        v = _embed_doc(c)
        if v is None:
            return {"ok": False, "error": "embedder unavailable (nomic embed model not loaded)"}
        dim = len(v)
        vecs.append(v)
        metas.append({"source": title, "path": "note", "text": c,
                      "added_by": by, "added_at": now})
    if not vecs:
        return {"ok": False, "error": "note produced no content"}
    total = _append(corpus, vecs, metas, dim)
    _audit_research("NOTE", corpus, by, f"note '{title}' ({len(vecs)} chunk(s))")
    return {"ok": True, "corpus": _safe_name(corpus), "note": title,
            "chunks_added": len(vecs), "total_chunks": total}


def _read_metas(corpus: str) -> List[dict]:
    meta_path = _corpus_dir(corpus) / "chunks.jsonl"
    if not meta_path.exists():
        return []
    out = []
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def documents(corpus: str) -> List[Dict[str, Any]]:
    """List the distinct documents in a corpus with who added each and when."""
    by_source: Dict[str, Dict[str, Any]] = {}
    for m in _read_metas(corpus):
        s = m.get("source") or "?"
        rec = by_source.setdefault(s, {"source": s, "kind": ("note" if m.get("path") == "note" else "file"),
                                       "added_by": m.get("added_by") or "anon",
                                       "added_at": m.get("added_at") or 0, "chunks": 0})
        rec["chunks"] += 1
    return sorted(by_source.values(), key=lambda r: r.get("added_at") or 0, reverse=True)


def members(corpus: str) -> List[str]:
    """Distinct contributors to a corpus (who has added documents)."""
    return sorted({(m.get("added_by") or "anon") for m in _read_metas(corpus)})


def remove_document(corpus: str, source: str, user: str = "", _silent: bool = False) -> Dict[str, Any]:
    """Remove a document (all its chunks) from a corpus, rebuilding the index from the
    remaining vectors (no re-embedding). Enables collaborative edit/cleanup."""
    import numpy as np
    import faiss
    d = _corpus_dir(corpus)
    idx_path, meta_path = d / "index.faiss", d / "chunks.jsonl"
    metas = _read_metas(corpus)
    if not metas or not idx_path.exists():
        return {"ok": False, "error": "corpus empty"}
    keep = [i for i, m in enumerate(metas) if m.get("source") != source]
    if len(keep) == len(metas):
        return {"ok": False, "error": f"no document named '{source}'"}
    try:
        index = faiss.read_index(str(idx_path))
        dim = index.d
        if keep:
            vecs = np.vstack([index.reconstruct(int(i)) for i in keep]).astype("float32")
            new_index = faiss.IndexFlatL2(dim)
            new_index.add(vecs)
        else:
            new_index = faiss.IndexFlatL2(dim)
        faiss.write_index(new_index, str(idx_path))
        with meta_path.open("w", encoding="utf-8") as fh:
            for i in keep:
                fh.write(json.dumps(metas[i], ensure_ascii=False) + "\n")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not _silent:
        _audit_research("REMOVE", corpus, (user or "anon"), f"removed '{source}'")
    return {"ok": True, "corpus": _safe_name(corpus), "removed": source,
            "total_chunks": len(keep)}


def activity(corpus: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Recent collaboration activity in a corpus (who ingested/added/asked), from the
    tamper-evident audit ledger."""
    try:
        from eli.runtime.evidence_ledger import recent_events
        rows = recent_events(limit=400, event_type="research")
    except Exception:
        return []
    name = _safe_name(corpus)
    out = []
    for e in rows:
        if e.get("subject") != name:
            continue
        out.append({"action": e.get("action"), "user": e.get("user_id"),
                    "detail": e.get("content"), "timestamp": e.get("timestamp")})
        if len(out) >= int(limit):
            break
    return out


def corpora() -> List[Dict[str, Any]]:
    """List all corpora with document/chunk counts and contributor (member) count."""
    out: List[Dict[str, Any]] = []
    try:
        for d in sorted(_root().iterdir()):
            # Skip the source-documents sandbox dir — it is not a corpus.
            if not d.is_dir() or d.name == "_sources":
                continue
            n, srcs, who = 0, set(), set()
            meta = d / "chunks.jsonl"
            if meta.exists():
                for line in meta.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    n += 1
                    try:
                        row = json.loads(line)
                        srcs.add(row.get("source"))
                        who.add(row.get("added_by") or "anon")
                    except Exception:
                        pass
            out.append({"corpus": d.name, "chunks": n, "documents": len(srcs),
                        "members": len(who)})
    except Exception:
        log.debug("research_corpus: list failed", exc_info=True)
    return out


def query(corpus: str, question: str, k: int = 6, user: str = "") -> Dict[str, Any]:
    """Retrieve the top-k most relevant chunks (with source + score) for a question,
    attributing the query to ``user`` in the corpus activity feed."""
    import numpy as np
    import faiss
    if (question or "").strip():
        _audit_research("QUERY", corpus, (user or "anon"), (question or "")[:160])
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
