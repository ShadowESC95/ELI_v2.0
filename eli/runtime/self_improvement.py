from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eli.memory import get_agent_memory
from eli.cognition.inference_broker import get_broker
from eli.memory import get_memory, Memory


from eli.utils.log import get_logger
log = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _safe_str(x: Any) -> str:
    try:
        return "" if x is None else str(x)
    except Exception:
        return ""


def _dotted_module_for_path(p: Path) -> Optional[str]:
    """Return the importable dotted module name for a project .py file, or None
    if it isn't an importable module under the `eli` package."""
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT)
    except Exception:
        return None
    parts = list(rel.parts)
    if not parts or parts[0] != "eli" or not parts[-1].endswith(".py"):
        return None
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _smoke_import_module(dotted: str, timeout: float = 30.0) -> Tuple[bool, str]:
    """Import a module in an isolated subprocess; return (ok, detail).

    `ok=False` on any import exception (including a bad/typo'd import the patch
    introduced) or on timeout — a self-modifying engine treats "can't confirm it
    loads within budget" as unsafe. Optional-dependency gaps are handled by the
    *caller* via a differential check (import before vs after the patch), so this
    deliberately does NOT special-case ModuleNotFoundError. Inability to launch
    the subprocess at all (infra error) returns ok=True so we never falsely
    revert on our own tooling failure.
    """
    code = (
        "import importlib, sys\n"
        f"m = {dotted!r}\n"
        "try:\n"
        "    importlib.import_module(m)\n"
        "except Exception:\n"
        "    import traceback; traceback.print_exc(); sys.exit(3)\n"
    )
    env = dict(os.environ)
    env["ELI_PATCH_SMOKE"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"import of {dotted} exceeded {timeout:.0f}s"
    except Exception as exc:
        return True, f"smoke-test skipped (infra): {exc}"
    if proc.returncode == 0:
        return True, ""
    tail = "\n".join((proc.stderr or "").splitlines()[-6:])
    return False, tail


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: Dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _ensure_failure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT
        )
        """
    )
    _ensure_columns(conn, "failures", {
        "command": "TEXT",
        "error": "TEXT",
        "context": "TEXT",
        "occurrence_count": "INTEGER DEFAULT 1",
        "timestamp": "REAL",
        "first_seen": "REAL",
        "last_seen": "REAL",
        "confidence": "REAL DEFAULT 0.0",
    })

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS error_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT,
            details TEXT,
            timestamp REAL
        )
        """
    )
    _ensure_columns(conn, "error_tracking", {
        "occurrence_count": "INTEGER DEFAULT 1",
        "first_seen": "REAL",
        "last_seen": "REAL",
    })

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS code_patches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            description TEXT,
            old_code TEXT,
            new_code TEXT,
            status TEXT DEFAULT 'applied',
            timestamp REAL,
            failure_ref TEXT
        )
        """
    )
    conn.commit()


class SelfImprovementEngine:
    """
    Self-improvement engine: analyzes failures, generates code patches, and applies them.
    Runs on the AGENT DB by default.
    """

    def __init__(self, memory: Optional[Memory] = None):
        self.memory: Memory = memory or get_agent_memory()

    # ─────────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────────

    def log_failure(self, input_text: str, error: str = "", confidence: float = 0.0, context: dict = None):
        # Guard: never persist a unit-test mock as a real failure. When a test patches
        # subprocess.run, the executor's stdout concat yields a MagicMock repr
        # ("<MagicMock name='run().stdout.__add__()' …>") that previously leaked into the
        # live failures DB and polluted SELF_ANALYZE. Drop mock reprs at the write source,
        # so a test-isolation slip can't pollute real runtime failures.
        import re as _re_mock
        if _re_mock.search(r"<\s*(?:Magic)?Mock\b|(?:Magic)?Mock\s+name=|\bMock\s+id=0x",
                           f"{error} {input_text}"):
            return
        ctx = context or {}
        now = time.time()
        try:
            self.memory.log_failure(input_text, error=error, confidence=confidence, context=ctx)
        except Exception:
            pass
        conn = self.memory._get_connection()
        try:
            _ensure_failure_tables(conn)
            error_type = _safe_str(error) or _safe_str(input_text)
            details = json.dumps(ctx, ensure_ascii=False) if isinstance(ctx, dict) else _safe_str(ctx)
            row = conn.execute(
                "SELECT id, occurrence_count FROM error_tracking WHERE error_type = ? AND details = ?",
                (error_type, details),
            ).fetchone()
            new_count = 1
            if row:
                new_count = (row[1] or 1) + 1
                conn.execute(
                    "UPDATE error_tracking SET occurrence_count = occurrence_count + 1, last_seen = ?, timestamp = ? WHERE id = ?",
                    (now, now, row[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO error_tracking (error_type, details, timestamp, occurrence_count, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                    (error_type, details, now, 1, now, now),
                )
            conn.commit()
        finally:
            conn.close()

        # Escalation clauses (recurring error → ELI proactively raises it with the user):
        #   ≥5×  → "notice": flag it to the user in the next conversation turn.
        #   ≥10× → "act":    additionally attempt a self-resolution and report the outcome.
        # Skip user-input/clarification cases (fault=False) — those aren't real faults.
        if new_count in (5, 10) or (new_count > 10 and new_count % 5 == 0):
            if not (isinstance(ctx, dict) and ctx.get("fault") is False):
                stage = "notice" if new_count < 10 else "act"
                head = (f"Heads up — I keep hitting an error: “{error_type[:90]}” "
                        f"({new_count}× now).")
                tail = ("I'm flagging it and keeping watch." if stage == "notice"
                        else "I'm going to try to resolve it myself and let you know.")
                _push_self_heal_notice({
                    "error_type": error_type[:140], "count": int(new_count),
                    "stage": stage, "message": f"{head} {tail}",
                })
        # Auto-trigger improvement analysis when an error pattern recurs 5× (and every 5× after)
        if new_count >= 5 and new_count % 5 == 0:
            log.debug(f"[SELF-IMPROVE] Recurring error pattern detected ({new_count}×) — auto-triggering capability analysis")
            threading.Thread(target=self._background_analyze, daemon=True,
                             args=(error_type, int(new_count))).start()

    def _background_analyze(self, error_type: str = "", count: int = 0) -> None:
        """Run analyze_and_improve then attempt code patches for high-recurrence failures.
        For a ≥10× error this also records a user-facing OUTCOME notice so ELI can report
        what it actually tried (proposals generated / patch applied / logged for review)."""
        _proposals = 0
        _patched: List[str] = []
        _outcome = "logged it for review — I couldn't auto-resolve it this pass"

        def _report():
            if count >= 10:
                if _patched:
                    out = "applied a fix to " + ", ".join(_patched)
                elif _proposals:
                    out = f"worked up {_proposals} fix proposal(s) for it"
                else:
                    out = _outcome
                _push_self_heal_notice({
                    "error_type": (error_type or "a recurring error")[:140],
                    "count": int(count), "stage": "resolved",
                    "message": f"Update on “{(error_type or 'that error')[:80]}”: I {out}.",
                })

        try:
            result = self.analyze_and_improve()
            imps = result.get("improvements", [])
            _proposals = len(imps)
            if imps:
                log.debug(f"[SELF-IMPROVE] Auto-analysis complete: {len(imps)} proposal(s) generated")
            else:
                log.debug("[SELF-IMPROVE] Auto-analysis complete: no new proposals")
        except Exception as _ae:
            log.debug(f"[SELF-IMPROVE] Auto-analysis failed: {_ae}")
            _report()
            return

        # Attempt code patches for failures with file tracebacks and high recurrence.
        # Gated behind auto_patch_enabled (default off) so patches never apply without
        # explicit user opt-in via settings.json.
        try:
            from eli.core.full_control import is_full_control as _ifc
        except Exception:
            _ifc = lambda: False
        try:
            _settings = json.loads((PROJECT_ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
            if not _settings.get("auto_patch_enabled", False) and not _ifc():
                log.debug("[SELF-IMPROVE] auto_patch_enabled is off — patch proposals logged but not applied")
                _report()
                return
        except Exception:
            if not _ifc():
                log.debug("[SELF-IMPROVE] Could not read settings — skipping auto-patch for safety")
                _report()
                return

        # Only runs when an inference broker is available (model loaded).
        try:
            broker = get_broker()
            if broker is None:
                _report()
                return
        except Exception:
            _report()
            return

        try:
            high_recurrence = self.analyze_failures(limit=5, days=14, min_cluster_size=5)
            patchable = [
                f for f in high_recurrence
                if f.get("error") and 'File "' in str(f.get("error", ""))
            ]
            if not patchable:
                _report()
                return
            log.debug(f"[SELF-IMPROVE] Attempting code patches for {len(patchable)} high-recurrence failure(s)")
            for failure in patchable[:2]:  # cap at 2 patches per cycle to limit LLM load
                try:
                    patch = self.generate_code_patch(failure)
                    if not patch.get("ok"):
                        log.debug(f"[SELF-IMPROVE] Patch generation skipped: {patch.get('error', '?')}")
                        continue
                    apply_result = self.apply_code_patch(patch)
                    if apply_result.get("ok"):
                        log.debug(f"[SELF-IMPROVE] Patch applied to {patch.get('file')}: {patch.get('description')}")
                        _patched.append(str(patch.get("file") or "a file"))
                    else:
                        log.debug(f"[SELF-IMPROVE] Patch rejected: {apply_result.get('error', '?')}")
                except Exception as _patch_err:
                    log.debug(f"[SELF-IMPROVE] Patch attempt failed: {_patch_err}")
        except Exception as _chain_err:
            log.debug(f"[SELF-IMPROVE] Patch chain failed: {_chain_err}")
        _report()

    def log_improvement(self, category: str, description: str, area: str = "runtime",
                        code_before: str = "", code_after: str = ""):
        self.memory.log_improvement(category, description, area=area,
                                    code_before=code_before, code_after=code_after)

    def handle_correction(self, original: str, corrected_action: str, _corrected_args: dict = None):
        self.memory.log_correction(_safe_str(original), _safe_str(corrected_action))
        return {"ok": True}

    # ─────────────────────────────────────────────────────────────────────────
    # Analysis
    # ─────────────────────────────────────────────────────────────────────────

    def analyze_failures(self, limit: int = 50, days: int = 7, min_cluster_size: int = 3) -> List[Dict[str, Any]]:
        conn = self.memory._get_connection()
        try:
            since = time.time() - (days * 86400)
            cur = conn.execute(
                """SELECT user_input, command, error, context, occurrence_count, timestamp, id
                   FROM failures
                   WHERE timestamp >= ?
                     AND COALESCE(status, 'open') NOT IN ('resolved', 'closed')
                   ORDER BY occurrence_count DESC, timestamp DESC LIMIT ?""",
                (since, int(limit)),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if min_cluster_size > 1:
                rows = [r for r in rows if (r.get("occurrence_count") or 1) >= min_cluster_size]
            return rows
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def analyze_and_improve(self) -> Dict[str, Any]:
        failures = self.analyze_failures(limit=25, min_cluster_size=1)
        improvements: List[Dict[str, Any]] = []

        existing_descs: set = set()
        try:
            conn = self.memory._get_connection()
            try:
                # Only skip failures already investigated in the last 14 days.
                # Older entries are re-queued so stale failures don't block forever.
                _cutoff = time.time() - (14 * 86400)
                rows = conn.execute(
                    "SELECT description FROM improvements "
                    "WHERE COALESCE(timestamp, ts, 0) > ? "
                    "ORDER BY COALESCE(timestamp, ts, 0) DESC LIMIT 50",
                    (_cutoff,),
                ).fetchall()
                existing_descs = {str(r[0]).strip().lower() for r in rows if r[0]}
            except Exception:
                pass
            finally:
                conn.close()
        except Exception:
            pass

        for f in failures[:10]:
            ui = _safe_str(f.get("user_input"))
            err = _safe_str(f.get("error"))
            if not ui and not err:
                continue
            desc = f"Investigate failure: {ui} → {err}".strip()
            if desc.lower() in existing_descs:
                continue
            improvements.append({"category": "stability", "area": "runtime", "description": desc})

        for imp in improvements[:5]:
            try:
                self.log_improvement(imp["category"], imp["description"], area=imp.get("area", "runtime"))
            except Exception:
                pass

        # Frontier self-repair: when there are NEW (un-investigated) failures and the model
        # is resident, route them through the coding agent (decompose→solve→VERIFY) and
        # PERSIST the verified/candidate fixes as proposal-only goals — so they survive and
        # surface via GET_PROPOSALS. Previously analyze_and_improve only logged 'investigate'
        # stubs that never became anything (the proposals=0 root cause). Propose-only:
        # nothing is auto-applied. Gated so the daemon never thrashes the GGUF/coding agent.
        proposals_made = 0
        if improvements:
            try:
                from eli.cognition import gguf_inference as _gi
                _model_ready = bool(getattr(_gi, "is_loaded", lambda: False)())
            except Exception:
                _model_ready = False
            if _model_ready:
                proposals_made = self._generate_and_persist_fix_proposals(max_items=2)

        try:
            from eli.cognition.persona_updater import update_persona_overlay
            update_persona_overlay(memory=self.memory)
        except Exception:
            pass

        return {"improvements": improvements, "proposals_made": proposals_made}

    def _generate_and_persist_fix_proposals(self, max_items: int = 2) -> int:
        """Run the coding-agent self-repair proposer and persist each result as a
        proposal-only goal (visible via GET_PROPOSALS). Returns the count persisted.
        Best-effort; never raises into the caller."""
        made = 0
        try:
            gen = self.propose_via_agent(max_items=max_items)
            for pr in (gen.get("proposals") or []):
                if not isinstance(pr, dict):
                    continue
                fail = _safe_str(pr.get("failure")).strip()
                if not fail:
                    continue
                verified = bool(pr.get("verified"))
                approach = _safe_str(pr.get("approach")).strip()
                vtag = "verified fix" if verified else "candidate fix"
                try:
                    import hashlib as _hl
                    from eli.planning.goal_store import upsert_goal
                    from eli.planning.goal_models import GoalSpec
                    gid = "selfrepair_" + _hl.sha1(fail.encode("utf-8", "ignore")).hexdigest()[:12]
                    upsert_goal(GoalSpec.from_any({
                        "goal_id": gid,
                        "title": f"Self-repair ({vtag}): {fail[:70]}",
                        "objective": (
                            f"A {vtag} for the recurring failure '{fail[:120]}' is ready"
                            + (f" — approach: {approach[:120]}" if approach else "")
                            + ". Review and apply if sound."
                        ),
                        "priority": 0.6 if verified else 0.45,
                        "autonomy_mode": "proposal_only",
                        "tags": ["self_improve", "verified_fix" if verified else "candidate_fix"],
                        "enabled": True,
                        "status": "active",
                    }))
                    made += 1
                except Exception:
                    continue
        except Exception as exc:
            log.debug("[SELF_IMPROVEMENT] generate/persist proposals failed: %s", exc)
        return made

    # ─────────────────────────────────────────────────────────────────────────
    # Coding-agent route — decompose → solve → VERIFY (propose-only)
    # ─────────────────────────────────────────────────────────────────────────
    def _build_fix_task(self, failure: dict, max_file_chars: int = 4000) -> str:
        """Turn a recorded failure into a coding task for the agent, with the offending
        file inlined as context when the traceback names one in-project."""
        err = _safe_str(failure.get("error", ""))
        ui = _safe_str(failure.get("user_input", ""))
        cmd = _safe_str(failure.get("command", ""))
        file_ref, file_content = "", ""
        m = re.search(r'File "([^"]+\.py)"', err)
        if m:
            cand = Path(m.group(1))
            try:
                cand.relative_to(PROJECT_ROOT)
                if cand.exists() and cand.stat().st_size < max_file_chars * 3:
                    file_content = cand.read_text(encoding="utf-8")[:max_file_chars]
                    file_ref = str(cand.relative_to(PROJECT_ROOT))
            except Exception:
                pass
        parts = [f"Fix the bug that causes this failure: {err[:500]}"]
        if cmd:
            parts.append(f"Triggered by command: {cmd[:150]}")
        if ui:
            parts.append(f"User input: {ui[:150]}")
        if file_content:
            parts.append(f"Correct this file ({file_ref}) and return the fixed version:\n"
                         f"```python\n{file_content}\n```")
        else:
            parts.append("Propose a minimal corrected implementation.")
        return "\n".join(parts)

    def propose_via_agent(self, max_items: int = 3, run_timeout: float = 20.0) -> Dict[str, Any]:
        """Route self-improvement through the CODING AGENT: per recent failure, the
        agent decomposes → solves → VERIFIES a fix (its tree-search + execution gate),
        orchestrated in parallel on the DAG. Propose-only — nothing is applied."""
        failures = [f for f in self.analyze_failures(limit=10, min_cluster_size=1)
                    if _safe_str(f.get("error")) or _safe_str(f.get("user_input"))][:max_items]
        if not failures:
            return {"ok": True, "proposals": [], "reason": "no recent failures to fix"}
        try:
            from eli.core.dag import Task, run_graph
            from eli.coding.agent import CodeAgent
            agent = CodeAgent()

            def _mk(failure):
                def _run(ctx):
                    cr = agent.solve(self._build_fix_task(failure), run_timeout=run_timeout)
                    return {
                        "failure": (_safe_str(failure.get("user_input"))
                                    or _safe_str(failure.get("error")))[:140],
                        "verified": bool(getattr(cr, "solved", False)),
                        "score": round(float(getattr(cr, "score", 0.0) or 0.0), 2),
                        "approach": (getattr(cr, "plan", {}) or {}).get("approach"),
                        "message": getattr(cr, "message", ""),
                        "code": (getattr(cr, "code", "") or "")[:1500],
                    }
                return _run

            tasks = [Task(id=f"fix_{i}", run=_mk(f), critical=False)
                     for i, f in enumerate(failures)]
            report = run_graph(tasks, max_workers=max(2, len(tasks)))
            proposals = [o.result for _tid, o in report.outcomes.items() if o.ok and o.result]
            return {"ok": True, "proposals": proposals, "count": len(proposals),
                    "orchestration": report.to_dict()}
        except Exception as e:
            return {"ok": False, "error": str(e), "proposals": []}

    # ─────────────────────────────────────────────────────────────────────────
    # Code Patching — generate → validate → apply
    # ─────────────────────────────────────────────────────────────────────────

    def generate_code_patch(self, failure: dict, max_file_chars: int = 5000) -> dict:
        """
        Use the inference broker to generate a targeted old→new code patch for a failure.
        Returns {"ok": bool, "file": str, "old": str, "new": str, "description": str}
        """
        err = _safe_str(failure.get("error", ""))
        cmd = _safe_str(failure.get("command", ""))
        ui = _safe_str(failure.get("user_input", ""))

        if not err and not ui:
            return {"ok": False, "error": "Insufficient failure context to generate a repair"}

        # Extract Python file reference from the error traceback
        file_ref = ""
        file_content = ""
        full_src = ""        # complete file text — used to VALIDATE the patch (verbatim + parse)
        file_match = re.search(r'File "([^"]+\.py)"', err)
        if file_match:
            candidate = Path(file_match.group(1))
            try:
                candidate.relative_to(PROJECT_ROOT)
                if candidate.exists() and candidate.stat().st_size < max_file_chars * 3:
                    full_src = candidate.read_text(encoding="utf-8")
                    file_ref = str(candidate.relative_to(PROJECT_ROOT))
                    # Give the model the ENCLOSING SCOPE around the failing line (+ the file's
                    # imports) instead of just the head — the same scope-aware context the code
                    # examiner uses, so it can produce a verbatim, in-scope fix. The deepest
                    # traceback frame for THIS file is the actual error site.
                    _frames = re.findall(
                        rf'File "[^"]*{re.escape(candidate.name)}", line (\d+)', err)
                    _err_line = int(_frames[-1]) if _frames else None
                    try:
                        from eli.runtime.code_examiner import _build_fix_context as _bfc
                        file_content = _bfc(full_src, _err_line)
                    except Exception:
                        file_content = full_src[:max_file_chars]
            except (ValueError, Exception):
                pass

        # Only patch failures we can ground to a REAL in-project file. Without a file
        # from the traceback the model invents a path (observed: phantom api_client.py /
        # command_handler.py for the 11434 / "No commands" errors) and apply_code_patch
        # then fails "File not found". Skip honestly — these are surfaced for goal-based
        # / self-heal handling instead of a hallucinated patch.
        if not file_ref or not file_content:
            return {
                "ok": False,
                "error": "no_groundable_file",
                "reason": ("This failure has no in-project file traceback, so it is not "
                           "code-patchable from its error text — routed to goal/self-heal "
                           "surfacing instead of guessing a file."),
                "failure_ref": f"{ui[:60]} → {err[:60]}",
            }

        prompt_parts = [
            "You are ELI's self-improvement code-patch engine.",
            f"A recurring error has been detected (occurred {failure.get('occurrence_count', 1)}× time(s)).",
            f"Error: {err[:600]}",
        ]
        if cmd:
            prompt_parts.append(f"Command: {cmd[:200]}")
        if ui:
            prompt_parts.append(f"User input: {ui[:200]}")
        if file_content:
            prompt_parts.append(f"\nSource file ({file_ref}):\n```python\n{file_content}\n```")

        prompt_parts += [
            "\nGenerate a minimal, targeted fix. Respond with ONLY valid JSON in this exact format:",
            f'{{"file": "{file_ref}", "old": "exact original code (verbatim)", "new": "corrected replacement", "description": "what this fixes"}}',
            "Rules:",
            f"- 'file' MUST be exactly \"{file_ref}\" — the file shown above; never invent or change the path",
            "- 'old' must be character-for-character identical to text in the file shown above",
            "- 'new' must fix only this specific error",
            "- Make the smallest possible change",
            "- If no safe patch can be generated, return: {\"ok\": false, \"reason\": \"explanation\"}",
        ]

        # Route self-upgrade through the coding engine's long-term bug memory:
        # classify this failure and inject any prior fix for the same bug class
        # so repeated bugs are repaired the way they were before. Guarded.
        try:
            from eli.coding.bug_memory import classify_bug, get_bug_memory
            _dg = classify_bug(traceback_text=err, code=file_content)
            _recalls = get_bug_memory().recall(_dg, limit=2)
            if _recalls:
                _known = "\n".join(f"- ({r.bug_class}, used {r.success_count}×) {r.fix_summary}" for r in _recalls)
                prompt_parts.append(
                    f"\nThis looks like a {_dg.bug_class.value} bug. Prior fixes that worked for "
                    f"this class (reuse the approach where applicable):\n{_known}")
        except Exception as _bm_e:
            log.debug(f"[SELF-IMPROVE] bug-memory recall skipped: {_bm_e}")

        # Validate-and-retry: a patch is only returned once 'old' is a verbatim substring of the
        # real file AND applying it still parses — the SAME pre-flight the code examiner uses, so
        # the autonomous loop stops handing apply_code_patch syntax-broken patches ("Fix failed
        # after retries: corrected code has SyntaxError"). On rejection the specific error is fed
        # back and the model retries. apply_code_patch still import-verifies + auto-reverts after.
        try:
            from eli.runtime.code_examiner import _validate_patch as _vp
        except Exception:
            _vp = None
        _base = "\n".join(prompt_parts)
        _attempts = 3
        _last = "no attempt made"
        try:
            broker = get_broker()
        except Exception as exc:
            return {"ok": False, "error": f"LLM inference unavailable: {exc}"}
        for _i in range(1, _attempts + 1):
            _p = _base if _i == 1 else (
                _base + f"\n\nYour previous attempt FAILED: {_last}. Return corrected JSON — "
                "'old' must be copied EXACTLY (character-for-character) from the code shown.")
            try:
                raw = broker.infer(_p, max_tokens=700, temperature=0.05)
            except Exception as exc:
                _last = f"inference failed: {exc}"
                continue
            json_match = re.search(r'\{[\s\S]+\}', raw or "")
            if not json_match:
                _last = "LLM did not return valid JSON"
                continue
            try:
                patch = json.loads(json_match.group(0))
            except json.JSONDecodeError as exc:
                _last = f"JSON parse failed: {exc}"
                continue
            if patch.get("ok", True) is False and patch.get("reason"):
                return {"ok": False, "error": patch["reason"]}   # explicit decline = terminal
            if not all(k in patch for k in ("file", "old", "new")):
                _last = "Patch JSON missing required fields (file/old/new)"
                continue
            if _vp is not None and full_src:
                _verr = _vp(full_src, patch)
                if _verr:
                    _last = _verr
                    log.debug(f"[SELF-IMPROVE] {file_ref}: attempt {_i}/{_attempts} rejected — {_verr}")
                    continue
            patch["ok"] = True
            patch.setdefault("description", "self-improvement patch")
            patch["failure_ref"] = f"{ui[:60]} → {err[:60]}"
            if _i > 1:
                log.debug(f"[SELF-IMPROVE] {file_ref}: valid patch on attempt {_i}/{_attempts}")
            return patch
        return {"ok": False, "error": f"no valid patch after {_attempts} attempts: {_last}"}

    def apply_code_patch(self, patch: dict, verify: bool = True) -> dict:
        """
        Apply a code patch: replace `old` with `new` in the target file.
        Validates Python syntax before and after writing, then (when ``verify``)
        smoke-imports the patched module in an isolated subprocess so a patch
        that compiles but breaks the module at import time is reverted instead of
        kept. Creates a timestamped backup (plus a canonical `.eli_bak` for
        revert_patch) and reverts on any failure.
        Returns {"ok": bool, "applied": bool, "message": str}
        """
        file_str = (patch.get("file") or "").strip()
        old_code = patch.get("old", "")
        new_code = patch.get("new", "")
        description = patch.get("description", "self-improvement patch")

        if not file_str or not old_code or not new_code:
            return {"ok": False, "applied": False, "message": "Patch missing required fields (file/old/new)"}
        if old_code == new_code:
            return {"ok": False, "applied": False, "message": "old and new are identical — no change"}

        # Resolve path
        p = Path(file_str)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p = p.resolve()

        # Safety guard — only patch files inside project
        try:
            p.relative_to(PROJECT_ROOT)
        except ValueError:
            return {"ok": False, "applied": False, "message": f"Refused: {p} is outside project root"}

        if not p.exists():
            return {"ok": False, "applied": False, "message": f"File not found: {p}"}
        if p.suffix != ".py":
            return {"ok": False, "applied": False, "message": "Only .py files can be auto-patched"}

        try:
            content = p.read_text(encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "applied": False, "message": f"Read error: {exc}"}

        if old_code not in content:
            return {"ok": False, "applied": False,
                    "message": "old_code not found verbatim in file — patch is stale or incorrect"}

        new_content = content.replace(old_code, new_code, 1)

        # Validate new syntax
        try:
            ast.parse(new_content)
        except SyntaxError as exc:
            return {"ok": False, "applied": False,
                    "message": f"Patch introduces syntax error at line {exc.lineno}: {exc.msg}"}

        # Pre-patch import baseline (differential verification). Only attribute a
        # broken import to THIS patch if the module imported cleanly *before* it;
        # this tolerates pre-existing missing optional deps without false reverts.
        verify_dotted = _dotted_module_for_path(p) if verify else None
        pre_import_ok = False
        if verify_dotted:
            pre_import_ok, _ = _smoke_import_module(verify_dotted)

        # Backup — timestamped (keeps history so a second patch can't clobber the
        # only undo) plus a canonical `.eli_bak` pointing at the latest, which
        # revert_patch() restores from.
        ts_backup = p.with_suffix(f".py.eli_bak.{int(time.time())}")
        backup = p.with_suffix(".py.eli_bak")
        try:
            shutil.copy2(str(p), str(ts_backup))
            shutil.copy2(str(p), str(backup))
        except Exception as exc:
            return {"ok": False, "applied": False, "message": f"Could not create backup: {exc}"}

        # Write
        try:
            p.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            if backup.exists():
                shutil.copy2(str(backup), str(p))
            return {"ok": False, "applied": False, "message": f"Write failed (backup restored): {exc}"}

        # Compile-check
        try:
            import py_compile
            py_compile.compile(str(p), doraise=True)
        except Exception as exc:
            if backup.exists():
                shutil.copy2(str(backup), str(p))
            return {"ok": False, "applied": False,
                    "message": f"Compile error after patch (reverted): {exc}"}

        # Behavioural verification — a patch can compile and still break the
        # module at import time (unresolved name, broken top-level statement,
        # bad import). For importable `eli` modules that imported cleanly before
        # the patch, smoke-import the patched file in an isolated subprocess and
        # revert if it no longer loads.
        if verify_dotted and pre_import_ok:
            imp_ok, imp_detail = _smoke_import_module(verify_dotted)
            if not imp_ok:
                if backup.exists():
                    shutil.copy2(str(backup), str(p))
                log.debug(f"[SELF-IMPROVE] Patch reverted — import verification failed: {imp_detail}")
                return {"ok": False, "applied": False,
                        "message": f"Patch broke module import (reverted): {imp_detail}"}

        # Log the applied patch
        try:
            rel_path = str(p.relative_to(PROJECT_ROOT))
            self.log_improvement(
                "code_patch",
                f"Patched {rel_path}: {description}",
                area="code",
                code_before=old_code[:500],
                code_after=new_code[:500],
            )
            # Also record in code_patches table
            conn = self.memory._get_connection()
            try:
                _ensure_failure_tables(conn)
                conn.execute(
                    "INSERT INTO code_patches (file_path, description, old_code, new_code, status, timestamp, failure_ref) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (rel_path, description, old_code[:1000], new_code[:1000], "applied",
                     time.time(), patch.get("failure_ref", ""))
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

        rel = str(p.relative_to(PROJECT_ROOT))
        log.debug(f"[SELF-IMPROVE] Patch applied: {rel} — {description}")
        return {
            "ok": True,
            "applied": True,
            "file": rel,
            "backup": str(backup),
            "message": f"Patch applied to {p.name}: {description}",
        }

    def revert_patch(self, file_path: str) -> dict:
        """Restore the most recent .eli_bak backup for a file."""
        p = Path(file_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p = p.resolve()
        backup = p.with_suffix(".py.eli_bak")
        if not backup.exists():
            return {"ok": False, "message": f"No backup found for {p.name}"}
        try:
            shutil.copy2(str(backup), str(p))
            return {"ok": True, "message": f"Reverted {p.name} from backup"}
        except Exception as exc:
            return {"ok": False, "message": f"Revert failed: {exc}"}

    def run_patch_cycle(self, max_patches: int = 3, dry_run: bool = False) -> dict:
        """
        Full automated patch cycle:
        1. Analyze recurring failures (min 2 occurrences)
        2. For each, ask LLM to generate a specific code fix
        3. Validate syntax and apply the fix
        4. Report results

        Returns a detailed dict with per-patch outcomes.
        """
        failures = self.analyze_failures(limit=20, days=14, min_cluster_size=2)

        results: Dict[str, Any] = {
            "failures_analyzed": len(failures),
            "patches_generated": 0,
            "patches_applied": 0,
            "patches_skipped": 0,
            "patches_failed": 0,
            "dry_run": dry_run,
            "details": [],
        }

        if not failures:
            results["summary"] = "No recurring failures found (need ≥2 occurrences). System appears stable."
            return results

        for failure in failures[:max_patches]:
            err_preview = (failure.get("error") or failure.get("user_input") or "?")[:80]
            count = failure.get("occurrence_count", 1)

            try:
                patch = self.generate_code_patch(failure)
                if not patch.get("ok"):
                    reason = patch.get("error", "unknown")
                    results["patches_skipped"] += 1
                    results["details"].append({
                        "failure": err_preview,
                        "count": count,
                        "status": "patch_generation_failed",
                        "reason": reason,
                    })
                    log.debug(f"[SELF-IMPROVE] Skipped (generation failed): {err_preview[:60]} — {reason}")
                    continue

                results["patches_generated"] += 1

                if dry_run:
                    results["details"].append({
                        "failure": err_preview,
                        "count": count,
                        "status": "dry_run",
                        "patch": {
                            "file": patch.get("file"),
                            "description": patch.get("description"),
                            "old_preview": (patch.get("old") or "")[:80],
                            "new_preview": (patch.get("new") or "")[:80],
                        },
                    })
                    continue

                apply_result = self.apply_code_patch(patch)
                if apply_result.get("applied"):
                    results["patches_applied"] += 1
                    results["details"].append({
                        "failure": err_preview,
                        "count": count,
                        "status": "applied",
                        "file": apply_result.get("file"),
                        "message": apply_result.get("message"),
                    })
                else:
                    results["patches_failed"] += 1
                    results["details"].append({
                        "failure": err_preview,
                        "count": count,
                        "status": "apply_failed",
                        "reason": apply_result.get("message", "unknown"),
                    })
                    log.debug(f"[SELF-IMPROVE] Apply failed: {apply_result.get('message')}")

            except Exception as exc:
                results["patches_failed"] += 1
                results["details"].append({
                    "failure": err_preview,
                    "count": count,
                    "status": "exception",
                    "reason": str(exc)[:120],
                })
                log.debug(f"[SELF-IMPROVE] Exception during patch cycle: {exc}")

        applied = results["patches_applied"]
        total = results["patches_generated"]
        results["summary"] = (
            f"Patch cycle complete: {applied}/{total} patches applied "
            f"({results['patches_failed']} failed, {results['patches_skipped']} skipped). "
            f"Analyzed {len(failures)} recurring failures."
        )
        log.debug(f"[SELF-IMPROVE] {results['summary']}")
        return results

    def list_applied_patches(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return history of applied code patches from the agent DB."""
        conn = self.memory._get_connection()
        try:
            _ensure_failure_tables(conn)
            rows = conn.execute(
                "SELECT id, file_path, description, status, timestamp FROM code_patches "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [
                {"id": r[0], "file": r[1], "description": r[2],
                 "status": r[3], "timestamp": r[4]}
                for r in rows
            ]
        except Exception:
            return []
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Plugin stub generators
    # ─────────────────────────────────────────────────────────────────────────

    def _generate_plugin_name(self, text):
        return self.generate_plugin_name(text)

    def _generate_plugin_stub(self, name, description="", examples=None):
        return self.generate_plugin_stub(name, description=description, examples=examples)

    def generate_plugin_name(self, idea: str) -> str:
        base = "".join(ch.lower() if ch.isalnum() else "_" for ch in (idea or "plugin").strip())
        base = "_".join([p for p in base.split("_") if p])
        if not base:
            base = "plugin"
        if base[0].isdigit():
            base = "p_" + base
        return base

    def generate_plugin_stub(self, name: str, description: str = "", examples: list = None) -> str:
        mod = self.generate_plugin_name(name)
        desc = description or "Auto-generated plugin"
        examples_str = f"    examples = {examples!r}\n" if examples else ""
        return (
            f"# Auto-generated plugin: {mod}\n"
            "from eli.plugins.base import BasePlugin\n"
            "from eli.memory import get_memory\n\n"
            f"class Plugin(BasePlugin):\n"
            f"    name = '{mod}'\n"
            f"    description = '{desc}'\n"
            f"{examples_str}"
            "\n"
            "    def run(self, args: dict) -> dict:\n"
            "        try:\n"
            f"            # Plugin logic for: {desc}\n"
            "            query = args.get('query', args.get('text', ''))\n"
            "            mem = get_memory()\n"
            "            results = mem.recall_memory(query, limit=5) if query else []\n"
            "            context = '; '.join(r.get('text', '') for r in results[:3])\n"
            "            return {\n"
            "                'ok': True,\n"
            "                'content': f'[{mod}] Processed: {query}. Context: {context or \"none\"}',\n"
            "                'response': f'[{mod}] Done.',\n"
            "                'results': results,\n"
            "            }\n"
            "        except Exception as e:\n"
            "            return {'ok': False, 'error': str(e), 'content': f'Plugin error: {e}'}\n"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Background loop
    # ─────────────────────────────────────────────────────────────────────────

    def start_self_improvement_loop(self, interval_hours: int = 24):
        def loop():
            # Mark this daemon thread's model calls BACKGROUND so they yield to a
            # foreground turn (cooperative abort) and are token-capped — ambient
            # self-improvement must never hold the model lock against the user.
            try:
                from eli.cognition.gguf_inference import set_background_inference as _set_bg
                _set_bg(True)
            except Exception:
                pass
            while True:
                try:
                    self.analyze_and_improve()
                except Exception as _exc:
                    log.warning("[SELF_IMPROVEMENT] analyze_and_improve error: %s", _exc)
                time.sleep(interval_hours * 3600)

        threading.Thread(target=loop, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singletons
# ─────────────────────────────────────────────────────────────────────────────

# ── Self-heal notices (recurring-error → proactive conversation surface) ──────
# When an error recurs ≥5× (flag) or ≥10× (act + report), a user-facing notice is
# queued here. The engine pops the most pressing one at the start of a conversational
# turn and mentions it — so ELI raises recurring problems with the user himself and
# reports what he tried, instead of failing silently.
def _self_heal_notices_path() -> Path:
    return PROJECT_ROOT / "artifacts" / "runtime" / "self_heal_notices.json"


def _read_notices() -> List[Dict[str, Any]]:
    try:
        p = _self_heal_notices_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
    except Exception:
        pass
    return []


def _push_self_heal_notice(notice: Dict[str, Any]) -> None:
    """Queue a user-facing self-heal notice (deduped by error_type+stage). Never raises."""
    try:
        p = _self_heal_notices_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = _read_notices()
        key = (notice.get("error_type"), notice.get("stage"))
        data = [n for n in data if (n.get("error_type"), n.get("stage")) != key]
        notice["ts"] = time.time()
        data.append(notice)
        p.write_text(json.dumps(data[-12:], indent=2), encoding="utf-8")
    except Exception:
        pass


def consume_self_heal_notice() -> Optional[Dict[str, Any]]:
    """Pop the most pressing un-surfaced notice (highest count, then most recent). The
    engine calls this once per conversational turn. Never raises."""
    try:
        data = _read_notices()
        if not data:
            return None
        data.sort(key=lambda n: (int(n.get("count", 0)), float(n.get("ts", 0))), reverse=True)
        top, rest = data[0], data[1:]
        _self_heal_notices_path().write_text(json.dumps(rest, indent=2), encoding="utf-8")
        return top
    except Exception:
        return None


_self_engine: Optional[SelfImprovementEngine] = None


def get_self_improvement() -> SelfImprovementEngine:
    global _self_engine
    if _self_engine is None:
        _self_engine = SelfImprovementEngine(memory=get_agent_memory())
    return _self_engine


def run_improvement_cycle() -> Dict[str, Any]:
    return get_self_improvement().analyze_and_improve()


def run_patch_cycle(max_patches: int = 3, dry_run: bool = False) -> Dict[str, Any]:
    return get_self_improvement().run_patch_cycle(max_patches=max_patches, dry_run=dry_run)
