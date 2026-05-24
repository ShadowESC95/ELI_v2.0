from __future__ import annotations
import os, pickle, threading
from typing import Any, Dict, List, Optional


from eli.utils.log import get_logger
log = get_logger(__name__)

try:
    from eli.runtime.native_locks import FAISS_IO_LOCK, LLAMA_CPP_NATIVE_LOCK
except Exception:
    FAISS_IO_LOCK = threading.RLock()
    LLAMA_CPP_NATIVE_LOCK = threading.RLock()

try:
    import numpy as np
    import faiss
    FAISS_AVAILABLE = faiss.__class__.__name__ == "module"
except ImportError:
    FAISS_AVAILABLE = False

MAX_ENTRIES  = 50_000
SAVE_EVERY   = 50
EMBED_DIM    = 768

_store: Optional["VectorStore"] = None
_store_lock = threading.Lock()


def reset_vector_store() -> None:
    """Discard the singleton so the next call to get_vector_store() returns a fresh instance."""
    global _store
    with _store_lock:
        _store = None


def get_vector_store() -> Optional["VectorStore"]:
    global _store
    if _store is not None:
        return _store
    if not FAISS_AVAILABLE:
        log.debug("[VECTOR_STORE] faiss not installed — vector search disabled")
        return None
    with _store_lock:
        if _store is None:
            try:
                _store = VectorStore()
            except Exception as e:
                log.debug(f"[VECTOR_STORE] Init failed: {e}")
                return None
    return _store




