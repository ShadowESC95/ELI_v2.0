#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eli.execution.router_enhanced import route
from eli.memory import get_memory
from eli.runtime.profile_extractor import backfill_user_patterns


COMMAND_ACTIONS = {
    "OPEN_APP",
    "CLOSE_APP",
    "OPEN_FILE_SYSTEM",
    "LIST_DIR",
    "READ_FILE",
    "SCREENSHOT",
    "SCREEN_READ_ANALYZE",
    "OCR_IMAGE",
    "GET_WEATHER",
    "TIME",
    "DATE",
    "SET_TIMER",
    "SET_ALARM",
    "VOLUME",
    "PLAY_MEDIA",
    "PAUSE_MEDIA",
    "STOP_MEDIA",
    "NEXT_MEDIA",
    "PREVIOUS_MEDIA",
    "MEDIA_CONTROL",
    "CREATE_DOCUMENT",
    "GENERATE_DOCUMENT",
    "GENERATE_SCRIPT",
    "CREATE_SCRIPT",
    "WRITE_SCRIPT",
    "LIST_CAPABILITIES",
    "PROACTIVE_STATUS",
    "HABIT_STATUS",
}


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _existing_source_turn_ids(db_path: Path) -> set[int]:
    out: set[int] = set()
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT details, data FROM habit_events").fetchall()
        except sqlite3.Error:
            return out
    for row in rows:
        payload = _json_loads(row["details"]) or _json_loads(row["data"])
        try:
            sid = int(payload.get("source_turn_id"))
            out.add(sid)
        except Exception:
            pass
    return out


def _iter_user_turns(db_path: Path, limit: int):
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, role, content, COALESCE(timestamp, ts, id) AS sort_ts
            FROM conversation_turns
            WHERE lower(COALESCE(role, '')) = 'user'
            ORDER BY COALESCE(timestamp, ts, id) DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return list(reversed(rows))


def backfill_command_habits(limit: int = 800) -> dict[str, Any]:
    mem = get_memory()
    db_path = Path(getattr(mem, "db_path"))
    existing = _existing_source_turn_ids(db_path)
    scanned = 0
    inserted = 0
    app_launches = 0

    for row in _iter_user_turns(db_path, limit):
        scanned += 1
        turn_id = int(row["id"])
        if turn_id in existing:
            continue
        text = str(row["content"] or "").strip()
        if not text:
            continue
        try:
            routed = route(text) or {}
        except Exception:
            continue
        action = str(routed.get("action") or "").upper()
        if action not in COMMAND_ACTIONS:
            continue
        args = routed.get("args") or {}
        meta = routed.get("meta") or {}
        payload = {
            "action": action,
            "args": args,
            "matched_by": meta.get("matched_by"),
            "source": "backfill_learning_tracking",
            "source_turn_id": turn_id,
            "text": text[:500],
        }
        mem.log_habit_event("command_result", payload)
        mem.log_learning_event(
            "command_result",
            input_text=text,
            action=action,
            outcome="observed",
            metadata=payload,
            timestamp=float(row["sort_ts"] or time.time()),
        )
        inserted += 1

        if action == "OPEN_APP":
            app = str(args.get("name") or args.get("target") or args.get("app") or "").strip()
            if app:
                cmd = str(args.get("cmd") or args.get("command") or app).strip()
                mem.store_app_cmd(app, cmd, method="backfill_learning_tracking")
                mem.log_habit_event(
                    "app_launch",
                    {
                        "app": app,
                        "cmd": cmd,
                        "method": "backfill_learning_tracking",
                        "success": True,
                        "source_turn_id": turn_id,
                    },
                )
                app_launches += 1

    return {
        "db": str(db_path),
        "scanned_user_turns": scanned,
        "command_events_inserted": inserted,
        "app_launches_inserted": app_launches,
    }


def rebuild_habit_summaries_from_events() -> dict[str, Any]:
    mem = get_memory()
    db_path = Path(getattr(mem, "db_path"))
    now = time.time()
    action_counts: dict[str, int] = {}
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT details, data FROM habit_events WHERE event_type = 'command_result'"
            ).fetchall()
        except sqlite3.Error:
            return {"db": str(db_path), "actions_indexed": 0}

        for row in rows:
            payload = _json_loads(row["details"]) or _json_loads(row["data"])
            action = str(payload.get("action") or "").upper().strip()
            if action and action not in {"CHAT", "NOOP"}:
                action_counts[action] = action_counts.get(action, 0) + 1

        for action, count in action_counts.items():
            row = conn.execute(
                "SELECT id, COALESCE(count, 0) FROM habits WHERE COALESCE(name, '') = ?",
                (action,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE habits SET count = MAX(COALESCE(count, 0), ?), timestamp = ?, ts = ?, command = ?, cmd = ?, method = ? WHERE id = ?",
                    (count, now, now, action, action, "command_result_summary", int(row["id"])),
                )
            else:
                conn.execute(
                    "INSERT INTO habits (name, command, cmd, method, count, timestamp, ts, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                    (action, action, action, "command_result_summary", count, now, now),
                )
            rule = conn.execute(
                "SELECT id FROM habit_rules WHERE COALESCE(name, '') = ?",
                (action,),
            ).fetchone()
            if rule is None:
                conn.execute(
                    "INSERT INTO habit_rules (name, command, enabled, timestamp, ts, pattern, action, trigger_phrase, action_type) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)",
                    (action, action, now, now, action, action, action, "command_result_summary"),
                )
        conn.commit()

    return {
        "db": str(db_path),
        "actions_indexed": len(action_counts),
        "actions": action_counts,
    }


def main() -> int:
    profile = backfill_user_patterns(limit=2500)
    habits = backfill_command_habits(limit=800)
    summaries = rebuild_habit_summaries_from_events()
    print(json.dumps({"profile": profile, "habits": habits, "summaries": summaries}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
