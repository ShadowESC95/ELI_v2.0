from __future__ import annotations

import json
import pickle
import sqlite3
from pathlib import Path
from typing import Any, Dict


def _project_root() -> Path:
    try:
        from eli.core.paths import project_root
        value = project_root() if callable(project_root) else project_root
        return Path(value).expanduser().resolve()
    except Exception:
        return Path(__file__).resolve().parents[2]


def _artifact_path(*parts: str) -> Path:
    root = _project_root()
    try:
        from eli.core import paths as _paths
        for fn_name in ("get_paths", "get_project_paths"):
            fn = getattr(_paths, fn_name, None)
            if callable(fn):
                obj = fn()
                val = getattr(obj, "artifacts_dir", None)
                if val:
                    return Path(val).expanduser().resolve().joinpath(*parts)
        val = getattr(_paths, "ARTIFACTS_DIR", None)
        if val:
            return Path(val).expanduser().resolve().joinpath(*parts)
    except Exception:
        pass
    return root.joinpath("artifacts", *parts)


def _count_table(cur: sqlite3.Cursor, table: str) -> int | None:
    try:
        safe = '"' + table.replace('"', '""') + '"'
        row = cur.execute(f"SELECT COUNT(*) FROM {safe}").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None


def inspect_sqlite(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "tables": [],
        "counts": {},
        "errors": [],
    }
    if not path.exists():
        return out

    try:
        con = sqlite3.connect(str(path))
        cur = con.cursor()
        tables = [
            str(r[0])
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        out["tables"] = tables
        for table in tables:
            out["counts"][table] = _count_table(cur, table)
        con.close()
    except Exception as exc:
        out["errors"].append(type(exc).__name__ + ": " + str(exc))
    return out


def inspect_vector_store() -> Dict[str, Any]:
    index_path = _artifact_path("vectors", "index.faiss")
    # Canonical metadata is JSON now; fall back to legacy pickle only if present.
    meta_path = _artifact_path("vectors", "meta.json")
    if not meta_path.exists():
        _legacy = _artifact_path("vectors", "meta.pkl")
        if _legacy.exists():
            meta_path = _legacy
    out: Dict[str, Any] = {
        "index_path": str(index_path),
        "index_exists": index_path.exists(),
        "index_size": index_path.stat().st_size if index_path.exists() else 0,
        "faiss_ntotal": None,
        "faiss_d": None,
        "meta_path": str(meta_path),
        "meta_exists": meta_path.exists(),
        "meta_size": meta_path.stat().st_size if meta_path.exists() else 0,
        "meta_type": None,
        "meta_len": None,
        "errors": [],
    }

    if index_path.exists():
        try:
            import faiss  # type: ignore
            index = faiss.read_index(str(index_path))
            out["faiss_ntotal"] = int(getattr(index, "ntotal", -1))
            out["faiss_d"] = int(getattr(index, "d", -1))
        except Exception as exc:
            out["errors"].append("faiss: " + type(exc).__name__ + ": " + str(exc))

    if meta_path.exists():
        try:
            if str(meta_path).endswith(".json"):
                import json as _json
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = _json.load(f)
            else:
                with meta_path.open("rb") as f:
                    meta = pickle.load(f)
            out["meta_type"] = type(meta).__name__
            try:
                out["meta_len"] = len(meta)
            except Exception:
                out["meta_len"] = None
        except Exception as exc:
            out["errors"].append("meta: " + type(exc).__name__ + ": " + str(exc))

    return out


def memory_truth_report() -> Dict[str, Any]:
    user_db = _artifact_path("db", "user.sqlite3")
    agent_db = _artifact_path("db", "agent.sqlite3")
    user = inspect_sqlite(user_db)
    agent = inspect_sqlite(agent_db)
    vectors = inspect_vector_store()

    user_counts = user.get("counts", {}) if isinstance(user.get("counts"), dict) else {}
    agent_counts = agent.get("counts", {}) if isinstance(agent.get("counts"), dict) else {}

    summary = {
        "user_memories": int(user_counts.get("memories") or 0),
        "user_memory_fts": int(user_counts.get("memories_fts") or 0),
        "user_conversation_turns": int(user_counts.get("conversation_turns") or 0),
        "user_conversations": int(user_counts.get("conversations") or 0),
        "user_observations": int(user_counts.get("observations") or 0),
        "user_recall_log": int(user_counts.get("recall_log") or 0),
        "agent_memories": int(agent_counts.get("memories") or 0),
        "agent_observations": int(agent_counts.get("observations") or 0),
        "vector_ntotal": vectors.get("faiss_ntotal"),
        "vector_dim": vectors.get("faiss_d"),
        "vector_meta_len": vectors.get("meta_len"),
    }

    return {
        "summary": summary,
        "databases": {
            "user": user,
            "agent": agent,
        },
        "vectors": vectors,
    }


def format_memory_truth(report: Dict[str, Any] | None = None) -> str:
    report = report or memory_truth_report()
    dbs = report.get("databases", {})
    vectors = report.get("vectors", {})
    errors = []
    for block in (dbs.get("user", {}), dbs.get("agent", {}), vectors):
        errors.extend(block.get("errors", []) if isinstance(block, dict) else [])
    payload = {
        "surface": "memory_truth_evidence",
        **report,
        "errors": errors,
    }
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)
