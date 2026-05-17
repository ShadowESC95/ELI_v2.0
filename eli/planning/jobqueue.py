from __future__ import annotations

import json
import sqlite3
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "artifacts" / "jobs"
DB_PATH = JOBS_DIR / "jobs.sqlite"

def _db() -> sqlite3.Connection:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_ts REAL NOT NULL,
        status TEXT NOT NULL,
        argv_json TEXT NOT NULL,
        cwd TEXT NOT NULL,
        timeout_s INTEGER NOT NULL,
        stdout_path TEXT NOT NULL,
        stderr_path TEXT NOT NULL,
        meta_json TEXT NOT NULL
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_ts);")
    return conn

def submit(argv: List[str], cwd: str=".", timeout_s: int=3600, meta: Optional[Dict[str,Any]]=None) -> int:
    conn = _db()
    ts = time.time()
    meta = meta or {}
    cur = conn.execute(
        "INSERT INTO jobs(created_ts,status,argv_json,cwd,timeout_s,stdout_path,stderr_path,meta_json) VALUES (?,?,?,?,?,?,?,?)",
        (ts, "queued", json.dumps(argv), str(Path(cwd).resolve()), int(timeout_s),
         "", "", json.dumps(meta))
    )
    jid = int(cur.lastrowid)

    stdout = JOBS_DIR / f"job_{jid}_stdout.txt"
    stderr = JOBS_DIR / f"job_{jid}_stderr.txt"
    stdout.write_text("", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")

    conn.execute(
        "UPDATE jobs SET stdout_path=?, stderr_path=? WHERE id=?",
        (str(stdout), str(stderr), jid)
    )
    conn.commit()
    conn.close()
    return jid

def list_jobs(limit: int=20, status: Optional[str]=None) -> List[Dict[str,Any]]:
    conn = _db()
    if status:
        rows = conn.execute(
            "SELECT id,created_ts,status,argv_json,cwd,timeout_s,stdout_path,stderr_path,meta_json FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id,created_ts,status,argv_json,cwd,timeout_s,stdout_path,stderr_path,meta_json FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    out=[]
    for r in rows:
        out.append({
            "id": r[0],
            "created_ts": r[1],
            "status": r[2],
            "argv": json.loads(r[3]),
            "cwd": r[4],
            "timeout_s": r[5],
            "stdout_path": r[6],
            "stderr_path": r[7],
            "meta": json.loads(r[8]),
        })
    return out

def get_job(jid: int) -> Optional[Dict[str,Any]]:
    conn = _db()
    r = conn.execute(
        "SELECT id,created_ts,status,argv_json,cwd,timeout_s,stdout_path,stderr_path,meta_json FROM jobs WHERE id=?",
        (jid,)
    ).fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r[0],
        "created_ts": r[1],
        "status": r[2],
        "argv": json.loads(r[3]),
        "cwd": r[4],
        "timeout_s": r[5],
        "stdout_path": r[6],
        "stderr_path": r[7],
        "meta": json.loads(r[8]),
    }

def _claim_next(conn: sqlite3.Connection) -> Optional[int]:
    r = conn.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY id ASC LIMIT 1").fetchone()
    if not r:
        return None
    jid = int(r[0])
    conn.execute("UPDATE jobs SET status='running' WHERE id=? AND status='queued'", (jid,))
    if conn.total_changes == 0:
        return None
    return jid

def run_worker(poll_s: float=0.5) -> None:
    while True:
        conn = _db()
        jid = _claim_next(conn)
        conn.commit()
        conn.close()

        if jid is None:
            time.sleep(poll_s)
            continue

        job = get_job(jid)
        if not job:
            continue

        stdout_p = Path(job["stdout_path"])
        stderr_p = Path(job["stderr_path"])

        try:
            r = subprocess.run(
                job["argv"],
                cwd=job["cwd"],
                text=True,
                capture_output=True,
                timeout=int(job["timeout_s"])
            )
            stdout_p.write_text(r.stdout or "", encoding="utf-8", errors="ignore")
            stderr_p.write_text(r.stderr or "", encoding="utf-8", errors="ignore")
            status = "done" if r.returncode == 0 else "failed"
            meta = job["meta"]
            meta.update({"returncode": r.returncode})
        except Exception as e:
            stderr_p.write_text(str(e), encoding="utf-8", errors="ignore")
            status = "failed"
            meta = job["meta"]
            meta.update({"error": str(e)})

        conn = _db()
        conn.execute("UPDATE jobs SET status=?, meta_json=? WHERE id=?", (status, json.dumps(meta), jid))
        conn.commit()
        conn.close()
