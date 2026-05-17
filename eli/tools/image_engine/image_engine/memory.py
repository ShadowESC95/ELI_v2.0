from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .contracts import utc_now


class ImageMemory:
    """Small SQLite memory/index for generated images, plots, and jobs."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    project TEXT,
                    prompt TEXT,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    prompt TEXT,
                    project TEXT,
                    tags TEXT,
                    score REAL,
                    metadata_json TEXT,
                    hash TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(job_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
                CREATE INDEX IF NOT EXISTS idx_artifacts_score ON artifacts(score);
                CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at);
                """
            )

    def create_job(self, job_id: str, task: str, request: dict[str, Any], project: str = "", prompt: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs
                    (job_id, task, status, project, prompt, request_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, task, "running", project, prompt, json.dumps(request, ensure_ascii=False), utc_now()),
            )

    def finish_job(self, job_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, result_json=?, finished_at=? WHERE job_id=?",
                (status, json.dumps(result or {}, ensure_ascii=False), utc_now(), job_id),
            )

    def add_artifact(
        self,
        job_id: str,
        artifact_type: str,
        path: str | Path,
        *,
        prompt: str = "",
        project: str = "",
        tags: list[str] | None = None,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
        artifact_hash: str = "",
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO artifacts
                    (job_id, artifact_type, path, prompt, project, tags, score, metadata_json, hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    artifact_type,
                    str(path),
                    prompt,
                    project,
                    " ".join(tags or []),
                    score,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    artifact_hash,
                    utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def search(
        self,
        query: str = "",
        *,
        artifact_type: str = "",
        project: str = "",
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        clauses: list[str] = []
        params: list[Any] = []

        if artifact_type:
            clauses.append("artifact_type = ?")
            params.append(artifact_type)
        if project:
            clauses.append("project LIKE ?")
            params.append(f"%{project}%")
        if query:
            q = f"%{query}%"
            clauses.append("(prompt LIKE ? OR tags LIKE ? OR path LIKE ? OR metadata_json LIKE ?)")
            params.extend([q, q, q, q])

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT *
            FROM artifacts
            {where}
            ORDER BY COALESCE(score, 0) DESC, created_at DESC
            LIMIT ?
        """
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._row_to_artifact(row) for row in rows]

    def list_jobs(self, limit: int = 25) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            data["metadata"] = {}
        return data
