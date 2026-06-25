"""
Conversation log rotation for ELI.

Problems this solves:
  1. JSONL files grow unbounded (96MB in 4 days observed)
  2. datetime.utcnow() is deprecated in Python 3.12+, removed in 3.13
  3. No archival or size-based rotation

Policy:
  - Max file size: 50MB per daily JSONL (configurable via ELI_CONVLOG_MAX_MB)
  - Retention: 30 days of daily files (configurable via ELI_CONVLOG_RETAIN_DAYS)
  - Archives: files older than retain_days are gzip-compressed into convlog_archive/
  - On size limit: current day's file is rotated with timestamp suffix

Usage (drop-in replacement for the logging functions in executor_enhanced.py):

    from eli.perception.log_rotation import convlog_append, convlog_rotate_old

    # Replace _convlog_append() calls with convlog_append()
    convlog_append("user", "Hello ELI")
    convlog_append("assistant", "Hello")

    # Call once at startup to compress old files
    convlog_rotate_old()
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Config ────────────────────────────────────────────────────

def _max_bytes() -> int:
    mb = int(os.environ.get("ELI_CONVLOG_MAX_MB", "50"))
    return mb * 1024 * 1024


def _retain_days() -> int:
    return int(os.environ.get("ELI_CONVLOG_RETAIN_DAYS", "30"))


# ── Path helpers ──────────────────────────────────────────────

def _conversations_dir() -> Optional[Path]:
    # Single source of truth for the conversation-log directory so writers and
    # readers (e.g. learning/dataset_builder) never diverge across install
    # layouts. Falls back to the artifacts_dir computation if the helper is
    # unavailable (both resolve to data_dir()/conversations).
    try:
        from eli.core.paths import conversations_dir
        d = conversations_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        try:
            from eli.core.paths import get_paths
            d = Path(get_paths().artifacts_dir) / "conversations"
            d.mkdir(parents=True, exist_ok=True)
            return d
        except Exception:
            return None


def _archive_dir() -> Optional[Path]:
    d = _conversations_dir()
    if d is None:
        return None
    a = d / "archive"
    a.mkdir(parents=True, exist_ok=True)
    return a


def _today_path() -> Optional[Path]:
    d = _conversations_dir()
    if d is None:
        return None
    fn = datetime.now(tz=timezone.utc).strftime("%Y%m%d") + ".jsonl"
    return d / fn


# ── Core write function (replaces _convlog_append) ────────────

def convlog_append(role: str, text: str, meta: Optional[dict] = None) -> None:
    """
    Append a conversation turn to today's JSONL log.
    - Thread-safe via file append (atomic on Linux)
    - Rotates today's file if it exceeds ELI_CONVLOG_MAX_MB
    - Uses timezone-aware UTC timestamps (no deprecation warning)
    """
    path = _today_path()
    if path is None:
        return

    try:
        # Rotate if too large
        if path.exists() and path.stat().st_size >= _max_bytes():
            _rotate_current(path)

        now = datetime.now(tz=timezone.utc)
        rec = {
            "ts_iso": now.strftime("%Y-%m-%d %H:%M:%S"),
            "ts_unix": now.timestamp(),
            "role": str(role),
            "text": str(text),
            "meta": meta or {},
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Never crash ELI on logging failure


def _rotate_current(path: Path) -> None:
    """Rename current log to a timestamped file to start fresh."""
    try:
        now = datetime.now(tz=timezone.utc)
        suffix = now.strftime("%H%M%S")
        stem = path.stem  # e.g. "20260311"
        rotated = path.parent / f"{stem}_{suffix}.jsonl"
        path.rename(rotated)
    except Exception:
        pass


# ── Archival (call at startup) ────────────────────────────────

def convlog_rotate_old(dry_run: bool = False) -> dict:
    """
    Compress and archive JSONL files older than retain_days.
    Call once at startup:

        from eli.perception.log_rotation import convlog_rotate_old
        convlog_rotate_old()

    Returns summary dict: {"archived": [...], "deleted": [...], "errors": [...]}
    """
    conv_dir = _conversations_dir()
    archive = _archive_dir()
    if conv_dir is None or archive is None:
        return {"archived": [], "deleted": [], "errors": ["conversations dir not found"]}

    retain = _retain_days()
    now = datetime.now(tz=timezone.utc)
    archived = []
    deleted = []
    errors = []

    for f in sorted(conv_dir.glob("*.jsonl")):
        if f.name.startswith("archive"):
            continue

        # Parse date from filename (YYYYMMDD or YYYYMMDD_HHMMSS)
        date_part = f.stem[:8]
        try:
            file_date = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        age_days = (now - file_date).days

        # Skip today
        if age_days == 0:
            continue

        # Compress if older than retain_days
        if age_days > retain:
            gz_path = archive / (f.name + ".gz")
            if not dry_run:
                try:
                    with open(f, "rb") as src, gzip.open(gz_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    f.unlink()
                    deleted.append(str(f))
                except Exception as e:
                    errors.append(f"{f.name}: {e}")
            else:
                deleted.append(str(f))

        # Compress if within retain window but uncompressed
        elif age_days >= 1:
            gz_path = archive / (f.name + ".gz")
            if not gz_path.exists() and not dry_run:
                try:
                    with open(f, "rb") as src, gzip.open(gz_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    f.unlink()
                    archived.append(str(f))
                except Exception as e:
                    errors.append(f"{f.name}: {e}")
            elif not gz_path.exists():
                archived.append(str(f))

    return {"archived": archived, "deleted": deleted, "errors": errors}


def convlog_stats() -> dict:
    """Return statistics about conversation log files."""
    conv_dir = _conversations_dir()
    if conv_dir is None:
        return {"error": "conversations dir not found"}

    files = []
    total_bytes = 0

    for f in sorted(conv_dir.glob("*.jsonl")):
        size = f.stat().st_size
        total_bytes += size
        files.append({"name": f.name, "size_mb": round(size / 1024 / 1024, 2)})

    archive = _archive_dir()
    archive_count = len(list(archive.glob("*.gz"))) if archive else 0

    return {
        "files": files,
        "total_mb": round(total_bytes / 1024 / 1024, 2),
        "archive_count": archive_count,
        "max_mb_per_file": _max_bytes() // (1024 * 1024),
        "retain_days": _retain_days(),
    }
