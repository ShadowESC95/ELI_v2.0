"""
Habit scheduler – runs in background and executes habit rules at the correct times.
"""

import time
import threading
import json
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
        self.running = True
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
                    # Execute the command
                    self._execute_rule(rule)

            time.sleep(30)  # check every 30 seconds

    def _execute_rule(self, rule: Dict):
        """Run a habit rule and record its execution."""
        try:
            command = rule['command']
        except (KeyError, TypeError):
            log.debug(f"[SCHEDULER] Skipping malformed rule (missing command): {rule!r}")
            return

        # Defense-in-depth: refuse to fire auto-corrupt rules whose command is a
        # bare action/capability token equal to the rule name (e.g. GET_WEATHER,
        # NEWS_FETCH, GENERATE_SCRIPT). Those are NOT learned time-routines — feeding
        # the token to engine.process() makes the router fall to fallback.chat and the
        # model role-plays/fabricates the action. Genuine learned rules are named
        # "Open <app> at HH:MM" (name != command). See memory.log_habit_event note.
        _name = str(rule.get("name") or "").strip()
        if command is not None and str(command).strip() == _name and _name:
            log.debug(f"[SCHEDULER] Skipping non-schedulable token rule '{_name}' "
                      f"(command == name; not a learned routine)")
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
