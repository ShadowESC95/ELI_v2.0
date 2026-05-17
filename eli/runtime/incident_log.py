from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

def _root() -> Path:
    # parents[2] resolves to the project root for files at eli/<pkg>/<file>.py
    return Path(__file__).resolve().parents[2]

def write_incident(payload: dict) -> str:
    try:
        from eli.core.paths import data_dir as _data_dir
        outdir = _data_dir() / "incidents"
    except Exception:
        outdir = _root() / "artifacts" / "incidents"
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{datetime.now(timezone.utc):%Y%m%d}.jsonl"
    record = {"ts": datetime.now(timezone.utc).isoformat(), **(payload or {})}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return str(path)
