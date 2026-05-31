from __future__ import annotations

import ast
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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

        # Auto-trigger improvement analysis when an error pattern recurs 5× (and every 5× after)
        if new_count >= 5 and new_count % 5 == 0:
            log.debug(f"[SELF-IMPROVE] Recurring error pattern detected ({new_count}×) — auto-triggering capability analysis")
            threading.Thread(target=self._background_analyze, daemon=True).start()

    def _background_analyze(self) -> None:
        """Run analyze_and_improve then attempt code patches for high-recurrence failures."""
        try:
            result = self.analyze_and_improve()
            imps = result.get("improvements", [])
            if imps:
                log.debug(f"[SELF-IMPROVE] Auto-analysis complete: {len(imps)} proposal(s) generated")
            else:
                log.debug("[SELF-IMPROVE] Auto-analysis complete: no new proposals")
        except Exception as _ae:
            log.debug(f"[SELF-IMPROVE] Auto-analysis failed: {_ae}")
            return

        # Attempt code patches for failures with file tracebacks and high recurrence.
        # Gated behind auto_patch_enabled (default off) so patches never apply without
        # explicit user opt-in via settings.json.
        try:
            _settings = json.loads((PROJECT_ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
            if not _settings.get("auto_patch_enabled", False):
                log.debug("[SELF-IMPROVE] auto_patch_enabled is off — patch proposals logged but not applied")
                return
        except Exception:
            log.debug("[SELF-IMPROVE] Could not read settings — skipping auto-patch for safety")
            return

        # Only runs when an inference broker is available (model loaded).
        try:
            broker = get_broker()
            if broker is None:
                return
        except Exception:
            return

        try:
            high_recurrence = self.analyze_failures(limit=5, days=14, min_cluster_size=5)
            patchable = [
                f for f in high_recurrence
                if f.get("error") and 'File "' in str(f.get("error", ""))
            ]
            if not patchable:
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
                    else:
                        log.debug(f"[SELF-IMPROVE] Patch rejected: {apply_result.get('error', '?')}")
                except Exception as _patch_err:
                    log.debug(f"[SELF-IMPROVE] Patch attempt failed: {_patch_err}")
        except Exception as _chain_err:
            log.debug(f"[SELF-IMPROVE] Patch chain failed: {_chain_err}")

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

        try:
            from eli.cognition.persona_updater import update_persona_overlay
            update_persona_overlay(memory=self.memory)
        except Exception:
            pass

        return {"improvements": improvements}

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
        file_match = re.search(r'File "([^"]+\.py)"', err)
        if file_match:
            candidate = Path(file_match.group(1))
            try:
                candidate.relative_to(PROJECT_ROOT)
                if candidate.exists() and candidate.stat().st_size < max_file_chars * 3:
                    file_content = candidate.read_text(encoding="utf-8")[:max_file_chars]
                    file_ref = str(candidate.relative_to(PROJECT_ROOT))
            except (ValueError, Exception):
                pass

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
            '{"file": "relative/path/to/file.py", "old": "exact original code (verbatim)", "new": "corrected replacement", "description": "what this fixes"}',
            "Rules:",
            "- 'old' must be character-for-character identical to text in the file",
            "- 'new' must fix only this specific error",
            "- Make the smallest possible change",
            "- If no safe patch can be generated, return: {\"ok\": false, \"reason\": \"explanation\"}",
        ]

        try:
            broker = get_broker()
            raw = broker.infer("\n".join(prompt_parts), max_tokens=600, temperature=0.05)
            # Extract JSON from response (model may wrap it in markdown)
            json_match = re.search(r'\{[\s\S]+\}', raw)
            if not json_match:
                return {"ok": False, "error": "LLM did not return valid JSON"}
            patch = json.loads(json_match.group(0))
            if not patch.get("ok", True) is False and patch.get("reason"):
                return {"ok": False, "error": patch["reason"]}
            if not all(k in patch for k in ("file", "old", "new")):
                return {"ok": False, "error": "Patch JSON missing required fields (file/old/new)"}
            patch["ok"] = True
            patch.setdefault("description", "self-improvement patch")
            patch["failure_ref"] = f"{ui[:60]} → {err[:60]}"
            return patch
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"JSON parse failed: {exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"LLM inference failed: {exc}"}

    def apply_code_patch(self, patch: dict) -> dict:
        """
        Apply a code patch: replace `old` with `new` in the target file.
        Validates Python syntax before and after writing.
        Creates a .eli_bak backup and reverts on any failure.
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

        # Backup
        backup = p.with_suffix(".py.eli_bak")
        try:
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
