"""The document index: every document ELI has read, kept whole and found again by passage.

`engine.document_rag` was never set, so the orchestrator's document channel returned nothing on
every turn ("rag: 0"), and the reader hands a reply only a file's first 8000 characters: page 40
of a PDF ELI had "read" did not exist for it. A document ELI reads, summarises, writes or is
handed is now stored in full, cut into passages, and searched by wording (FTS5) and by meaning
(the embedder the memory store already loads). Text and vectors sit in one SQLite file, so
removing a document removes everything made from it.
"""
from __future__ import annotations

import hashlib
import os
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from eli.utils.log import get_logger

log = get_logger(__name__)

SUFFIXES = frozenset((".pdf", ".docx", ".odt", ".epub", ".txt", ".md", ".markdown", ".rst", ".text", ".tex", ".org"))
# Never stored, whatever asked to read it.
_PRIVATE_NAME = re.compile(
    r"(?i)(?:^\.env|\.pem$|\.key$|\.kdbx$|id_rsa|id_ed25519|credential|secret|passw(?:or)?d|token|wallet|recovery[-_ ]?code)")
_MAX_BYTES = 96 * 1024 * 1024
_PASSAGE_CHARS = 900
_OVERLAP_CHARS = 120
_MAX_PASSAGES = 6000

# Cosines from the nomic embedder sit high and close together: measured on real documents,
# passages that answer the question score 0.69-0.84 and unrelated ones up to 0.66. A passage
# nobody asked for is offered only above the first, or above the second with the wording to match.
_COS_STRONG = 0.70
_COS_WORDED = 0.64

_STOP = frozenset("""a about above after again all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its just me more most my no nor not now of off on once only or other our out over
own same she should so some such than that the their them then there these they this those through to too under until
up very was we were what when where which while who whom why will with would you your yours tell say said give show
find look please want need know think document documents file files pdf paper report notes page pages""".split())

_ASKS_RE = re.compile(
    r"\b(?:documents?|docs?|files?|pdfs?|papers?|reports?|articles?|chapters?|books?|e-?books?|essays?|coursework|"
    r"thesis|dissertation|manuals?|handbook|specs?|specification|contracts?|policy|policies|transcripts?|slides?|"
    r"notes|readme|codebase|attachments?|what i (?:sent|gave|showed|uploaded|dropped)|you (?:read|summari[sz]ed|analy[sz]ed))\b",
    re.I)


def asks_about_documents(text: Any) -> bool:
    """The question names a document or a kind of one."""
    return bool(_ASKS_RE.search(str(text or "")))


_THAT_ONE = re.compile(
    r"\b(?:that|this|the|same)\s+(?:file|document|doc|pdf|paper|report|article|book|chapter|attachment)\b", re.I)
_ATTACHED = re.compile(r"\[(?:File|PDF):\s*(.+?)\]")


def attached_paths(text: Any) -> List[str]:
    """Files handed over with the message (the GUI writes a dropped file as "[File: path]")."""
    return [m.strip() for m in _ATTACHED.findall(str(text or "")) if m.strip()]


def _terms(text: str) -> List[str]:
    out: List[str] = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-']{2,}", str(text or "").lower()):
        w = w.strip("'-_")
        if len(w) >= 3 and w not in _STOP and w not in out:
            out.append(w)
    return out[:24]


def _named(terms: Sequence[str], titles: Dict[int, str]) -> List[int]:
    """Documents whose title shares a word with the question ("the harbour pack", "my garden file")."""
    asked = {t[:6] for t in terms if len(t) >= 4}
    if not asked:
        return []
    out = []
    for doc_id, title in titles.items():
        words = {w[:6] for w in re.findall(r"[a-z0-9]{4,}", Path(str(title)).stem.lower()) if w not in _STOP}
        if asked & words:
            out.append(int(doc_id))
    return out


def indexable(path: Any) -> bool:
    """A document worth keeping: a prose format, not a secret, not enormous."""
    try:
        p = Path(str(path)).expanduser()
        if p.suffix.lower() not in SUFFIXES or _PRIVATE_NAME.search(p.name):
            return False
        if any(part in (".ssh", ".gnupg", ".aws", ".kube") for part in p.parts):
            return False
        return p.is_file() and 0 < p.stat().st_size <= _MAX_BYTES
    except Exception:
        return False


