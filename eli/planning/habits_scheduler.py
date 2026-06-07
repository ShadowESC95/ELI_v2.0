"""
Habit scheduler – runs in background and executes habit rules at the correct times.
"""

import time
import threading
import json
import re
import sqlite3  # added to catch OperationalError
from datetime import datetime, timedelta
from typing import List, Dict
from eli.memory import get_memory
from eli.execution.executor_enhanced import execute


from eli.utils.log import get_logger
log = get_logger(__name__)

class HabitScheduler:
    def __init__(self):
        self.memory = get_memory()
        # Self-heal legacy corruption: disable enabled-but-un-schedulable rules
        # (NULL time, or bare-token command == name) so they stop appearing as
        # "active habits at 00:00". Non-destructive; idempotent across boots.
        try:
            _n = self.memory.disable_invalid_habit_rules()
            if _n:
                log.info(f"[SCHEDULER] Disabled {_n} invalid/legacy habit rule(s) "
                         f"(no valid scheduled time or bare-token command)")
        except Exception as e:
            log.debug(f"[SCHEDULER] habit self-heal skipped: {e}")
        self.running = True
        self._fired_keys: set = set()  # (rule_id, YYYYMMDDHHMM) — fire once per minute
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        """Main loop: check every 30 seconds for rules that should run now."""
        while self.running:
            now = datetime.now()
            current_hour = now.hour
            current_minute = now.minute

            try:
                rules = self.memory.get_habit_rules(enabled_only=True)
            except sqlite3.OperationalError as e:
                if "no such table" in str(e):
                    rules = []  # table not created yet – skip gracefully
                else:
                    raise

            for rule in rules:
                try:
                    rule_hour = rule['hour']
                    rule_minute = rule['minute']
                except (KeyError, TypeError):
                    log.debug(f"[SCHEDULER] Skipping malformed rule (missing hour/minute): {rule!r}")
                    continue
                if rule_hour == current_hour and rule_minute == current_minute:
                    # Check day‑of‑week if specified
                    days = rule.get('days')
                    if days is not None:
                        if now.weekday() not in days:
                            continue
                    # Fire ONCE per scheduled minute — the loop ticks every 30s,
                    # so without this an active habit would launch twice.
                    _key = (rule.get('id'), now.strftime("%Y%m%d%H%M"))
                    if _key in self._fired_keys:
                        continue
                    self._fired_keys.add(_key)
                    # Execute the command
                    self._execute_rule(rule)

            # Keep the dedupe set small (drop entries older than this minute).
            if len(self._fired_keys) > 256:
                _stamp = now.strftime("%Y%m%d%H%M")
                self._fired_keys = {k for k in self._fired_keys if k[1] == _stamp}

            time.sleep(30)  # check every 30 seconds

    def _execute_rule(self, rule: Dict):
        """Run a habit rule and record its execution."""
        try:
            command = rule['command']
        except (KeyError, TypeError):
            log.debug(f"[SCHEDULER] Skipping malformed rule (missing command): {rule!r}")
            return

        # Defense-in-depth: refuse to fire corrupt rules whose command is a bare
        # ACTION/CAPABILITY token (e.g. GET_WEATHER, NEWS_FETCH, GENERATE_SCRIPT).
        # Feeding such a token to engine.process() makes the router fall to
        # fallback.chat and the model role-plays/fabricates the action.
        # IMPORTANT: this must NOT block a legitimate "launch app" habit where the
        # user named it after the app (name "firefox", command "firefox"). So only
        # skip when the command is an ALL-CAPS action token — a plain app name or
        # natural phrase is a real routine and must run.
        _cmd = str(command).strip()
        if _cmd and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", _cmd):
            log.debug(f"[SCHEDULER] Skipping bare ACTION-token rule "
                      f"'{rule.get('name','?')}' (command={_cmd!r} is not a routine)")
            return

        log.debug(f"[SCHEDULER] Executing habit '{rule.get('name', '?')}': {command}")

        # Try to parse as a natural language command – use cognitive engine
        try:
            from eli.kernel.engine import get_engine
            engine = get_engine()
            result = engine.process(command, source="habit")
            if isinstance(result, dict):
                _ok = bool(result.get("ok"))
                _content = str(
                    result.get("content")
                    or result.get("response")
                    or result.get("message")
                    or result.get("text")
                    or ""
                )
                _error = str(result.get("error") or "Unknown error")
            else:
                _content = str(result or "")
                _ok = bool(_content.strip())
                _error = "No structured result returned"

            if _ok:
                print(f"   ✅ Success: {_content[:60]}")
            else:
                print(f"   ❌ Failed: {_error}")
        except Exception as e:
            print(f"   ❌ Error: {e}")

        self.memory.record_habit_run(rule['id'])

    def stop(self):
        self.running = False

# Global scheduler instance
_scheduler = None
def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = HabitScheduler()
    return _scheduler