class VectorStore:
    @property
    def ntotal(self) -> int:
        return int(getattr(getattr(self, "_index", None), "ntotal", 0) or 0)

    @property
    def index_path(self) -> str:
        return self._index_path

    @property
    def meta_path(self) -> str:
        return self._meta_path

    @property
    def meta_count(self) -> int:
        return len(self._meta)

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Separate lock for _embed serialisation. RLock keeps re-entrant
        # callers (e.g. add() -> _embed -> ... ) from self-deadlocking.
        self._embed_lock = threading.RLock()
        self._embedder: Any = None
        self._embedder_error: Optional[str] = None
        self._index: Any = None
        self._meta: List[Dict[str, Any]] = []
        self._adds_since_save = 0
        self._save_generation = 0
        self._needs_rebuild = False
        self._index_path, self._meta_path = _get_index_paths()
        self._load()
        self._init_embedder()
        # Check for divergence between loaded index and SQLite memories count.
        # If >20% of memories are missing from FAISS, schedule a rebuild so
        # semantic search is accurate even after unclean shutdowns.
        if not self._needs_rebuild:
            try:
                import sqlite3 as _sq
                from eli.core.paths import user_db_path as _udb
                _db = str(_udb())
                if _db and os.path.exists(_db):
                    _con = _sq.connect(_db)
                    try:
                        _sqlite_count = _con.execute(
                            "SELECT COUNT(*) FROM memories "
                            "WHERE length(COALESCE(text, content, '')) > 10"
                        ).fetchone()[0]
                    except Exception:
                        _sqlite_count = 0
                    finally:
                        _con.close()
                    _vec_count = self._index.ntotal if self._index is not None else 0
                    if _sqlite_count > 0 and _vec_count < _sqlite_count * 0.8:
                        log.debug(
                            f"[VECTOR_STORE] Index divergence detected: "
                            f"{_vec_count} vectors vs {_sqlite_count} DB memories — scheduling rebuild"
                        )
                        self._needs_rebuild = True
            except Exception:
                pass
        if self._needs_rebuild and self._embedder is not None:
            threading.Thread(target=self._auto_rebuild, daemon=True, name="eli-vs-rebuild").start()

    def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        # === PHASE43_SKIP_VECTOR_EMBED_DURING_SHUTDOWN ===
        try:
            if os.environ.get('ELI_SHUTTING_DOWN') == '1':
                log.debug('[VECTOR_STORE][PHASE43] skipping embedding during shutdown')
                return False
        except Exception:
            pass
        # === END PHASE43_SKIP_VECTOR_EMBED_DURING_SHUTDOWN ===
        vec = self._embed(text)
        if vec is None:
            return False
        with self._lock:
            self._index.add(vec)
            self._meta.append({"text": text, **(metadata or {})})
            self._adds_since_save += 1
            if len(self._meta) > MAX_ENTRIES:
                self._prune()
            if self._adds_since_save >= SAVE_EVERY:
                self._save_async()
        return True

    def search(self, query: str, top_k: int = 5, limit: int | None = None, k: int | None = None) -> List[Dict[str, Any]]:
        vec = self._embed(query)
        if limit is not None:
            top_k = int(limit)
        if k is not None:
            top_k = int(k)
        if vec is None:
            return self._keyword_fallback(query, top_k)
        with self._lock:
            if self._index.ntotal == 0:
                return []
            k = min(top_k, self._index.ntotal)
            distances, indices = self._index.search(vec, k)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self._meta):
                continue
            score = float(1.0 / (1.0 + dist))
            entry = dict(self._meta[idx])
            entry["score"] = score
            results.append(entry)
        return results

    def _get_embedder(self):
        if self._embedder is None:
            self._init_embedder()
        return self._embedder

    def _init_embedder(self) -> None:
        try:
            import os
            from pathlib import Path
            from llama_cpp import Llama
            _root = Path(__file__).resolve().parents[2]
            _models_dir = Path(os.getenv('ELI_MODELS_DIR', str(_root / 'models')))
            env_embed = os.getenv('ELI_EMBED_MODEL_PATH', '').strip()
            if env_embed:
                _model_path = str(Path(env_embed).expanduser().resolve())
            else:
                _project_root = Path(os.getenv('ELI_PROJECT_ROOT', str(_root))).expanduser().resolve()
                _model_path = str((_project_root / 'models' / 'embeddings' / 'nomic-embed-text-v1.5.Q4_K_M.gguf').resolve())
            if not os.path.exists(_model_path):
                raise FileNotFoundError('Embed model not found: ' + _model_path)
            _llm = Llama(
                model_path=_model_path,
                embedding=True,
                n_ctx=2048,
                n_gpu_layers=0,
                verbose=False,
                n_threads=4,
            )
            class _EmbedShim:
                def __init__(self, llm): self._llm = llm
                def _get_llm(self): return self._llm
                def get_llm(self): return self._llm
                def embed(self, text):
                    pfx = '' if text.startswith(('search_query:', 'search_document:', 'classification:', 'clustering:')) else 'search_query: '
                    r = self._llm.create_embedding(pfx + text)
                    return r['data'][0]['embedding']
            self._embedder = _EmbedShim(_llm)
            log.debug('[VECTOR_STORE] Embedder ready (nomic-embed-text-v1.5.Q4_K_M.gguf)')
        except Exception as e:
            self._embedder_error = str(e)
            log.debug('[VECTOR_STORE] Embedder unavailable, keyword fallback: ' + str(e))

    def _auto_rebuild(self) -> None:
        """Background rebuild triggered on startup when saved index is empty but DB has memories."""
        import sqlite3 as _sq
        try:
            from eli.core.paths import user_db_path
            db_path = str(user_db_path())
        except Exception:
            return
        try:
            con = _sq.connect(db_path)
            try:
                raw = con.execute(
                    "SELECT COALESCE(text, content, ''), COALESCE(source,'user'), "
                    "COALESCE(tags,''), COALESCE(kind,'memory'), id "
                    "FROM memories "
                    "WHERE length(COALESCE(text, content, '')) > 10 "
                    "ORDER BY id"
                ).fetchall()
            finally:
                con.close()
        except Exception as e:
            log.debug(f"[VECTOR_STORE] Auto-rebuild DB read failed: {e}")
            return
        if not raw:
            return
        entries = [
            {"text": row[0].strip(), "source": row[1], "tags": row[2], "kind": row[3], "id": row[4]}
            for row in raw if row[0].strip()
        ]
        log.debug(f"[VECTOR_STORE] Auto-rebuilding index from {len(entries)} memories…")
        self.rebuild_full(entries)
        log.debug(f"[VECTOR_STORE] Auto-rebuild complete: {self.ntotal} vectors")

    def _embed(self, text: str) -> Optional[Any]:
        if self._embedder is None:
            return None
        # Serialise embed calls; llama-cpp embedding models are not
        # thread-safe and concurrent calls can corrupt embedder state.
        with self._embed_lock, LLAMA_CPP_NATIVE_LOCK:
            try:
                vec = self._embedder.embed(text)
                arr = np.array(vec, dtype="float32").reshape(1, -1)
                faiss.normalize_L2(arr)
                return arr
            except Exception as e:
                log.debug(f"[VECTOR_STORE] embed failed: {e}")
                return None

    def _keyword_fallback(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        terms = query.lower().split()
        scored = []
        with self._lock:
            entries = list(self._meta)
        for entry in entries:
            text = (entry.get("text") or "").lower()
            hit_count = sum(1 for t in terms if t in text)
            if hit_count:
                scored.append((hit_count, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**e, "score": hits / max(len(terms), 1)}
            for hits, e in scored[:top_k]
        ]

    def _load(self) -> None:
        if os.path.exists(self._index_path) and os.path.exists(self._meta_path):
            try:
                self._index = faiss.read_index(self._index_path)
                with open(self._meta_path, "rb") as f:
                    self._meta = pickle.load(f)
                loaded = self._index.ntotal
                log.debug(f"[VECTOR_STORE] Loaded {loaded} vectors")
                if loaded == 0:
                    # Saved index is empty — schedule a background rebuild after embedder init
                    self._needs_rebuild = True
                return
            except Exception as e:
                log.debug(f"[VECTOR_STORE] Load failed, starting fresh: {e}")
        self._index = faiss.IndexFlatL2(EMBED_DIM)
        self._meta = []
        self._needs_rebuild = True

    def _save_async(self) -> None:
        with self._lock, FAISS_IO_LOCK:
            self._save_generation += 1
            generation = self._save_generation
            idx_snapshot = faiss.clone_index(self._index)
            meta_snapshot = list(self._meta)
            self._adds_since_save = 0
        def _write():
            try:
                with FAISS_IO_LOCK:
                    with self._lock:
                        if generation != self._save_generation:
                            return
                    faiss.write_index(idx_snapshot, self._index_path)
                    with open(self._meta_path, "wb") as f:
                        pickle.dump(meta_snapshot, f)
            except Exception as e:
                log.debug(f"[VECTOR_STORE] Background save failed: {e}")
        threading.Thread(target=_write, daemon=True, name="eli-vs-save").start()

    def _prune(self) -> None:
        keep = self._meta[-MAX_ENTRIES:]
        new_index = faiss.IndexFlatL2(EMBED_DIM)
        texts = [entry.get("text", "") for entry in keep]
        # Embed outside the lock to avoid holding it during inference
        vecs = []
        for t in texts:
            vecs.append(self._embed(t))
        for entry, vec in zip(keep, vecs):
            if vec is not None:
                new_index.add(vec)
        self._index = new_index
        self._meta = keep
        log.debug(f"[VECTOR_STORE] Pruned to {MAX_ENTRIES} entries")

    def flush(self) -> None:
        """Force-save index and metadata to disk."""
        with self._lock, FAISS_IO_LOCK:
            try:
                self._save_generation += 1
                faiss.write_index(self._index, self._index_path)
                with open(self._meta_path, "wb") as f:
                    pickle.dump(self._meta, f)
                self._adds_since_save = 0
            except Exception as e:
                log.debug(f"[VECTOR_STORE] flush failed: {e}")

    def rebuild_full(self, texts_and_meta: List[Dict[str, Any]]) -> None:
        """Rebuild the entire FAISS index from a list of {text, ...metadata} dicts."""
        new_index = faiss.IndexFlatL2(EMBED_DIM)
        new_meta: List[Dict[str, Any]] = []
        for entry in texts_and_meta:
            text = entry.get("text", "")
            vec = self._embed(text)
            if vec is not None:
                new_index.add(vec)
                new_meta.append(entry)
        with self._lock:
            self._index = new_index
            self._meta = new_meta
            self._adds_since_save = 0
        self.flush()
        log.debug(f"[VECTOR_STORE] Rebuilt index with {new_index.ntotal} vectors")




def _get_index_paths() -> tuple:
    """
    Resolve FAISS artifacts into the canonical project-local vector dir.

    Expected files:
    - artifacts/vectors/index.faiss
    - artifacts/vectors/meta.pkl
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    vdir = root / "artifacts" / "vectors"
    vdir.mkdir(parents=True, exist_ok=True)
    return str((vdir / "index.faiss").resolve()), str((vdir / "meta.pkl").resolve())