def passages(sections: Sequence[tuple]) -> List[tuple]:
    """(where, text) parts cut into overlapping passages that end on a paragraph or sentence."""
    out: List[tuple] = []
    for where, text in sections:
        text = re.sub(r"[ \t]+", " ", str(text or "")).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        at = 0
        while at < len(text) and len(out) < _MAX_PASSAGES:
            end = min(len(text), at + _PASSAGE_CHARS)
            if end < len(text):
                window = text[at:end]
                cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind(".\n"), window.rfind("\n"))
                if cut > _PASSAGE_CHARS // 2:
                    end = at + cut + 1
            piece = text[at:end].strip()
            if len(piece) >= 40 or (piece and not out):
                out.append((where, piece))
            if end >= len(text):
                break
            # overlap with the passage before, starting on a word
            back = max(end - _OVERLAP_CHARS, at + 1)
            space = text.find(" ", back, end)
            at = space + 1 if space >= 0 else back
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _owner(user_id: str) -> bool:
    if not user_id:
        return True
    try:
        from eli.kernel.state import get_active_user_id
        return str(user_id) == str(get_active_user_id())
    except Exception:
        return True


class DocumentIndex:
    def __init__(self, db_path: Optional[Any] = None, embed: Optional[Callable[[str], Any]] = None):
        if db_path is None:
            from eli.core.paths import document_index_db_path
            db_path = document_index_db_path()
        self._db = Path(db_path)
        self._embed_fn = embed
        self._lock = threading.RLock()
        self._jobs: "queue.Queue" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._fts = True
        self._matrix: Optional[tuple] = None  # (chunk ids, doc ids, vectors)
        self._stats: Optional[Dict[str, int]] = None
        self._refreshed = False
        self._schema()

    # ── storage ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._db), timeout=15.0)
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _schema(self) -> None:
        con = self._connect()
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS documents(
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    mtime REAL NOT NULL DEFAULT 0,
                    chars INTEGER NOT NULL DEFAULT 0,
                    passages INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT '',
                    added_at REAL NOT NULL DEFAULT 0,
                    UNIQUE(path, user_id));
                CREATE TABLE IF NOT EXISTS passages(
                    id INTEGER PRIMARY KEY,
                    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    n INTEGER NOT NULL,
                    place TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    vec BLOB);
                CREATE INDEX IF NOT EXISTS passages_doc ON passages(doc_id, n);
            """)
            try:
                con.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts
                        USING fts5(text, content='passages', content_rowid='id', tokenize='porter unicode61');
                    CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
                        INSERT INTO passages_fts(rowid, text) VALUES (new.id, new.text); END;
                    CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
                        INSERT INTO passages_fts(passages_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
                """)
            except sqlite3.OperationalError:
                self._fts = False  # an SQLite built without FTS5: wording falls back to LIKE
                log.debug("document index: FTS5 unavailable, using LIKE")
            con.commit()
        finally:
            con.close()

    def _changed(self) -> None:
        with self._lock:
            self._matrix = None
            self._stats = None

    def _scope(self, user_id: Optional[str]) -> tuple:
        uid = str(user_id or "")
        if _owner(uid):
            return "d.user_id IN (?, '')", (uid,)
        return "d.user_id = ?", (uid,)

    # ── adding ───────────────────────────────────────────────────────────────

    def add(self, path: Any, *, user_id: str = "", source: str = "", embed: bool = True) -> Dict[str, Any]:
        """Store a document whole. Unchanged since last time, it is left as it is."""
        if not indexable(path):
            return {"ok": False, "error": "not_indexable", "path": str(path)}
        p = Path(str(path)).expanduser().resolve()
        uid = str(user_id or "")
        try:
            stat = p.stat()
            digest = _sha256(p)
        except OSError as e:
            return {"ok": False, "error": str(e), "path": str(p)}
        con = self._connect()
        try:
            row = con.execute("SELECT id, sha256, passages FROM documents WHERE path=? AND user_id=?",
                              (str(p), uid)).fetchone()
        finally:
            con.close()
        if row and row[1] == digest:
            con = self._connect()
            try:
                con.execute("UPDATE documents SET added_at=? WHERE id=?", (time.time(), int(row[0])))
                con.commit()
            finally:
                con.close()
            if embed:
                self._embed_pending(int(row[0]))
            return {"ok": True, "unchanged": True, "doc_id": int(row[0]), "passages": int(row[2]), "path": str(p)}
        try:
            from eli.plugins.document_reader.plugin import document_sections
            parts = passages(document_sections(p))
        except Exception as e:
            log.debug("document index: could not read %s", p, exc_info=True)
            return {"ok": False, "error": str(e), "path": str(p)}
        if not parts:
            return {"ok": False, "error": "no_text", "path": str(p)}
        with self._lock:
            con = self._connect()
            try:
                con.execute("DELETE FROM documents WHERE path=? AND user_id=?", (str(p), uid))
                cur = con.execute(
                    "INSERT INTO documents(path, user_id, title, sha256, size, mtime, chars, passages, source, added_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (str(p), uid, p.name, digest, int(stat.st_size), float(stat.st_mtime),
                     sum(len(t) for _, t in parts), len(parts), str(source or ""), time.time()))
                doc_id = int(cur.lastrowid)
                con.executemany("INSERT INTO passages(doc_id, n, place, text) VALUES (?,?,?,?)",
                                [(doc_id, i, where, text) for i, (where, text) in enumerate(parts, 1)])
                con.commit()
            finally:
                con.close()
        self._changed()
        self._ledger("INDEX", str(p), f"{len(parts)} passages" + (f", via {source}" if source else ""), uid)
        log.debug("[DOCUMENTS] indexed %s: %d passages", p.name, len(parts))
        if embed:
            self._embed_pending(doc_id)
        return {"ok": True, "doc_id": doc_id, "passages": len(parts), "path": str(p)}

    def note(self, path: Any, *, user_id: str = "", source: str = "") -> bool:
        """Queue a document ELI has just read or written. Returns at once; a worker does the rest."""
        if not indexable(path):
            return False
        self._jobs.put((str(path), str(user_id or ""), str(source or "")))
        self._start()
        return True

    def _start(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="eli-document-index", daemon=True)
                self._worker.start()

    def _run(self) -> None:
        while True:
            try:
                path, uid, source = self._jobs.get(timeout=30.0)
            except queue.Empty:
                return
            try:
                self.add(path, user_id=uid, source=source)
            except Exception:
                log.debug("document index: job failed for %s", path, exc_info=True)
            finally:
                self._jobs.task_done()

    def wait(self, timeout: float = 30.0) -> bool:
        """Block until queued documents are stored and embedded (tests, and "index this now")."""
        end = time.monotonic() + float(timeout)
        while self._jobs.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.05)
        return not self._jobs.unfinished_tasks

    # ── meaning ──────────────────────────────────────────────────────────────

    def _embed(self, text: str, *, query: bool = False) -> Optional[Any]:
        try:
            import numpy as np
            if self._embed_fn is not None:
                vec = self._embed_fn(text)
            else:
                from eli.memory.vector_store import get_vector_store
                store = get_vector_store()
                vec = store._embed(text if query else "search_document: " + text) if store else None
            if vec is None:
                return None
            arr = np.asarray(vec, dtype="float32").reshape(-1)
            norm = float(np.linalg.norm(arr))
            return arr / norm if norm else None
        except Exception:
            log.debug("document index: embed failed", exc_info=True)
            return None

    def _yield_to_conversation(self) -> None:
        """Embedding shares the CPU and the llama.cpp lock with the model: wait while a turn is live."""
        if self._embed_fn is not None:
            return
        try:
            from eli.cognition.inference_broker import foreground_recently_active
            waited = 0.0
            while foreground_recently_active(5.0) and waited < 600.0:
                time.sleep(1.0)
                waited += 1.0
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    def _embed_pending(self, doc_id: int) -> int:
        con = self._connect()
        try:
            rows = con.execute("SELECT id, text FROM passages WHERE doc_id=? AND vec IS NULL ORDER BY n", (doc_id,)).fetchall()
        finally:
            con.close()
        done = 0
        for pid, text in rows:
            self._yield_to_conversation()
            vec = self._embed(text)
            if vec is None:
                break  # no embedder: wording search still works
            con = self._connect()
            try:
                con.execute("UPDATE passages SET vec=? WHERE id=?", (vec.astype("float16").tobytes(), pid))
                con.commit()
            finally:
                con.close()
            done += 1
            if self._embed_fn is None:
                time.sleep(0.01)  # let a waiting generation take the lock
        if done:
            self._changed()
        return done

    def _vectors(self) -> Optional[tuple]:
        with self._lock:
            if self._matrix is not None:
                return self._matrix
        try:
            import numpy as np
            con = self._connect()
            try:
                rows = con.execute("SELECT id, doc_id, vec FROM passages WHERE vec IS NOT NULL").fetchall()
            finally:
                con.close()
            if not rows:
                return None
            width = len(rows[0][2]) // 2
            rows = [r for r in rows if len(r[2]) == width * 2]
            mat = np.frombuffer(b"".join(r[2] for r in rows), dtype="float16").astype("float32").reshape(len(rows), width)
            built = ([r[0] for r in rows], [r[1] for r in rows], mat)
            with self._lock:
                self._matrix = built
            return built
        except Exception:
            log.debug("document index: vectors unavailable", exc_info=True)
            return None

    # ── finding ──────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 8, *, user_id: Optional[str] = None,
               strict: bool = False, doc_ids: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
        """Passages for a question, best first.

        `strict` is for a question that did not ask about a document: only passages that clearly
        bear on it come back. `doc_ids` keeps the search to those documents (the ones handed over
        with the message); a question that names a document by its title is kept to it the same
        way. Inside named documents a question too general to match a passage ("what is this?")
        gets how they open."""
        limit = max(1, int(limit))
        query = _ATTACHED.sub(" ", str(query or "")).strip()
        if not query or not self.stats()["passages"]:
            return []
        where, args = self._scope(user_id)
        terms = _terms(query)
        con = self._connect()
        try:
            listed = con.execute(f"SELECT d.id, d.title, d.added_at FROM documents d WHERE {where}", args).fetchall()
            titles = {r[0]: r[1] for r in listed}
            if doc_ids is None and listed:
                named = _named(terms, titles)
                if not named and _THAT_ONE.search(query):
                    named = [max(listed, key=lambda r: r[2])[0]]  # "that file": the one read last
                if named:
                    doc_ids, strict = named, False
            visible = set(titles) if doc_ids is None else set(titles) & {int(i) for i in doc_ids}
            if not visible:
                return []
            marks = ",".join(str(i) for i in sorted(visible))
            worded: List[int] = []
            if terms:
                try:
                    if not self._fts:
                        raise sqlite3.OperationalError("no fts5")
                    match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
                    worded = [r[0] for r in con.execute(
                        f"SELECT p.id FROM passages_fts f JOIN passages p ON p.id = f.rowid "
                        f"WHERE passages_fts MATCH ? AND p.doc_id IN ({marks}) ORDER BY bm25(passages_fts) LIMIT ?",
                        (match, limit * 6))]
                except sqlite3.OperationalError:
                    like = " OR ".join("p.text LIKE ?" for _ in terms)
                    worded = [r[0] for r in con.execute(
                        f"SELECT p.id FROM passages p WHERE ({like}) AND p.doc_id IN ({marks}) LIMIT ?",
                        (*[f"%{t}%" for t in terms], limit * 6))]
            cosine = self._closest(query, terms, visible, limit * 6, both=not strict)
            fused: Dict[int, float] = {}
            for rank, pid in enumerate(worded):
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (60 + rank)
            for rank, pid in enumerate(sorted(cosine, key=cosine.get, reverse=True)):
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (60 + rank)
            # Next to nothing matched inside the named documents: the question is about the
            # document as a whole ("what is this?"), so show how it opens.
            if doc_ids is not None and len(fused) < 2:
                for rank, (pid,) in enumerate(con.execute(
                        f"SELECT id FROM passages WHERE doc_id IN ({marks}) ORDER BY doc_id, n LIMIT ?", (limit,))):
                    fused.setdefault(pid, 1.0 / (200 + rank))
            if not fused:
                return []
            ids = sorted(fused, key=fused.get, reverse=True)[:limit * 4]
            rows = {r[0]: r for r in con.execute(
                f"SELECT p.id, p.doc_id, p.n, p.place, p.text, d.title, d.path, d.passages, d.added_at "
                f"FROM passages p JOIN documents d ON d.id = p.doc_id WHERE p.id IN ({','.join('?' * len(ids))})", ids)}
        finally:
            con.close()
        out: List[Dict[str, Any]] = []
        for pid in ids:
            r = rows.get(pid)
            if r is None:
                continue
            low = r[4].lower()
            shared = sum(1 for t in terms if t[:6] in low)
            cos = cosine.get(pid)
            # No cosine for a passage means it is not among the nearest (or nothing is embedded yet).
            near = (cos >= _COS_WORDED) if cos is not None else not cosine
            if strict:
                close = cos is not None and cos >= _COS_STRONG
                if not (close or (shared >= max(2, (len(terms) + 1) // 2) and near)):
                    continue
            elif doc_ids is None and not shared and not (cos is not None and cos >= _COS_WORDED):
                continue
            out.append({"id": pid, "doc_id": r[1], "part": r[2], "parts": r[7], "where": r[3], "text": r[4],
                        "title": r[5], "path": r[6], "ts": r[8], "score": round(fused[pid] * 30, 4),
                        "cosine": cos, "shared_terms": shared, "source": "document"})
            if len(out) >= limit:
                break
        return out

    def _closest(self, query: str, terms: List[str], visible: set, count: int, *, both: bool) -> Dict[int, float]:
        """Passage id -> cosine for the passages nearest in meaning. A question about a document
        is wrapped in words about documents ("what does the file say about gardening"), which
        pull it away from the passage; with `both`, the bare subject is tried as well."""
        import numpy as np
        vectors = self._vectors()
        if vectors is None:
            return {}
        asked = [query]
        if both and terms and " ".join(terms) != query.lower():
            asked.append(" ".join(terms))
        scores = None
        for text in asked:
            q = self._embed(text, query=True)
            if q is None or vectors[2].shape[1] != q.shape[0]:
                continue
            s = vectors[2] @ q
            scores = s if scores is None else np.maximum(scores, s)
        if scores is None:
            return {}
        out: Dict[int, float] = {}
        for i in scores.argsort()[::-1]:
            if vectors[1][i] in visible:
                out[vectors[0][i]] = float(scores[i])
                if len(out) >= count:
                    break
        return out

    def mentions(self, query: str, user_id: Optional[str] = None) -> bool:
        """The question names an indexed document by a word of its title."""
        return bool(_named(_terms(query), {d["id"]: d["title"] for d in self.documents(user_id)}))

    def documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        where, args = self._scope(user_id)
        con = self._connect()
        try:
            return [{"id": r[0], "title": r[1], "path": r[2], "passages": r[3], "added_at": r[4], "source": r[5]}
                    for r in con.execute(
                        f"SELECT d.id, d.title, d.path, d.passages, d.added_at, d.source FROM documents d "
                        f"WHERE {where} ORDER BY d.added_at DESC", args)]
        finally:
            con.close()

    def matching(self, query: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Documents a request to forget something names: by title words or by file name."""
        low = str(query or "").lower()
        words = {w for w in _terms(query) if len(w) >= 4}
        out = []
        for doc in self.documents(user_id):
            stem = Path(doc["title"]).stem.lower()
            if doc["title"].lower() in low or stem in low or (words & set(re.findall(r"[a-z0-9]{4,}", stem))):
                out.append(doc)
        return out

    def stats(self) -> Dict[str, int]:
        with self._lock:
            if self._stats is not None:
                return dict(self._stats)
        con = self._connect()
        try:
            docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            total, embedded = con.execute("SELECT COUNT(*), COUNT(vec) FROM passages").fetchone()
        finally:
            con.close()
        stats = {"documents": int(docs), "passages": int(total), "embedded": int(embedded or 0)}
        with self._lock:
            self._stats = stats
        return dict(stats)

    # ── removing ─────────────────────────────────────────────────────────────

    def remove(self, doc_ids: Sequence[Any], *, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Take documents out of the index. The files themselves are not touched."""
        wanted = {int(i) for i in (doc_ids or []) if str(i).isdigit()}
        gone = [d for d in self.documents(user_id) if d["id"] in wanted]
        if not gone:
            return []
        with self._lock:
            con = self._connect()
            try:
                con.executemany("DELETE FROM documents WHERE id=?", [(d["id"],) for d in gone])
                con.commit()
            finally:
                con.close()
        self._changed()
        for d in gone:
            self._ledger("REMOVE", d["path"], f"{d['passages']} passages removed", str(user_id or ""))
        return gone

    def refresh(self, folders: Sequence[Any] = (), *, user_id: str = "") -> int:
        """Pick up documents written into ELI's own folders, and ones that changed on disk."""
        queued = 0
        seen = set()
        for doc in self.documents(user_id):
            seen.add(doc["path"])
            try:
                p = Path(doc["path"])
                if p.is_file() and self._stale(doc["id"], p):
                    queued += int(self.note(p, user_id=user_id, source="changed"))
            except OSError:
                continue
        for folder in folders:
            try:
                found = sorted(Path(str(folder)).rglob("*"))[:2000]
            except OSError:
                continue
            for p in found:
                if str(p.resolve()) not in seen and indexable(p):
                    queued += int(self.note(p, user_id=user_id, source="folder"))
        return queued

    def refresh_once(self, folders: Sequence[Any] = ()) -> None:
        """The first time the app reaches for the index: pick up what changed while it was shut,
        on a thread of its own so nothing waits for the walk."""
        with self._lock:
            if self._refreshed:
                return
            self._refreshed = True

        def _walk():
            try:
                self.refresh(folders)
            except Exception:
                log.debug("document index: refresh failed", exc_info=True)

        threading.Thread(target=_walk, name="eli-document-refresh", daemon=True).start()

    def _stale(self, doc_id: int, p: Path) -> bool:
        con = self._connect()
        try:
            row = con.execute("SELECT size, mtime FROM documents WHERE id=?", (doc_id,)).fetchone()
        finally:
            con.close()
        stat = p.stat()
        return bool(row) and (int(row[0]) != int(stat.st_size) or abs(float(row[1]) - float(stat.st_mtime)) > 1.0)

    def _ledger(self, action: str, path: str, what: str, user_id: str) -> None:
        try:
            from eli.runtime.evidence_ledger import record_event
            record_event("document_index", source="document_index", action=action, subject=path,
                         content=what, user_id=user_id, reusable=False)
        except Exception:
            log.debug("document index: ledger write skipped", exc_info=True)


def format_passages(hits: Sequence[Dict[str, Any]], *, max_chars: int = 6000) -> str:
    """The block the model reads: the passages that fit, best first. Best first matters: the
    prompt is trimmed from the tail when it is too long, and in page order that cut took the
    passage that held the answer."""
    if not hits:
        return ""
    head = ("Passages from documents you have read (the documents' own words, found for this question, "
            "closest match first). Answer questions about those documents from these and name the document; "
            "if the passages do not cover it, say the part you have does not, not that the document doesn't.")
    lines: List[str] = []
    used = len(head)
    for h in hits:
        m = h.get("meta") if isinstance(h.get("meta"), dict) else h
        place = ", ".join(x for x in (str(m.get("where") or ""), f"part {m.get('part')} of {m.get('parts')}") if x)
        line = f"[{m.get('title') or 'document'} | {place}] " + " ".join(str(m.get("text") or "").split())
        if used + len(line) > max_chars:
            if lines:
                continue  # a shorter one further down may still fit
            line = line[:max(200, max_chars - used)]
        lines.append(line)
        used += len(line) + 1
    return head + "\n" + "\n".join(lines) if lines else ""


_indexes: Dict[str, DocumentIndex] = {}
_indexes_lock = threading.Lock()


def get_document_index() -> Optional[DocumentIndex]:
    """The index for this install, or None when switched off (ELI_DOCUMENT_INDEX=0)."""
    if os.environ.get("ELI_DOCUMENT_INDEX", "1").strip().lower() in ("0", "false", "off", "no"):
        return None
    try:
        from eli.core.paths import document_index_db_path
        key = str(document_index_db_path())
        with _indexes_lock:
            if key not in _indexes:
                _indexes[key] = DocumentIndex(key)
            return _indexes[key]
    except Exception:
        log.debug("document index unavailable", exc_info=True)
        return None


def note_document(path: Any, *, user_id: str = "", source: str = "") -> bool:
    """Queue a document for the index. Safe to call from anywhere; never raises."""
    try:
        index = get_document_index()
        return bool(index and path and index.note(path, user_id=user_id, source=source))
    except Exception:
        log.debug("document index: note skipped", exc_info=True)
        return False
