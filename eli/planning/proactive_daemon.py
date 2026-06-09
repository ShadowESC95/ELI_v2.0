#!/usr/bin/env python3
"""
ELI Proactive Daemon - Self-Improvement & Intelligence System
==============================================================

Option B (TWO DBs):
- Reads user-facing memories/conversations from USER DB
- Writes proactive observations/improvements/errors to AGENT DB
"""

import os
import re
import sys
import time
import subprocess
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import threading
import queue
from eli.core.paths import get_paths
from eli.runtime.self_model_refresh import refresh_all_overlays_nonfatal
from eli.planning.proposal_memory_bridge import drain_proposals_to_agent_memory

# IMPORTANT: don't force sys.path unless you're running this file directly.
# In normal package use, PYTHONPATH/src handles it.
if __name__ == "__main__":
    # Add the parent of the package root so `import eli` works in both flat and src layouts.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eli.memory import (
    get_memory,
    get_agent_memory,
    resolve_db_paths,
)

from eli.utils.log import get_logger
log = get_logger(__name__)

class ProactiveDaemon:
    """
    Self-improving proactive intelligence daemon
    - READS: user DB
    - WRITES: agent DB
    """

    def __init__(self):
        self.paths = get_paths()
        self.project_root = self.paths.project_root
        self.package_root = Path(__file__).resolve().parents[2]
        self.running = False
        self.paused = False
        self.suggestion_queue = queue.Queue()

        # Two DB handles
        self.user_mem = get_memory()
        self.agent_mem = get_agent_memory()

        # Keep db_path attribute for legacy code paths that still use sqlite3 directly
        # (but this should always refer to AGENT DB in Option B)
        self.db_path = Path(self.agent_mem.db_path)

        log.debug("[PROACTIVE] Daemon initialized")
        log.debug(f"[PROACTIVE] USER DB  : {self.user_mem.db_path}")
        log.debug(f"[PROACTIVE] AGENT DB : {self.agent_mem.db_path}")

    # ------------------------------
    # Low-level helpers (agent DB)
    # ------------------------------

    def _safe_execute_query(self, query, params=(), fetch_all=True):
        """
        Executes query against AGENT DB (proactive/internal).
        Missing tables -> empty result.
        """
        try:
            con = sqlite3.connect(str(self.db_path))
            cur = con.cursor()
            cur.execute(query, params)
            result = cur.fetchall() if fetch_all else cur.fetchone()
            con.close()
            return result
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return [] if fetch_all else None
            raise

    # ------------------------------
    # Reads: USER DB
    # Writes: AGENT DB
    # ------------------------------

    # ─── stop-words for topic extraction ──────────────────────────────────────
    _STOPWORDS = frozenset({
        'the','a','an','is','are','was','were','be','been','being','have','has','had',
        'do','does','did','will','would','could','should','may','might','can','shall',
        'to','of','in','for','on','with','at','by','from','as','or','and','but','not',
        'it','i','you','we','they','he','she','that','this','what','how','why','when',
        'where','there','here','so','if','then','just','really','like','get','got','go',
        'up','out','also','about','into','than','which','who','more','some','no','any',
        'my','your','its','our','their','me','him','her','us','them','yes','okay','ok',
        'well','now','still','even','much','many','all','very','too','make','made','use',
        'used','using','run','ran','running','sure','need','want','think','know','see',
        'look','let','try','work','working','works','right','wrong','good','bad','new',
        'old','same','different','way','time','thing','things','something','nothing',
        'everything','anything','else','please','thanks','sorry','hi','hey','hello',
        'yeah','yep','nope','actually','basically','maybe','probably','definitely',
        'already','only','both','each','other','another','again','always','never',
        'every','few','most','least','great','nice','pretty','quite','rather','really',
        'seems','seem','seemed','better','best','worse','worst','big','small','little',
        'long','short','first','last','next','back','down','over','through','after',
        'before','during','without','within','between','among','around','against',
        'going','gone','came','come','give','given','take','taken','put','keep','kept',
        'start','started','stop','stopped','end','ended','want','wanted','tell','told',
    })

    def analyze_user_patterns(self) -> List[Dict[str, Any]]:
        """
        Analyze user-facing memories for MEANINGFUL patterns (READ USER DB).
        Produces at most ~5 concise signals per cycle — no bi-gram spam.
        """
        patterns: List[Dict[str, Any]] = []

        user_db = Path(self.user_mem.db_path)
        if not user_db.exists():
            return patterns

        try:
            con = sqlite3.connect(str(user_db))
            cur = con.cursor()
            rows: List[tuple] = []
            try:
                cur.execute(
                    "SELECT ts, text, tags FROM memories "
                    "WHERE kind NOT IN ('reflection','assistant_insight','session_summary','conversation') "
                    "ORDER BY ts DESC LIMIT 300"
                )
                rows = cur.fetchall()
            except Exception:
                pass
            try:
                cur.execute(
                    "SELECT timestamp, content, '' FROM conversation_turns "
                    "WHERE role='user' ORDER BY timestamp DESC LIMIT 200"
                )
                rows += cur.fetchall()
            except Exception:
                pass
            con.close()
        except sqlite3.OperationalError:
            return patterns

        if not rows:
            return patterns

        # ── Pattern 1: Peak activity hour (single result) ──────────────────
        # Robust hour extraction. The old code did fromtimestamp(float(ts)).hour,
        # which counted rows with ts=0/NULL/default (common in `memories`) as
        # "hour 0" — producing a permanent fake "Peak activity at 00:00". Skip
        # non-real timestamps; accept epoch seconds, epoch ms, and ISO strings.
        def _real_hour(_ts):
            # numeric epoch (seconds or ms)
            try:
                _v = float(_ts)
                if _v >= 1_000_000_000_000:      # epoch milliseconds
                    return datetime.fromtimestamp(_v / 1000.0).hour
                if _v >= 1_000_000_000:          # epoch seconds (≥ 2001)
                    return datetime.fromtimestamp(_v).hour
                return None                      # 0 / tiny / default → not real activity
            except (TypeError, ValueError):
                pass
            # ISO-ish datetime string fallback
            _s = str(_ts).strip()
            for _fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                         "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(_s[:26], _fmt).hour
                except Exception:
                    continue
            return None

        # Peak activity reflects WHEN THE USER ACTUALLY TALKS to ELI — only
        # genuine user conversation turns, de-noised. Auto-generated memories,
        # STT-echo fragments, [filtered]/repeated-char junk, and exact prompt
        # replays (test sessions) must not skew the result.
        hour_counts: Dict[float, float] = {}
        try:
            _pc = sqlite3.connect(str(user_db))
            _seen_norm: set = set()
            # Window to RECENT activity (default 30 days) and weight the last week 2x, so
            # the "most active hour" tracks the user's CURRENT routine instead of a frozen
            # all-time peak (an ancient pile of 08:00 sessions used to dominate forever).
            _now_ts = time.time()
            _win_days = float(os.environ.get("ELI_HABIT_WINDOW_DAYS", "30") or 30)
            _cutoff = _now_ts - _win_days * 24 * 3600
            _recent_cut = _now_ts - 7 * 24 * 3600
            for _uts, _utext in _pc.execute(
                "SELECT timestamp, content FROM conversation_turns "
                "WHERE role='user' AND timestamp > ? ORDER BY timestamp DESC LIMIT 1500",
                (_cutoff,),
            ).fetchall():
                _h = _real_hour(_uts)
                if _h is None:
                    continue
                _t = str(_utext or "").strip()
                _low = _t.lower()
                if len(_t) < 4:
                    continue
                if "[filtered]" in _low or len(set(_t)) <= 2:
                    continue  # filtered junk / "xxxx" / repeated-char noise
                _norm = (_h, _low[:48])
                if _norm in _seen_norm:
                    continue  # dedupe identical prompts (test replays)
                _seen_norm.add(_norm)
                # Recency weight: turns in the last 7 days count double, so a shift in the
                # user's routine surfaces within days rather than being outvoted by weeks of
                # history.
                _w = 2.0 if (_uts and float(_uts) >= _recent_cut) else 1.0
                hour_counts[_h] = hour_counts.get(_h, 0.0) + _w
            _pc.close()
        except Exception:
            pass
        if hour_counts and sum(hour_counts.values()) > 5:
            _ranked = sorted(hour_counts.items(), key=lambda kv: kv[1], reverse=True)
            peak, _peak_n = _ranked[0]
            _second = _ranked[1][1] if len(_ranked) > 1 else 0
            # Only claim a single peak when it's a clear winner; otherwise report
            # the active window honestly instead of a misleading single hour.
            if _peak_n >= max(3, int(_second * 1.3) + 1):
                patterns.append({
                    "type": "time_habit",
                    "peak_hour": peak,
                    "suggestion": f"Most active around {peak:02d}:00 "
                                  f"(recent {int(_win_days)}d, recency-weighted)",
                })
            else:
                _top = ", ".join(f"{h:02d}:00" for h, _ in _ranked[:3])
                patterns.append({
                    "type": "time_habit",
                    "peak_hour": peak,
                    "suggestion": f"Activity spread across {_top}",
                })

        # ── Pattern 2: Meaningful topic focus (top 5 non-trivial words) ────
        word_counts: Dict[str, int] = {}
        for _, text, _ in rows:
            if not text:
                continue
            for w in str(text).lower().split():
                w = w.strip('.,!?;:\'"()[]{}')
                if len(w) > 4 and w not in self._STOPWORDS and w.isalpha():
                    word_counts[w] = word_counts.get(w, 0) + 1
        top = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top = [(w, c) for w, c in top if c >= 3]
        if top:
            topics = ", ".join(f"{w} (×{c})" for w, c in top)
            patterns.append({
                "type": "topic_focus",
                "topics": [w for w, _ in top],
                "suggestion": f"Current focus areas: {topics}"
            })

        # ── Pattern 3: PDF analysis usage ───────────────────────────────────
        try:
            con = sqlite3.connect(str(user_db))
            cur = con.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM memories WHERE tags LIKE '%pdf_analysis%' AND ts > ?",
                (time.time() - 30 * 24 * 3600,),
            )
            pdf_row = cur.fetchone()
            con.close()
            if pdf_row and pdf_row[0] and int(pdf_row[0]) > 5:
                patterns.append({
                    "type": "high_pdf_usage",
                    "count": int(pdf_row[0]),
                    "suggestion": f"Heavy PDF usage ({pdf_row[0]} in 30d) — pipeline automation may help"
                })
        except Exception:
            pass

        # ── Pattern 4: Recurring errors from agent DB ────────────────────────
        # Filter out world-awareness metric strings (repair_pressure=X.XX,
        # memory_confidence=X.XX, etc.) — these are state readings, not real
        # errors, and should never surface as recurring failure patterns.
        _AWARENESS_METRIC_RE = re.compile(
            r"\b(?:repair_pressure|memory_confidence|evidence_confidence|"
            r"uncertainty|autonomy_pressure|reflection_depth|tool_activity|"
            r"curiosity|focus|cognitive_load)\s*=\s*\d",
            re.IGNORECASE,
        )
        try:
            con = sqlite3.connect(str(self.db_path))
            cur = con.cursor()
            cur.execute(
                "SELECT error, occurrence_count FROM failures "
                "WHERE occurrence_count >= 2 "
                "AND COALESCE(status, 'open') NOT IN ('resolved', 'closed') "
                "ORDER BY timestamp DESC LIMIT 10"
            )
            _added = 0
            for err, cnt in (cur.fetchall() or []):
                err_str = str(err or "").strip()
                # Skip awareness metric entries — they pollute recurring_error
                # pattern detection and falsely raise repair_pressure again.
                if _AWARENESS_METRIC_RE.search(err_str):
                    continue
                if _added >= 3:
                    break
                patterns.append({
                    "type": "recurring_error",
                    "error": err_str[:80],
                    "count": int(cnt or 1),
                    "suggestion": f"Recurring error (×{cnt}): {err_str[:80]}"
                })
                _added += 1
            con.close()
        except Exception:
            pass

        # ── Pattern 5: Active project signals from user_patterns table ───────
        try:
            con = sqlite3.connect(str(user_db))
            cur = con.cursor()
            # Read ONLY the dynamic project signal (project.current, written from the LLM
            # session summary's CURRENT WORK) and any genuinely dynamic project rows — NEVER
            # the legacy hard-coded 'project.eli*' rows, which are the frozen "developing ELI"
            # canned facts that must not resurface (they're no longer written; this also
            # neutralises any that linger in an existing DB).
            cur.execute(
                "SELECT pattern_data, COALESCE(timestamp, ts) FROM user_patterns "
                "WHERE pattern_type LIKE 'project%' "
                "AND pattern_type NOT LIKE 'project.eli%' "
                "ORDER BY COALESCE(timestamp, ts, id) DESC LIMIT 3"
            )
            proj_rows = cur.fetchall()
            con.close()
            if proj_rows:
                proj = (proj_rows[0][0] or "").strip()[:120]
                proj_ts = proj_rows[0][1]
                if proj:
                    import time as _time
                    age_hours = (_time.time() - proj_ts) / 3600 if proj_ts else None
                    if age_hours is not None and age_hours >= 4:
                        age_days = age_hours / 24
                        if age_days >= 2:
                            age_label = f"{age_days:.0f}d ago"
                        else:
                            age_label = f"{age_hours:.0f}h ago"
                        suggestion = f"Active project signal ({age_label}): {proj}"
                    else:
                        suggestion = f"Active project signal: {proj}"
                    patterns.append({
                        "type": "active_project",
                        "suggestion": suggestion
                    })
        except Exception:
            pass

        # ── Pattern 6: Frequent behaviours → proactive proposals ─────────────
        # High-frequency behaviours that never become time-scheduled rules
        # (screenshots, media, news) should still make ELI OFFER to streamline
        # them. Feed them to goal autogenesis as 'frequent_behavior' signals so a
        # genuine proposal forms instead of the behaviour dying as observation noise.
        try:
            _det = []
            if hasattr(self.user_mem, "get_detected_habits"):
                _det = self.user_mem.get_detected_habits(min_count=8, limit=5) or []
            for _hb in _det:
                if not isinstance(_hb, dict):
                    continue
                _bname = str(_hb.get("name") or _hb.get("command") or "").strip()
                _bcnt = int(_hb.get("count", 0) or 0)
                if _bname and _bcnt >= 8:
                    patterns.append({
                        "type": "frequent_behavior",
                        "behavior": _bname,
                        "count": _bcnt,
                        "suggestion": (f"Frequent behaviour: {_bname.replace('_', ' ').lower()} "
                                       f"(×{_bcnt}) — offer to streamline"),
                    })
        except Exception:
            pass

        # Store a single compact observation (not per-pattern spam)
        if patterns:
            try:
                self.agent_mem.add_observation(
                    category="proactive_patterns",
                    observation="pattern_summary",
                    content=json.dumps({
                        "count": len(patterns),
                        "types": [p["type"] for p in patterns]
                    })[:1000],
                )
            except Exception:
                pass

        # --- Trend detection: compare against last stored observation ---
        # This closes the loop: patterns are not just logged once, they're
        # compared to past patterns to surface rising/falling trends.
        try:
            _last_obs = self.agent_mem.get_recent_observations(limit=5) if self.agent_mem else []
            _past_topics: set = set()
            for _obs in _last_obs:
                _obs_content = str(_obs.get("content") or _obs.get("notes") or "")
                if "topic_focus" in _obs_content:
                    try:
                        _obs_data = json.loads(_obs_content) if _obs_content.startswith("{") else {}
                        for _t in _obs_data.get("topics", []):
                            _past_topics.add(str(_t).lower())
                    except Exception:
                        pass
            for _pat in patterns:
                if _pat.get("type") == "topic_focus":
                    _cur_topics = set(str(t).lower() for t in _pat.get("topics", []))
                    _new_topics = _cur_topics - _past_topics
                    _dropped = _past_topics - _cur_topics
                    if _new_topics:
                        patterns.append({
                            "type": "trend_emerging",
                            "topics": list(_new_topics),
                            "suggestion": f"Emerging focus: {', '.join(_new_topics)} (not seen in prior ticks)",
                        })
                    if _dropped and _past_topics:
                        patterns.append({
                            "type": "trend_fading",
                            "topics": list(_dropped),
                            "suggestion": f"Fading interest: {', '.join(_dropped)} (seen before, gone now)",
                        })
                    break
        except Exception:
            pass

        # Persist current patterns as an observation for future trend comparison
        try:
            _obs_payload = json.dumps({
                "patterns": [{"type": p.get("type"), "topics": p.get("topics", [])} for p in patterns],
                "ts": time.time(),
            })
            _obs_mem = self.agent_mem or self.user_mem
            if _obs_mem:
                _obs_mem.add_observation("proactive_pattern_tick", _obs_payload)
        except Exception:
            pass

        log.debug(f"[PROACTIVE] Pattern analysis: {len(patterns)} signals ({', '.join(p['type'] for p in patterns)})")
        return patterns

    def analyze_code_quality(self) -> List[Dict[str, Any]]:
        """
        Analyze ELI's own code for improvements (WRITE to AGENT DB)
        """
        improvements: List[Dict[str, Any]] = []

        code_files = [
            self.package_root / "execution" / "executor_enhanced.py",
            self.package_root / "execution" / "router_enhanced.py",
            self.package_root / "kernel" / "engine.py",
        ]

        for file_path in code_files:
            if not file_path.exists():
                continue

            try:
                content = file_path.read_text()
                lines = content.split("\n")

                # Duplicate lines heuristic
                line_counts: Dict[str, int] = {}
                for line in lines:
                    stripped = line.strip()
                    if len(stripped) > 20:
                        line_counts[stripped] = line_counts.get(stripped, 0) + 1
                duplicates = {k: v for k, v in line_counts.items() if v > 2}
                if duplicates:
                    improvements.append({
                        "file": file_path.name,
                        "type": "duplicate_code",
                        "count": len(duplicates),
                        "priority": 2,
                        "suggestion": f"Found {len(duplicates)} duplicate code blocks - consider refactoring"
                    })

                # Long functions heuristic
                in_function = False
                function_line_count = 0
                function_name = ""

                for line in lines:
                    if line.strip().startswith("def "):
                        if function_line_count > 100:
                            improvements.append({
                                "file": file_path.name,
                                "type": "long_function",
                                "function": function_name,
                                "lines": function_line_count,
                                "priority": 3,
                                "suggestion": f"Function '{function_name}' is {function_line_count} lines - consider splitting"
                            })
                        in_function = True
                        function_line_count = 0
                        function_name = line.strip().split("(")[0].replace("def ", "")
                    elif in_function:
                        function_line_count += 1

                # TODO/FIXME comments
                todos = [line for line in lines if "TODO" in line or "FIXME" in line]
                if todos:
                    improvements.append({
                        "file": file_path.name,
                        "type": "todos",
                        "count": len(todos),
                        "priority": 4,
                        "suggestion": f"Found {len(todos)} TODO/FIXME comments"
                    })

            except Exception as e:
                log.debug(f"[PROACTIVE] Code analysis error for {file_path.name}: {e}")

        # Store improvements summary into AGENT DB
        for item in improvements:
            try:
                self.agent_mem.log_improvement("code_quality", json.dumps(item)[:4000])
            except Exception:
                pass

        return improvements

    def execute_habit(self, rule: dict) -> dict:
        """
        Execute a habit rule's shell command. Only runs if command is non-empty.
        Returns {"ok": bool, "output": str, "returncode": int}.
        """
        name = rule.get("name", "unnamed")
        cmd = (rule.get("command") or "").strip()
        if not cmd:
            return {"ok": False, "error": "No command defined"}
        # Kill-switch: habit commands run via the shell (they may use pipes/&&).
        # That's fine for a user's own habits, but a redistributed/imported habit
        # DB is untrusted — let deployments disable shell habits. Default on to
        # preserve existing behavior; ELI_NO_HABIT_SHELL=1 or the
        # habit_shell_enabled=false setting turns it off.
        _habit_shell_on = os.environ.get("ELI_NO_HABIT_SHELL", "0") != "1"
        if _habit_shell_on:
            try:
                from eli.core import config as _cfg
                _habit_shell_on = bool(_cfg.get("habit_shell_enabled", True))
            except Exception:
                pass
        if not _habit_shell_on:
            return {"ok": False, "error": "Shell habits are disabled (habit_shell_enabled=false)"}
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            out = (result.stdout or result.stderr or "").strip()[:500]
            status = "✓" if result.returncode == 0 else f"✗ (rc={result.returncode})"
            log.debug(f"[PROACTIVE] Habit executed '{name}': {status} — {out[:120]}")
            self.suggestion_queue.put(("habit_result", {
                "type": "habit_result",
                "name": name,
                "command": cmd,
                "ok": result.returncode == 0,
                "suggestion": f"{status} Habit '{name}' ran: {out[:120] or 'done'}"
            }))
            # Log to agent DB
            try:
                self.agent_mem.add_observation(
                    category="habit_executed",
                    observation=f"{name}: rc={result.returncode}",
                    content=out[:500],
                )
            except Exception:
                pass
            return {"ok": result.returncode == 0, "output": out, "returncode": result.returncode}
        except subprocess.TimeoutExpired:
            msg = f"Habit '{name}' timed out after 30s"
            log.debug(f"[PROACTIVE] {msg}")
            return {"ok": False, "error": msg}
        except Exception as exc:
            msg = str(exc)
            log.debug(f"[PROACTIVE] Habit execution error '{name}': {msg}")
            return {"ok": False, "error": msg}

    def track_error(self, error_type: str, error_message: str, context: str):
        """
        Track recurring errors (WRITE AGENT DB).
        """
        try:
            # Use Memory’s failure logger (dedup + occurrence_count)
            self.agent_mem.log_failure(
                user_input=context or error_message,
                error=f"{error_type}: {error_message}",
                confidence=1.0,
                context={"context": context},
                command=error_type,
            )
        except Exception as e:
            log.debug(f"[PROACTIVE] Error tracking failed: {e}")

    def generate_morning_report(self) -> str:
        """
        Morning report should read:
          - USER DB: conversations/memories
          - AGENT DB: improvements/errors/observations
        """
        hour = datetime.now().hour
        greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

        user_db = Path(self.user_mem.db_path)
        agent_db = Path(self.agent_mem.db_path)
        window = time.time() - (24 * 60 * 60)

        def fetch_all(db: Path, query: str, params=()):
            try:
                con = sqlite3.connect(str(db))
                cur = con.cursor()
                cur.execute(query, params)
                rows = cur.fetchall()
                con.close()
                return rows
            except sqlite3.OperationalError:
                return []

        def fetch_one(db: Path, query: str, params=()):
            try:
                con = sqlite3.connect(str(db))
                cur = con.cursor()
                cur.execute(query, params)
                row = cur.fetchone()
                con.close()
                return row
            except sqlite3.OperationalError:
                return None

        # USER DB: interactions/convs/memories
        interaction_count = 0
        count_row = fetch_one(user_db, "SELECT COUNT(*) FROM conversations WHERE timestamp > ?", (window,))
        if count_row:
            interaction_count = int(count_row[0])

        recent_convs = fetch_all(
            user_db,
            "SELECT role, content FROM conversations WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 20",
            (window,),
        )
        recent_mems = fetch_all(
            user_db,
            "SELECT text, tags FROM memories ORDER BY ts DESC LIMIT 30",
        )

        # AGENT DB: failures/improvements/observations
        errors = fetch_all(
            agent_db,
            "SELECT user_input, error, occurrence_count FROM failures ORDER BY timestamp DESC LIMIT 5",
        )
        improvements = fetch_all(
            agent_db,
            "SELECT category, description FROM improvements ORDER BY timestamp DESC LIMIT 5",
        )

        ctx_parts = []
        if recent_convs:
            conv_text = "\n".join([f"{r}: {c[:120]}" for r, c in recent_convs[:10]])
            ctx_parts.append(f"Recent conversations:\n{conv_text}")
        if recent_mems:
            mem_text = "\n".join([f"[{t}] {m[:100]}" for m, t in recent_mems[:15]])
            ctx_parts.append(f"Knowledge base:\n{mem_text}")
        if errors:
            ctx_parts.append("Recent failures (agent):\n" + "\n".join([f"{e[:80]} (x{n})" for _, e, n in errors]))
        if improvements:
            ctx_parts.append("Recent improvements (agent):\n" + "\n".join([f"[{c}] {d[:100]}" for c, d in improvements]))

        # ── 24h news digest: eight 3-hour reflections compiled together ──
        news_digest = ""
        news_meta = {}
        try:
            from eli.tools.news.news_synthesis import build_morning_digest
            news_meta = build_morning_digest(hours=24) or {}
            if news_meta.get("digest"):
                ctx_parts.append(
                    f"24h news digest ({news_meta.get('reflection_count',0)} "
                    f"3h reflections, {news_meta.get('article_count',0)} articles):\n"
                    f"{news_meta['digest']}"
                )
        except Exception as _nde:
            log.debug(f"[PROACTIVE] Morning news digest error: {_nde}")

        # ── Include active habit rules in briefing context ──
        try:
            from eli.planning.habits import detect_habits
            _mem_h = self.user_mem or self.agent_mem
            if _mem_h and hasattr(_mem_h, 'get_habit_rules'):
                _rules = _mem_h.get_habit_rules(enabled_only=True) or []
                if _rules:
                    _rule_lines = []
                    for _r in _rules:
                        if not isinstance(_r, dict):
                            try: _r = dict(_r)
                            except: continue
                        _rname = _r.get("name", "?")
                        _rcmd = _r.get("command", "?")
                        _rh = _r.get("hour", 0)
                        _rm = _r.get("minute", 0)
                        _rule_lines.append(f"  {_rname} ({_rcmd}) at {_rh:02d}:{_rm:02d}")
                    if _rule_lines:
                        ctx_parts.append("Detected user habits:\n" + "\n".join(_rule_lines))
        except Exception:
            pass

        context = "\n\n".join(ctx_parts) if ctx_parts else "No recent activity."

        # Morning prompt: synthesise across the 8 news reflections, then
        # expand load-bearing items, then ask 3 targeted follow-up questions.
        followup_directive = (
            "After your briefing, expand on the most consequential news "
            "item from the 24h digest above (with the depth a researcher would "
            "expect), then ask the user one or two pointed follow-up questions "
            "(just one unless there are genuinely distinct threads worth "
            "pursuing) tied to specific reflection windows or items, and offer "
            "to go deeper if they want to discuss something at length. Cite "
            "reflection windows as [HH:MM-HH:MM] and never invent stories.\n"
            if news_meta.get("digest") else ""
        )

        prompt = f"""You are ELI. Generate a specific, data-driven briefing based ONLY on the actual content below.
No generic openers. No filler. Reference specific topics, files, errors, or patterns from the data.
Be direct and analytical. Flag anything that needs attention.
Date: {datetime.now().strftime("%A %B %d %H:%M")} | Interactions last 24h: {interaction_count}

{context}

{followup_directive}3-5 specific actionable points. No fluff."""

        try:
            from eli.cognition.inference_broker import get_broker as _pro_broker; chat_completion = lambda prompt, system=None, max_tokens=512, temperature=0.7, **kw: _pro_broker().infer(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
            import concurrent.futures as _cf

            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(
                    chat_completion,
                    prompt,
                    system="You are ELI. Reference actual data only. Write 5 detailed points, "
                           "each 3-4 sentences with full reasoning. No one-liners.",
                    max_tokens=1500,
                    temperature=0.3,
                )
                briefing = _fut.result(timeout=120)

            return f"🌅 {greeting}\n\n{briefing.strip()}"
        except Exception:
            # fallback summary
            lines_out = [f"🌅 {greeting} — {datetime.now().strftime('%A %B %d')}"]
            lines_out.append(f"📊 {interaction_count} interactions in last 24h")
            if errors:
                lines_out.append(f"⚠️  {len(errors)} recent failures — top: {errors[0][1][:60]}")
            if improvements:
                lines_out.append(f"💡 {len(improvements)} recent improvements — top: {improvements[0][1][:60]}")
            if recent_mems:
                lines_out.append(f"🧠 Last memory: {recent_mems[0][0][:80]}")
            return "\n".join(lines_out)

    def run(self):
        """
        Main proactive daemon loop
        """
        self.running = True
        log.debug("[PROACTIVE] Daemon started - continuous learning active")

        last_analysis = time.time()
        last_report = datetime.now().date()
        last_news_fetch = 0.0
        last_autonomy = 0.0

        while self.running:
            try:
                if self.paused:
                    time.sleep(5)
                    continue

                # ── Autonomy / self-awareness tick (every 30 min) ─────────────────
                # ELI's self-directed loop, finally wired to actually RUN (it was
                # previously only fired by the Operator Console button): monitor own
                # code changes, refresh the self-model overlays (self-awareness), and
                # advance goals → proposals. All governed — approval_engine caps the
                # controller to observe-only / memory-write, and goal/scheduler ticks
                # produce PROPOSALS that still need user approval, so nothing
                # destructive runs unattended. Kill switch: ELI_AUTONOMY_TICK=0.
                if (time.time() - last_autonomy > 1800
                        and os.environ.get("ELI_AUTONOMY_TICK", "1").strip().lower()
                        not in ("0", "false", "no", "off")):
                    last_autonomy = time.time()
                    try:
                        from eli.planning.autonomy_controller import (
                            safe_tick, safe_goal_tick, safe_scheduler_tick)
                        _at = safe_tick(reason="proactive_daemon")
                        _gt = safe_goal_tick(limit=3)
                        _st = safe_scheduler_tick(limit=3, cooldown_sec=60)
                        log.debug(
                            "[PROACTIVE] autonomy tick: code_changed=%s goal_ok=%s sched_ok=%s",
                            (_at.get("code_monitor") or {}).get("has_changes"),
                            _gt.get("ok"), _st.get("ok"))
                    except Exception as _auto_err:
                        log.debug(f"[PROACTIVE] autonomy tick skipped: {_auto_err}")

                # Run analysis every 10 minutes
                if time.time() - last_analysis > 600:
                    patterns = self.analyze_user_patterns()
                    improvements = self.analyze_code_quality()

                    # Background-synthesise the reflection insight (gated on a resident
                    # model + throttled to 30 min inside refresh_insight) so the reflection
                    # + proactive agents surface real synthesis with zero per-turn latency.
                    try:
                        from eli.planning.insight_synthesis import refresh_insight
                        refresh_insight(self.user_mem)
                    except Exception:
                        pass

                    for pattern in patterns:
                        self.suggestion_queue.put(("pattern", pattern))
                    for improvement in improvements:
                        self.suggestion_queue.put(("improvement", improvement))

                    # ── Habit detection + execution ────────────────────────
                    try:
                        from eli.planning.habits import detect_habits
                        detect_habits(days=14, min_occurrences=3)

                        # ── Proactively OFFER newly-detected habits ──────────
                        # detect_habits creates suggestions DISABLED. Pitch one
                        # per cycle (specific app at a specific hour) and let the
                        # user say yes/no — never silently activate. One offer at a
                        # time; don't re-pitch the same rule.
                        try:
                            from eli.planning.habits import (
                                get_pending_habit, set_pending_habit,
                                was_offered, mark_offered,
                            )
                            _hmem = self.user_mem or self.agent_mem
                            if _hmem and hasattr(_hmem, "get_habit_rules") and not get_pending_habit():
                                for _r in (_hmem.get_habit_rules(enabled_only=False) or []):
                                    if not isinstance(_r, dict):
                                        try:
                                            _r = dict(_r)
                                        except Exception:
                                            continue
                                    if _r.get("enabled"):
                                        continue  # already active
                                    _rid = int(_r.get("id", -1))
                                    if _rid < 0 or was_offered(_rid):
                                        continue
                                    # Skip legacy/corrupt suggestions: a real learned
                                    # habit has a concrete time AND a command distinct
                                    # from its bare name. NULL-time / command==name rows
                                    # are legacy corruption that otherwise surfaced as a
                                    # bogus "run it around 00:00" offer (user-reported).
                                    _hraw, _mraw = _r.get("hour"), _r.get("minute")
                                    _cmd = str(_r.get("command") or "").strip()
                                    _nm = str(_r.get("name") or "a recurring action").strip()
                                    if _hraw is None or _mraw is None or str(_hraw) == "" or str(_mraw) == "":
                                        continue
                                    if _cmd and _cmd.lower() == _nm.lower():
                                        continue
                                    try:
                                        _hh, _mm = int(_hraw), int(_mraw)
                                    except (TypeError, ValueError):
                                        continue
                                    if not (0 <= _hh <= 23 and 0 <= _mm <= 59):
                                        continue
                                    offer = (f"I've noticed a pattern — “{_nm}”. Want me to add it "
                                             f"as a habit and run it around {_hh:02d}:{_mm:02d}? (yes/no)")
                                    set_pending_habit(_rid, _nm, _hh, _mm, _cmd)
                                    mark_offered(_rid)
                                    self.suggestion_queue.put(("habit_suggestion", {
                                        "rule_id": _rid, "name": _nm,
                                        "hour": _hh, "minute": _mm, "suggestion": offer,
                                    }))
                                    break  # one offer per cycle
                        except Exception as _ho:
                            log.debug(f"[PROACTIVE] habit offer skipped: {_ho}")

                        from datetime import datetime as _dt
                        _now = _dt.now()
                        _cur_h, _cur_m = _now.hour, _now.minute
                        _mem = self.user_mem or self.agent_mem
                        if _mem and hasattr(_mem, 'get_habit_rules'):
                            for rule in (_mem.get_habit_rules(enabled_only=True) or []):
                                if not isinstance(rule, dict):
                                    try:
                                        rule = dict(rule)
                                    except Exception:
                                        continue
                                _rh = int(rule.get("hour", -1))
                                _rm = int(rule.get("minute", -1))
                                _name = rule.get("name", "scheduled action")
                                _cmd = (rule.get("command") or "").strip()
                                # Within 5-minute window of scheduled time
                                if _rh == _cur_h and abs(_rm - _cur_m) <= 5:
                                    log.debug(f"[PROACTIVE] Habit triggered: '{_name}' @ {_rh:02d}:{_rm:02d}")
                                    if _cmd:
                                        # Execute and report result via queue
                                        threading.Thread(
                                            target=self.execute_habit,
                                            args=(rule,),
                                            daemon=True,
                                        ).start()
                                    else:
                                        # No command — notify user
                                        self.suggestion_queue.put(("habit", {
                                            "type": "habit_trigger",
                                            "name": _name,
                                            "command": "",
                                            "suggestion": f"Scheduled time for '{_name}' — no command configured"
                                        }))
                    except Exception as _he:
                        log.debug(f"[PROACTIVE] Habit detection error: {_he}")

                    try:
                        drain_proposals_to_agent_memory(self.agent_mem, max_items=32, archive=True)
                    except Exception as _pq_exc:
                        log.debug(f"[PROACTIVE] Proposal drain error: {_pq_exc}")

                    try:
                        refresh_all_overlays_nonfatal(reason="proactive_tick")
                    except Exception as _rf_exc:
                        log.debug(f"[PROACTIVE] Overlay refresh error: {_rf_exc}")

                    # ── World awareness: fire reflection event on each tick ──
                    try:
                        from eli.world.world_event_bus import fire_world_event as _wfe
                        _pat_count = len([p for p in patterns if p.get("suggestion")])
                        _imp_count = len([i for i in improvements if i.get("suggestion")])
                        _wfe(
                            "reflection",
                            "proactive_daemon",
                            f"Proactive tick: {_pat_count} patterns, {_imp_count} improvements analysed.",
                            {
                                "pattern_count": _pat_count,
                                "improvement_count": _imp_count,
                                "reflection_depth": min(1.0, (_pat_count + _imp_count) * 0.1),
                            },
                        )
                    except Exception:
                        pass

                    # ── World → runtime feedback loop ────────────────────────
                    # Read AwarenessState-driven suggestions from the world engine
                    # and merge high-priority ones into the self-improvement memory
                    # so they surface as proactive proposals in future ticks.
                    try:
                        from eli.world.local_world_bridge import get_awareness_driven_suggestions as _gads
                        _world_suggs = _gads()
                        for _ws in _world_suggs:
                            _ws_priority = float(_ws.get("priority", 0.0))
                            _ws_action = str(_ws.get("action") or "")
                            if _ws_priority >= 0.55:
                                # Record as an observation (NOT a failure) so it
                                # surfaces as a proposal without incrementing the
                                # failure count — which would raise repair_pressure
                                # and create an infinite feedback loop.
                                try:
                                    _obs_target = self.agent_mem or self.user_mem
                                    if _obs_target:
                                        _obs_target.add_observation(
                                            source="world_autonomy",
                                            category="world_suggestion",
                                            observation=f"[world_suggestion] {_ws_action}",
                                            content=_ws.get("reason", "world awareness threshold exceeded"),
                                        )
                                except Exception:
                                    pass

                            if _ws_priority >= 0.70 and _ws_action:
                                # HIGH priority: actually execute the suggested action.
                                # Queue as a suggestion so the proactive listener can
                                # surface it to the user in the next response.
                                self.suggestion_queue.put(("world_action", {
                                    "type": "world_driven_action",
                                    "action": _ws_action,
                                    "reason": _ws.get("reason", ""),
                                    "priority": _ws_priority,
                                    "suggestion": (
                                        f"[AUTO] World awareness triggered {_ws_action}: "
                                        f"{_ws.get('reason', '')[:120]}"
                                    ),
                                }))
                                # Also store as a user-visible memory note
                                try:
                                    _obs_mem = self.agent_mem or self.user_mem
                                    if _obs_mem:
                                        _obs_mem.store_memory(
                                            f"ELI autonomy: {_ws_action} triggered — {_ws.get('reason','')[:120]}",
                                            tags=["eli_autonomy", "world_action", "auto"],
                                            kind="insight",
                                            source="eli_world",
                                            importance=0.72,
                                        )
                                except Exception:
                                    pass

                            if _ws_priority >= 0.55:
                                log.debug(
                                    f"[PROACTIVE] World suggestion: "
                                    f"action={_ws_action} priority={_ws_priority:.2f} "
                                    f"reason={_ws.get('reason','')[:80]}"
                                )
                    except Exception as _world_loop_err:
                        log.debug(f"[PROACTIVE] World→runtime feedback failed: {_world_loop_err}")

                    # ── Goal autogenesis: turn ELI's own signals into goals ──────
                    # The autonomy/goal-tick stack was fully wired but the goal store
                    # was always empty (create_goal was operator-only). Convert the
                    # high-value world-suggestions + recurring-failure patterns this
                    # tick produced into GOVERNED goals (proposal_only — they surface
                    # for approval via governed_goal_tick, never silent execution).
                    # Deduped + capped, so this is safe every tick.
                    try:
                        from eli.planning.goal_autogenesis import propose_goals_from_signals
                        _new_goals = propose_goals_from_signals(
                            world_suggestions=_world_suggs,
                            patterns=patterns,
                            improvements=improvements,
                            memory=self.agent_mem or self.user_mem,
                        )
                        if _new_goals:
                            log.info(
                                "[PROACTIVE] goal autogenesis: %d new goal(s) — %s",
                                len(_new_goals), ", ".join(_new_goals),
                            )
                    except Exception as _goal_gen_err:
                        log.debug(f"[PROACTIVE] goal autogenesis failed: {_goal_gen_err}")

                    last_analysis = time.time()

                    # ── 3-hour news fetch + synthesis cycle ───────────────
                    # Every 3 hours: fetch new articles, compile a synthesis
                    # of the window, store it as a news_reflection. The
                    # morning report later compiles 8 such reflections per 24h.
                    _news_net_ok = False
                    try:
                        from eli.core.config import network_allowed as _net_ok
                        _news_net_ok = _net_ok()
                    except Exception:
                        pass
                    if _news_net_ok and time.time() - last_news_fetch > 10800:  # 3 hours
                        try:
                            from eli.tools.news.news_fetcher import fetch_news as _fetch_news
                            _nr = _fetch_news(sources=["hn", "reddit"])
                            stored_new = int(_nr.get("stored_new", 0) or 0)

                            from eli.tools.news.news_synthesis import synthesise_window
                            _sr = synthesise_window()

                            if not _sr.get("skipped"):
                                self.suggestion_queue.put(("news", {
                                    "type": "news_synthesis",
                                    "suggestion": (
                                        f"3h news synthesis: "
                                        f"{stored_new} new articles, "
                                        f"{_sr.get('article_count', 0)} in window."
                                    ),
                                }))
                            last_news_fetch = time.time()
                        except Exception as _ne:
                            log.debug(f"[PROACTIVE] News synthesis error: {_ne}")

                    # ── Write artifact files for agent bus (do NOT drain queue) ──
                    try:
                        from eli.core.paths import get_paths as _gp
                        _pro_dir = _gp().artifacts_dir / "proactive"
                        _pro_dir.mkdir(parents=True, exist_ok=True)
                        _ctx_lines = [f"[{p['type']}] {p.get('suggestion','')}" for p in patterns if p.get('suggestion')]
                        _action_lines = [f"[improvement] {i.get('suggestion','')}" for i in improvements if i.get('suggestion')]
                        if _ctx_lines:
                            (_pro_dir / "latest_context.txt").write_text(
                                "\n".join(_ctx_lines[-8:]), encoding="utf-8")
                        if _action_lines:
                            (_pro_dir / "latest_action.txt").write_text(
                                "\n".join(_action_lines[-4:]), encoding="utf-8")
                    except Exception as _pe:
                        log.debug(f"[PROACTIVE] artifact flush error: {_pe}")

                # Generate morning report once per day between 6-10
                current_date = datetime.now().date()
                current_hour = datetime.now().hour
                if current_date > last_report and 6 <= current_hour <= 10:
                    report = self.generate_morning_report()
                    if report:
                        # Print to CLI
                        print(f"\n[PROACTIVE] Morning report:\n{report}\n")
                        # Push to GUI summary tab via queue
                        self.suggestion_queue.put(("morning_report", {
                            "type": "morning_report",
                            "suggestion": report,
                        }))
                        # Store in user DB
                        if hasattr(self, 'user_mem') and self.user_mem:
                            try:
                                self.user_mem.store_memory(
                                    report[:500],
                                    tags=["morning_report", "proactive", "briefing"],
                                    source="proactive_daemon",
                                    kind="briefing",
                                )
                            except Exception as _store_err:
                                log.debug(f"[PROACTIVE] Failed to store morning report: {_store_err}")
                    last_report = current_date

                _maybe_update_persona_from_db()
                time.sleep(60)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.debug(f"[PROACTIVE] Daemon error: {e}")
                time.sleep(60)

        log.debug("[PROACTIVE] Daemon stopped")

    def stop(self):
        self.running = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


# Singleton instance
_daemon = None
_daemon_started = False
_daemon_start_lock = threading.Lock()

def get_daemon() -> ProactiveDaemon:
    global _daemon
    if _daemon is None:
        _daemon = ProactiveDaemon()
    return _daemon

def _guarded_daemon_run(daemon) -> None:
    """Run the daemon with a crash guard.

    On unhandled exception, writes the traceback to
    artifacts/proactive_daemon_down.flag so the GUI can surface a warning
    and offer a restart button.
    """
    try:
        daemon.run()
    except Exception as _exc:
        import traceback as _tb
        _crash_text = _tb.format_exc()
        try:
            _flag = get_paths().artifacts_dir / "proactive_daemon_down.flag"
            _flag.parent.mkdir(parents=True, exist_ok=True)
            _flag.write_text(str(_exc)[:500], encoding="utf-8")
            # Full traceback goes to the crash log for debugging
            _crash_log = get_paths().artifacts_dir / "proactive_daemon_crash.txt"
            _crash_log.write_text(_crash_text, encoding="utf-8")
        except Exception:
            pass
        log.debug(f"[PROACTIVE_DAEMON] Crashed: {_exc}")


def start_daemon():
    global _daemon_started
    with _daemon_start_lock:
        if _daemon_started:
            return _daemon
        daemon = get_daemon()
        _daemon_started = True
    thread = threading.Thread(
        target=_guarded_daemon_run, args=(daemon,),
        daemon=True, name="eli-proactive-daemon",
    )
    thread.start()
    return daemon


# _ELI_PERSONA_DB_AUTOUPDATE_HOOK_V1
_LAST_PERSONA_UPDATE = 0.0

def _maybe_update_persona_from_db():
    global _LAST_PERSONA_UPDATE
    now = time.time()
    if now - _LAST_PERSONA_UPDATE < 60.0:
        return
    _LAST_PERSONA_UPDATE = now

    try:
        from eli.cognition.persona_updater import update_persona_overlay
        from eli.memory.memory import get_memory
        update_persona_overlay(memory=get_memory())
    except Exception as _e:
        try:
            log.debug(f"[PROACTIVE] persona overlay update failed: {_e}")
        except Exception:
            pass


if __name__ == "__main__":
    daemon = ProactiveDaemon()

    print("\n" + "=" * 70)
    print("Testing Proactive Daemon")
    print("=" * 70 + "\n")

    print("Analyzing user patterns...")
    patterns = daemon.analyze_user_patterns()
    print(f"Found {len(patterns)} patterns:")
    for p in patterns:
        print(f"  • {p}")

    print("\nAnalyzing code quality...")
    improvements = daemon.analyze_code_quality()
    print(f"Found {len(improvements)} improvements:")
    for i in improvements[:5]:
        print(f"  • {i}")

    print("\nGenerating morning report...")
    report = daemon.generate_morning_report()
    print(report)

    print("\n" + "=" * 70)
    print("Proactive Daemon Test Complete")
    print("=" * 70)
