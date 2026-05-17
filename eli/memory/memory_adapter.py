from __future__ import annotations
import sqlite3, threading, time
from typing import Any, Dict, List, Optional

__all__ = ["MemoryAdapter", "get_memory_adapter"]

_adapter: Optional["MemoryAdapter"] = None
_adapter_lock = threading.Lock()


def get_memory_adapter() -> "MemoryAdapter":
    global _adapter
    if _adapter is not None:
        return _adapter
    with _adapter_lock:
        if _adapter is None:
            from eli.memory.memory import get_memory
            _adapter = MemoryAdapter(get_memory())
    return _adapter


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return dict(row)
    keys = ["id", "ts", "kind", "text", "tags", "source", "confidence"]
    try:
        return dict(zip(keys, row))
    except Exception:
        return {"text": str(row)}


class MemoryAdapter:
    def __init__(self, mem: Any) -> None:
        self._mem = mem
        self._lock = threading.Lock()

    def recall_memory(self, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        try:
            raw = self._mem.recall_memory(query, limit=limit) or []
            return [_row_to_dict(r) for r in raw]
        except Exception as e:
            print(f"[MEMORY_ADAPTER] recall_memory failed: {e}")
            return []

    def store_memory(self, text: str, tags: Optional[List[str]] = None,
                     kind: str = "note", source: str = "user",
                     confidence: float = 0.8) -> bool:
        with self._lock:
            try:
                result = self._mem.store_memory(text=text, tags=tags or [],
                                                source=source, kind=kind,
                                                confidence=confidence)
                ok = result.get("ok", False) if isinstance(result, dict) else bool(result)
            except Exception as e:
                print(f"[MEMORY_ADAPTER] store_memory failed: {e}")
                return False
        if ok:
            try:
                from eli.memory.vector_store import get_vector_store
                vs = get_vector_store()
                if vs is not None:
                    vs.add(text, metadata={"tags": ",".join(tags or []), "source": source})
            except Exception as ve:
                print(f"[MEMORY_ADAPTER] vector index failed (non-fatal): {ve}")
        return ok

    def add_conversation_turn(self, role: str, content: str,
                               session_id: str = "", user_id: str = "") -> None:
        with self._lock:
            for attempt in range(5):
                try:
                    self._mem.add_conversation_turn(role, content, session_id, user_id)
                    return
                except sqlite3.OperationalError as e:
                    if attempt < 4:
                        time.sleep(0.05 * (2 ** attempt))
                    else:
                        print(f"[MEMORY_ADAPTER] add_conversation_turn gave up: {e}")
                except Exception as e:
                    print(f"[MEMORY_ADAPTER] add_conversation_turn failed: {e}")
                    return

    def get_memory_status(self) -> Dict[str, Any]:
        try:
            if hasattr(self._mem, "get_memory_status"):
                return self._mem.get_memory_status()
            db_path = (getattr(self._mem, "db_path", None)
                       or getattr(self._mem, "dbpath", None))
            if not db_path:
                return {"conversation_turns": 0, "memory_entries": 0,
                        "distinct_sessions": 0}
            conn = sqlite3.connect(str(db_path))
            try:
                t = conn.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()
                m = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                s = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) FROM conversation_turns"
                ).fetchone()
                return {"conversation_turns": t[0] if t else 0,
                        "memory_entries": m[0] if m else 0,
                        "distinct_sessions": s[0] if s else 0,
                        "db_path": str(db_path)}
            finally:
                conn.close()
        except Exception as e:
            print(f"[MEMORY_ADAPTER] get_memory_status failed: {e}")
            return {"conversation_turns": 0, "memory_entries": 0,
                    "distinct_sessions": 0, "error": str(e)}

    def add_observation(self, source: str, content: str) -> None:
        try:
            self._mem.add_observation(source, content)
        except Exception as e:
            print(f"[MEMORY_ADAPTER] add_observation failed: {e}")

    def get_recent_observations(self, limit: int = 8) -> List[Dict[str, Any]]:
        try:
            raw = self._mem.get_recent_observations(limit=limit) or []
            return [_row_to_dict(r) for r in raw]
        except Exception as e:
            print(f"[MEMORY_ADAPTER] get_recent_observations failed: {e}")
            return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mem, name)
