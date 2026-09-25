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
from eli.memory import Memory


from eli.utils.log import get_logger
log = get_logger(__name__)

from eli.runtime.self_maintenance_config import (
    ANALYSIS_MIN_CLUSTER,
    DEFAULT_ANALYSIS_DAYS,
    PATCH_MIN_CLUSTER,
)

try:
    from eli.core.paths import canonical_root
    PROJECT_ROOT = canonical_root(Path(__file__).resolve().parents[2])
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]


_PROTECTED_PATCH_PATHS = {
    "eli/runtime/security.py",
    "eli/core/netguard.py",
    "eli/core/full_control.py",
    "eli/runtime/approval_engine.py",
    "eli/runtime/self_improvement.py",
    "eli/runtime/deterministic_grounding_gate.py",
    "eli/execution/shell_gate.py",        # shell denylist (extracted from executor)
    "eli/runtime/authority_gate.py",      # action allow/check gate
    "eli/execution/route_authority.py",   # routing authority
    "eli/runtime/persistence_gate.py",    # upstream action/persistence gate
    "eli/runtime/evidence_ledger.py",     # the record calibration and reliability are judged from
    "eli/runtime/lessons.py",             # decides which lessons survive
    "eli/runtime/failure_taxonomy.py",    # classifies what failed
}
# A candidate may change the code under test, never what tests it or what counts as passing.
_PROTECTED_PATCH_PREFIXES = ("tests/", "tools/eval/", "conftest.py", "pytest.ini")


def is_protected_patch_path(p: Path) -> bool:
    """True when `p` is one of ELI's own safety guardrail files — must never
    be auto-patched, by self-improvement's autonomous path or a user-triggered
    fix/improve request (FIX_FILE). Only matches paths inside the project
    source root; a user's own unrelated file is never "protected" by this.
    Env-extensible via ELI_PROTECTED_PATCH_PATHS (comma-separated posix paths).
    """
    try:
        root = _patch_root()
        rel = Path(p).resolve().relative_to(root).as_posix()
    except Exception:
        return False
    protected = _PROTECTED_PATCH_PATHS | {
        x.strip() for x in os.environ.get("ELI_PROTECTED_PATCH_PATHS", "").split(",") if x.strip()
    }
    return rel in protected or rel.startswith(_PROTECTED_PATCH_PREFIXES)


def _patch_root() -> Path:
    """Tree where self-improvement may read/write Python source."""
    from eli.core.paths import source_root
    return source_root()


def _safe_str(x: Any) -> str:
    try:
        return "" if x is None else str(x)
    except Exception:
        return ""


def _dotted_module_for_path(p: Path) -> Optional[str]:
    """Return the importable dotted module name for a project .py file, or None
    if it isn't an importable module under the `eli` package."""
    try:
        rel = p.resolve().relative_to(_patch_root())
    except Exception:
        return None
    parts = list(rel.parts)
    if not parts or parts[0] != "eli" or not parts[-1].endswith(".py"):
        return None
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _reload_patched_module(dotted: Optional[str]) -> bool:
    """Evict cached module(s) and re-import so disk patches affect this process."""
    if not dotted:
        return False
    import importlib

    prefix = dotted + "."
    for name in list(sys.modules):
        if name == dotted or name.startswith(prefix):
            sys.modules.pop(name, None)
    try:
        importlib.import_module(dotted)
        return True
    except Exception as exc:
        log.debug("[SELF-IMPROVE] post-patch reload failed for %s: %s", dotted, exc)
        return False


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


def _run_targeted_tests(module_path: Path, timeout: float = 120.0) -> Tuple[bool, bool, str]:
    """CI-grade verification: run the tests most related to a just-patched module
    (`pytest -k <module-stem>`). Returns (ran, passed, detail):

      • ran=False  → no matching tests, a timeout, or an infra error. Never a false revert,
                     but the patch is reported as unverified (ELI_SELFPATCH_REQUIRE_TESTS=1
                     reverts it instead).
      • ran=True, passed=False → a genuine regression: the caller reverts.

    pytest exit codes: 0 all-pass, 1 failures, 5 no-tests-collected."""
    try:
        stem = module_path.stem
        if not stem or stem in ("__init__",):
            return (False, True, "no test target")
        base = [sys.executable, "-m", "pytest", "tests/", "-k", stem,
                "-p", "no:cacheprovider", "-q"]
        co = subprocess.run(base + ["--collect-only"], cwd=str(PROJECT_ROOT),
                            capture_output=True, text=True, timeout=60)
        if co.returncode == 5:
            return (False, True, "no matching tests")
        proc = subprocess.run(base + ["-x"], cwd=str(PROJECT_ROOT),
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            return (True, True, "targeted tests passed")
        if proc.returncode == 5:
            return (False, True, "no matching tests")
        tail = "\n".join((proc.stdout or "").strip().splitlines()[-6:])
        return (True, False, tail or "targeted tests failed")
    except subprocess.TimeoutExpired:
        return (False, True, "targeted test run timed out — tolerated")
    except Exception as exc:
        return (False, True, f"targeted test infra error — tolerated: {exc}")


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
    _ensure_columns(conn, "code_patches", {
        "hypothesis": "TEXT", "verdict": "TEXT", "results": "TEXT", "cost_s": "REAL", "parent_id": "INTEGER",
    })
    conn.commit()



_WORKSPACE_DIRS = ("eli", "api", "tests", "tools", "config")
_WORKSPACE_FILES = ("pytest.ini", "pyproject.toml", "conftest.py")
_REPLAYABLE_ACTIONS = frozenset({"DATE", "TIME", "GPU_STATUS", "RUNTIME_STATUS", "MEMORY_STATUS", "MEMORY_STATS",
                                 "SYSTEM_STATUS", "CPU_USAGE", "LIST_DIR", "EXPLAIN_MEMORY_RUNTIME", "IMAGE_STATUS"})


def failure_capsule(action: str, args: Any, result: Any, *, request_id: str = "") -> Dict[str, Any]:
    """Everything needed to look at a failure again: input, versions, model, error class and the error itself."""
    from eli.runtime.failure_taxonomy import classify
    err = ""
    if isinstance(result, dict):
        err = str(result.get("error") or result.get("content") or "")[:500]
    model = ""
    try:
        from eli.core.paths import get_paths
        snap = json.loads((Path(get_paths().artifacts_dir) / "runtime_snapshot.json").read_text(encoding="utf-8"))
        model = str(snap.get("model_name") or "")
    except Exception:
        model = ""
    try:
        from importlib.metadata import version
        eli_version = version("eli-v2.0")
    except Exception:
        eli_version = ""
    return {"action": str(action or "").upper(), "args": args if isinstance(args, dict) else {}, "error": err,
            "classification": classify(err, command=str(action or "")), "eli_version": eli_version, "model": model,
            "python": sys.version.split()[0], "request_id": request_id, "captured_at": time.time()}


def capsule_reproducer(capsule: Dict[str, Any]) -> Optional[List[str]]:
    """A command that re-runs the failed action and exits non-zero when it fails again, or None when replay is unsafe."""
    action = str(capsule.get("action") or "").upper()
    if action not in _REPLAYABLE_ACTIONS:
        return None
    code = ("import json,sys;from eli.execution.executor_enhanced import execute;"
            f"r=execute({action!r}, json.loads({json.dumps(json.dumps(capsule.get('args') or {}))}));"
            "sys.exit(0 if isinstance(r, dict) and r.get('ok') else 1)")
    return [sys.executable, "-c", code]


def _make_workspace(root: Path, dest: Path) -> Path:
    """A working copy of the source tree. Files are hard-linked, so it is instant and costs no space until one is changed."""
    def link(src: str, dst: str) -> None:
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.eli_bak", "artifacts", "models", "*.gguf")
    for d in _WORKSPACE_DIRS:
        if (root / d).is_dir():
            shutil.copytree(root / d, dest / d, ignore=skip, copy_function=link, symlinks=True)
    for f in _WORKSPACE_FILES:
        if (root / f).is_file():
            link(str(root / f), str(dest / f))
    return dest


def _change_in_workspace(path: Path, old: str, new: str) -> bool:
    """Replace text in a workspace file without touching the original it is linked to."""
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.unlink()
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def _run_cmd(cmd: List[str], cwd: Path, timeout: float) -> Dict[str, Any]:
    env = dict(os.environ, PYTHONPATH=str(cwd), ELI_TEST_MODE="1", PYTHONDONTWRITEBYTECODE="1")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "seconds": round(time.time() - t0, 1), "failed": []}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "seconds": round(time.time() - t0, 1), "failed": []}
    failed = sorted(set(re.findall(r"^FAILED (\S+)", proc.stdout or "", re.M)))
    if proc.returncode == 5:
        status = "no_tests"
    elif proc.returncode in (0, 1):
        status = "ok" if proc.returncode == 0 else "failed"
    else:
        status = "error"
    return {"status": status, "returncode": proc.returncode, "seconds": round(time.time() - t0, 1), "failed": failed,
            "tail": "\n".join((proc.stdout or proc.stderr or "").strip().splitlines()[-4:])}


def compare_runs(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> str:
    """fixed, regression, unchanged or inconclusive. A run that did not really run proves nothing either way."""
    if baseline["status"] in ("timeout", "error", "no_tests") or candidate["status"] in ("timeout", "error", "no_tests"):
        return "inconclusive"
    before, after = set(baseline["failed"]), set(candidate["failed"])
    if after - before:
        return "regression"
    if before - after:
        return "fixed"
    if baseline["returncode"] != candidate["returncode"]:
        return "fixed" if candidate["returncode"] == 0 else "regression"
    return "unchanged"

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
        # Guard: never persist a unit-test mock as a real failure. When a test patches subprocess.run,
        # the executor's stdout concat gives a MagicMock repr ("<MagicMock name='run().stdout.__add__()'
        # ...>") that leaked into the live failures DB and polluted SELF_ANALYZE. Drop mock reprs at the
        # write source so a test-isolation slip can't pollute real failures.
        import re as _re_mock
        if _re_mock.search(r"<\s*(?:Magic)?Mock\b|(?:Magic)?Mock\s+name=|\bMock\s+id=0x",
                           f"{error} {input_text}"):
            return
        ctx = dict(context or {}) if isinstance(context, dict) else (context or {})
        if isinstance(ctx, dict) and ctx.get("action") and "capsule" not in ctx:
            try:
                ctx["capsule"] = failure_capsule(ctx.get("action"), ctx.get("args"), ctx.get("result") or {"error": error})
            except Exception:
                log.debug("failure capsule not built", exc_info=True)
        now = time.time()
        try:
            self.memory.log_failure(input_text, error=error, confidence=confidence, context=ctx)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
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

        # Escalation clauses (a recurring error is raised with the user): >=5x is "notice" (flag it
        # in the next conversation turn); >=10x is "act" (also attempt a self-resolution and report
        # the outcome). Skip user-input/clarification cases (fault=False); they aren't real faults.
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
                    apply_result = self.apply_autonomously(patch, failure)
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

    def failures_outside_window(self, days: int = 7) -> Dict[str, Any]:
        """Open failures OLDER than the analysis window.

        `analyze_failures` looks back `days` and says nothing about what it did not
        look at. Live at 2.3.10 that produced two self-reports contradicting each
        other seconds apart: `self improve` reported "failures_inspected: 3" and
        printed the newest error, while `analyse yourself` reported "0 recent
        issues — No recent failures found." Both were correct — the seven stored
        failures were 9.8 to 15.1 days old, outside SELF_ANALYZE's 7-day window —
        and together they read as ELI contradicting itself.

        Saying "none in the last 7 days" is true. Saying "no failures found" when
        seven are open is not.
        """
        conn = self.memory._get_connection()
        try:
            since = time.time() - (days * 86400)
            row = conn.execute(
                """SELECT COUNT(*), MIN(timestamp)
                   FROM failures
                   WHERE timestamp < ?
                     AND COALESCE(status, 'open') NOT IN ('resolved', 'closed')""",
                (since,),
            ).fetchone()
            count = int((row or [0])[0] or 0)
            oldest_ts = (row or [0, None])[1]
            oldest_days = ((time.time() - oldest_ts) / 86400.0) if oldest_ts else 0.0
            return {"count": count, "oldest_days": round(oldest_days, 1)}
        except Exception as exc:
            log.debug("[SELF_IMPROVE] could not count older failures: %s", exc)
            return {"count": 0, "oldest_days": 0.0}
        finally:
            try:
                conn.close()
            except Exception:
                log.debug("suppressed exception", exc_info=True)

    def analyze_failures(
        self,
        limit: int = 50,
        days: int = DEFAULT_ANALYSIS_DAYS,
        min_cluster_size: int = ANALYSIS_MIN_CLUSTER,
    ) -> List[Dict[str, Any]]:
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
                log.debug("suppressed exception", exc_info=True)

    def analyze_and_improve(self, propose: bool = True) -> Dict[str, Any]:
        """Cluster recent failures and (optionally) generate fix proposals.

        ``propose=False`` keeps this to pure analysis. Proposal generation runs
        the coding agent across a thread pool and blocks on live inference —
        fine on a daemon tick, fatal on the shutdown path, where it hung the
        window close until the user pressed Ctrl-C twice.
        """
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
                log.debug("suppressed exception", exc_info=True)
            finally:
                conn.close()
        except Exception:
            log.debug("suppressed exception", exc_info=True)

        for f in failures[:10]:
            ui = _safe_str(f.get("user_input"))
            err = _safe_str(f.get("error"))
            if not ui and not err:
                continue
            desc = f"Investigate failure: {ui} → {err}".strip()
            if desc.lower() in existing_descs:
                continue
            # Classified from the failure itself. This was a hardcoded stability/runtime for every
            # proposal, so the improvements table carried no signal to prioritise or filter on: a
            # CUDA OOM and a wrong dict key were indistinguishable.
            try:
                from eli.runtime.failure_taxonomy import classify
                tags = classify(err, _safe_str(f.get("command")), ui)
            except Exception:
                log.debug("failure classification unavailable", exc_info=True)
                tags = {"category": "stability", "area": "runtime",
                        "severity": "unknown", "exception": ""}
            improvements.append({
                "category": tags["category"],
                "area": tags["area"],
                "severity": tags["severity"],
                "exception": tags.get("exception", ""),
                "description": desc,
            })

        # Real defects before environmental noise. Only five are logged per pass, and a deliberately
        # offline machine can fill that slice with network failures, burying the TypeError that is an
        # actual bug. Order is stable within each group, so the newest actionable failure still leads.
        try:
            from eli.runtime.failure_taxonomy import is_actionable
            improvements.sort(key=lambda i: not is_actionable(i.get("category", "")))
        except Exception:
            log.debug("could not prioritise improvements", exc_info=True)

        for imp in improvements[:5]:
            try:
                self.log_improvement(imp["category"], imp["description"], area=imp.get("area", "runtime"))
            except Exception:
                log.debug("suppressed exception", exc_info=True)

        # Frontier self-repair: with new failures and a model resident, route them through the coding
        # agent (decompose, solve, verify) and keep the fixes as proposal-only goals that surface via
        # GET_PROPOSALS. It used to log 'investigate' stubs that went nowhere (why proposals stayed 0).
        # Nothing is auto-applied, and it's gated so the daemon can't thrash the GGUF.
        proposals_made = 0
        if improvements and propose:
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
            log.debug("suppressed exception", exc_info=True)

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
                cand.relative_to(_patch_root())
                if cand.exists() and cand.stat().st_size < max_file_chars * 3:
                    file_content = cand.read_text(encoding="utf-8")[:max_file_chars]
                    file_ref = str(cand.relative_to(_patch_root()))
            except Exception:
                log.debug("suppressed exception", exc_info=True)
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

    def _try_deterministic_patch(self, failure: dict) -> dict:
        """Apply a known rule-based fix when the failure pattern is unambiguous."""
        try:
            from eli.runtime.deterministic_failure_patches import propose_deterministic_patch
            patch = propose_deterministic_patch(failure)
            return patch if patch else {"ok": False}
        except Exception as exc:
            log.debug("[SELF-IMPROVE] deterministic patch lookup failed: %s", exc)
            return {"ok": False, "error": str(exc)}

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
                candidate.relative_to(_patch_root())
                if candidate.exists() and candidate.stat().st_size < max_file_chars * 3:
                    full_src = candidate.read_text(encoding="utf-8")
                    file_ref = str(candidate.relative_to(_patch_root()))
                    # Give the model the enclosing scope around the failing line (plus the file's imports) instead
                    # of just the head, the same scope-aware context the code examiner uses, so it can write a
                    # verbatim in-scope fix. The deepest traceback frame for this file is the error site.
                    _frames = re.findall(
                        rf'File "[^"]*{re.escape(candidate.name)}", line (\d+)', err)
                    _err_line = int(_frames[-1]) if _frames else None
                    try:
                        from eli.runtime.code_examiner import _build_fix_context as _bfc
                        file_content = _bfc(full_src, _err_line)
                    except Exception:
                        file_content = full_src[:max_file_chars]
            except (ValueError, Exception):
                log.debug("suppressed exception", exc_info=True)

        # Only patch failures we can ground to a real in-project file. Without a file from the
        # traceback the model invents a path (phantom api_client.py / command_handler.py for the 11434
        # and "No commands" errors) and apply_code_patch fails "File not found". Skip honestly, these go
        # to goal-based/self-heal handling instead of a hallucinated patch.
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

        # Validate-and-retry: a patch is returned only once 'old' is a verbatim substring of the real
        # file and applying it still parses (the same pre-flight the code examiner uses), so the
        # autonomous loop stops handing apply_code_patch syntax-broken patches. On rejection the specific
        # error is fed back and the model retries. apply_code_patch still import-verifies and
        # auto-reverts after.
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
        _root = _patch_root()
        if not p.is_absolute():
            p = _root / p
        p = p.resolve()

        # Safety guard — only patch files inside source root
        try:
            p.relative_to(_root)
        except ValueError:
            return {"ok": False, "applied": False, "message": f"Refused: {p} is outside source root"}

        # Protected-path guard: the self-improver must never auto-patch the safety guardrails (or
        # itself), since a faulty or adversarial patch to them would disable the gates that contain it
        # (network fail-closed, shell denylist, Full Control, grounding, the patcher). Shared with
        # FIX_FILE (executor_enhanced.py) so both patch paths enforce the same list, see
        # is_protected_patch_path.
        if is_protected_patch_path(p):
            try:
                _rel = p.relative_to(_root).as_posix()
            except Exception:
                _rel = p.as_posix()
            return {"ok": False, "applied": False,
                    "message": f"Refused: {_rel} is a protected safety guardrail and cannot be auto-patched"}

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

        # Behavioural verification: a patch can compile and still break the module at import time
        # (unresolved name, broken top-level statement, bad import). For importable `eli` modules that
        # imported cleanly before the patch, smoke-import the patched file in an isolated subprocess and
        # revert if it no longer loads.
        if verify_dotted and pre_import_ok:
            imp_ok, imp_detail = _smoke_import_module(verify_dotted)
            if not imp_ok:
                if backup.exists():
                    shutil.copy2(str(backup), str(p))
                log.debug(f"[SELF-IMPROVE] Patch reverted — import verification failed: {imp_detail}")
                return {"ok": False, "applied": False,
                        "message": f"Patch broke module import (reverted): {imp_detail}"}

        # Targeted regression (CI-grade): a patch can compile and import and still break behaviour.
        # Run the patched module's related tests and revert on a genuine failure. Timeouts, no matching
        # tests and infra errors are not a pass: the patch stays and is reported unverified, or is
        # reverted when ELI_SELFPATCH_REQUIRE_TESTS=1. ELI_SELFPATCH_VERIFY_TESTS=0 disables the run.
        verification = "not run"
        if verify and os.environ.get("ELI_SELFPATCH_VERIFY_TESTS", "1").strip().lower() not in ("0", "false", "no", "off"):
            t_ran, t_passed, t_detail = _run_targeted_tests(p)
            if t_ran and not t_passed:
                if backup.exists():
                    shutil.copy2(str(backup), str(p))
                log.debug(f"[SELF-IMPROVE] Patch reverted — targeted tests failed: {t_detail[:200]}")
                return {"ok": False, "applied": False,
                        "message": f"Patch broke targeted tests (reverted): {t_detail[:200]}"}
            if t_ran:
                verification = "targeted tests passed"
            else:
                verification = f"unverified: {t_detail}"
                if os.environ.get("ELI_SELFPATCH_REQUIRE_TESTS", "0").strip().lower() in ("1", "true", "yes", "on"):
                    if backup.exists():
                        shutil.copy2(str(backup), str(p))
                    return {"ok": False, "applied": False, "verification": verification,
                            "message": f"Patch reverted, its tests could not run ({t_detail[:160]})"}

        # Log the applied patch
        try:
            rel_path = str(p.relative_to(_root))
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
                    (rel_path, description, old_code[:1000], new_code[:1000],
                     "applied" if verification == "targeted tests passed" else "applied_unverified",
                     time.time(), patch.get("failure_ref", ""))
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            log.debug("suppressed exception", exc_info=True)

        rel = str(p.relative_to(_root))
        reloaded = _reload_patched_module(verify_dotted) if verify_dotted else False
        log.debug(f"[SELF-IMPROVE] Patch applied: {rel} — {description}")
        return {
            "ok": True,
            "applied": True,
            "file": rel,
            "backup": str(backup),
            "reloaded": reloaded,
            "verification": verification,
            "message": f"Patch applied to {p.name}: {description} ({verification})",
        }

    def apply_patch_set(self, patches: list, *, verify: bool = True) -> dict:
        """Apply a SET of single-file patches ATOMICALLY (Advancement E) — enabling safe
        COORDINATED multi-file edits (e.g. rename a symbol + update its callers).

        Phases, all-or-nothing:
          1. Validate ALL in memory — resolve each target (project-scope, existing .py),
             confirm every `old` is present verbatim, apply it, and ast.parse the result.
             If ANY patch fails, NOTHING is written.
          2. Back up every target file (timestamped + canonical `.eli_bak`).
          3. Write all new contents.
          4. Compile + (when ``verify``) import-verify every touched module. If ANY fails,
             ROLL BACK ALL files and report — the repo is never left half-patched.

        Reuses apply_code_patch's mechanics (path/scope guard, differential import verify,
        backups). `patches`: [{"file","old","new"[,"description"]}], 1+ per file.
        Returns {"ok","applied","files":[...],"message"}.
        """
        if not patches or not isinstance(patches, list):
            return {"ok": False, "applied": False, "message": "no patches supplied"}

        # ── Phase 1: validate ALL in memory (zero writes) ───────────────────────
        by_path: Dict[Path, str] = {}
        order: List[Path] = []
        for i, patch in enumerate(patches):
            file_str = (patch.get("file") or "").strip()
            old_code, new_code = patch.get("old", ""), patch.get("new", "")
            if not file_str or not old_code or not new_code:
                return {"ok": False, "applied": False, "message": f"patch {i}: missing file/old/new"}
            p = Path(file_str)
            _root = _patch_root()
            p = (_root / p if not p.is_absolute() else p).resolve()
            try:
                p.relative_to(_root)
            except ValueError:
                return {"ok": False, "applied": False, "message": f"patch {i}: {p} outside source root"}
            if not p.exists() or p.suffix != ".py":
                return {"ok": False, "applied": False, "message": f"patch {i}: {p} is not an existing .py file"}
            try:
                content = by_path[p] if p in by_path else p.read_text(encoding="utf-8")
            except Exception as exc:
                return {"ok": False, "applied": False, "message": f"patch {i}: read error {exc}"}
            if old_code not in content:
                return {"ok": False, "applied": False,
                        "message": f"patch {i}: old_code not found verbatim in {p.name}"}
            content = content.replace(old_code, new_code, 1)
            try:
                ast.parse(content)
            except SyntaxError as exc:
                return {"ok": False, "applied": False,
                        "message": f"patch {i}: introduces syntax error in {p.name} (line {exc.lineno})"}
            if p not in by_path:
                order.append(p)
            by_path[p] = content

        # Pre-patch import baselines — only blame a broken import on us if it was clean before.
        dotted: Dict[Path, Optional[str]] = {}
        pre_ok: Dict[Path, bool] = {}
        if verify:
            for p in order:
                d = _dotted_module_for_path(p)
                dotted[p] = d
                pre_ok[p] = _smoke_import_module(d)[0] if d else False

        # ── Phase 2: back up every target ───────────────────────────────────────
        backups: Dict[Path, Path] = {}
        ts = int(time.time())
        try:
            for p in order:
                shutil.copy2(str(p), str(p.with_suffix(f".py.eli_bak.{ts}")))
                canon = p.with_suffix(".py.eli_bak")
                shutil.copy2(str(p), str(canon))
                backups[p] = canon
        except Exception as exc:
            return {"ok": False, "applied": False, "message": f"backup failed (nothing written): {exc}"}

        def _rollback_all():
            for _p, _b in backups.items():
                try:
                    if Path(_b).exists():
                        shutil.copy2(str(_b), str(_p))
                except Exception:
                    log.debug("suppressed exception", exc_info=True)

        # ── Phase 3: write all ──────────────────────────────────────────────────
        try:
            for p in order:
                p.write_text(by_path[p], encoding="utf-8")
        except Exception as exc:
            _rollback_all()
            return {"ok": False, "applied": False, "message": f"write failed (all reverted): {exc}"}

        # ── Phase 4: verify all (compile + import); roll back ALL on any failure ─
        import py_compile
        for p in order:
            try:
                py_compile.compile(str(p), doraise=True)
            except Exception as exc:
                _rollback_all()
                return {"ok": False, "applied": False,
                        "message": f"compile error in {p.name} (all reverted): {exc}"}
        if verify:
            for p in order:
                d = dotted.get(p)
                if d and pre_ok.get(p):
                    ok, detail = _smoke_import_module(d)
                    if not ok:
                        _rollback_all()
                        return {"ok": False, "applied": False,
                                "message": f"import broke in {p.name} (all reverted): {detail}"}

        files = [str(p.relative_to(_patch_root())) for p in order]
        reloaded: List[str] = []
        if verify:
            for p in order:
                d = dotted.get(p)
                if d and _reload_patched_module(d):
                    reloaded.append(d)
        log.debug(f"[SELF-IMPROVE] Patch set applied atomically across {len(files)} file(s): {files}")
        return {"ok": True, "applied": True, "files": files, "reloaded": reloaded,
                "message": f"Applied {len(patches)} patch(es) across {len(files)} file(s)"}

    def verify_in_workspace(self, patch: dict, *, tests: Optional[List[str]] = None, reproducer: Optional[List[str]] = None,
                            timeout: float = 240.0) -> dict:
        """Test a candidate patch on a copy of the tree, and compare with the same tests on the untouched tree.

        The running install is never modified. fixed = tests that failed before pass now and nothing new fails;
        regression = something that passed now fails; a timeout, an error or no matching tests is inconclusive.
        """
        root = _patch_root()
        file_str = (patch.get("file") or "").strip()
        p = (root / file_str).resolve() if not Path(file_str).is_absolute() else Path(file_str).resolve()
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            return {"verdict": "rejected", "reason": "outside the source tree"}
        if is_protected_patch_path(p):
            return {"verdict": "rejected", "reason": f"{rel} is protected: a candidate cannot change its own guardrails or evaluator"}
        stem = p.stem
        cmd = reproducer or [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", "-rf",
                             *(tests or ["tests/", "-k", stem])]
        ws_parent = root / "artifacts" / "self_improve"
        ws_parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        ws = Path(tempfile.mkdtemp(prefix="candidate_", dir=str(ws_parent)))
        t0 = time.time()
        try:
            _make_workspace(root, ws)
            if not _change_in_workspace(ws / rel, patch.get("old", ""), patch.get("new", "")):
                return {"verdict": "rejected", "reason": "the text to replace is not in the file"}
            try:
                ast.parse((ws / rel).read_text(encoding="utf-8"))
            except SyntaxError as exc:
                return {"verdict": "rejected", "reason": f"the candidate does not parse: {exc}"}
            baseline = _run_cmd(cmd, root, timeout)
            candidate = _run_cmd(cmd, ws, timeout)
        finally:
            shutil.rmtree(ws, ignore_errors=True)
        return {"verdict": compare_runs(baseline, candidate), "baseline": baseline, "candidate": candidate,
                "cost_s": round(time.time() - t0, 1)}

    def propose_candidate(self, patch: dict, *, hypothesis: str = "", tests: Optional[List[str]] = None,
                          reproducer: Optional[List[str]] = None, parent_id: Optional[int] = None) -> dict:
        """Evaluate a patch in a workspace and keep the result, whether or not it is adopted."""
        result = self.verify_in_workspace(patch, tests=tests, reproducer=reproducer)
        status = "verified" if result["verdict"] == "fixed" else "rejected" if result["verdict"] in ("rejected", "regression") else "proposed"
        conn = self.memory._get_connection()
        try:
            _ensure_failure_tables(conn)
            cur = conn.execute(
                "INSERT INTO code_patches (file_path, description, old_code, new_code, status, timestamp, failure_ref, "
                "hypothesis, verdict, results, cost_s, parent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(patch.get("file") or ""), str(patch.get("description") or "")[:300], str(patch.get("old", ""))[:4000],
                 str(patch.get("new", ""))[:4000], status, time.time(), str(patch.get("failure_ref") or ""),
                 hypothesis[:400], result["verdict"], json.dumps({k: result.get(k) for k in ("baseline", "candidate", "reason")}, default=str)[:6000],
                 float(result.get("cost_s") or 0.0), parent_id))
            conn.commit()
            result["candidate_id"] = int(cur.lastrowid)
        finally:
            conn.close()
        result["status"] = status
        return result

    def adopt_candidate(self, candidate_id: int) -> dict:
        """Apply a verified candidate to the real tree. Nothing else is adopted; a failed adoption is rolled back and recorded."""
        conn = self.memory._get_connection()
        try:
            _ensure_failure_tables(conn)
            row = conn.execute("SELECT file_path, description, old_code, new_code, status, verdict FROM code_patches WHERE id = ?",
                               (int(candidate_id),)).fetchone()
        finally:
            conn.close()
        if not row or row[4] != "verified" or row[5] != "fixed":
            return {"ok": False, "applied": False, "message": "only a candidate that fixed its reproducer with no regression can be adopted"}
        res = self.apply_code_patch({"file": row[0], "old": row[2], "new": row[3], "description": row[1]}, verify=True)
        conn = self.memory._get_connection()
        try:
            conn.execute("UPDATE code_patches SET status = ? WHERE id = ?", ("adopted" if res.get("applied") else "rolled_back", int(candidate_id)))
            conn.commit()
        finally:
            conn.close()
        return res

    def apply_autonomously(self, patch: dict, failure: Optional[dict] = None) -> dict:
        """The self-repair path: a patch goes live only when a copy of the tree shows it fixes something.

        The failure's capsule supplies the reproducer when the action is safe to replay; otherwise the module's own
        tests are the evidence. Anything short of a demonstrated fix stays in the archive, unapplied.
        """
        if os.environ.get("ELI_SELFPATCH_UNPROVEN", "0").strip().lower() in ("1", "true", "yes", "on"):
            return self.apply_code_patch(patch)
        capsule = ((failure or {}).get("context") or {}).get("capsule") if isinstance((failure or {}).get("context"), dict) else None
        reproducer = capsule_reproducer(capsule) if isinstance(capsule, dict) else None
        cand = self.propose_candidate(patch, hypothesis=str(patch.get("description") or ""), reproducer=reproducer)
        if cand.get("verdict") == "fixed":
            return self.adopt_candidate(cand["candidate_id"])
        return {"ok": False, "applied": False, "candidate_id": cand.get("candidate_id"), "verdict": cand.get("verdict"),
                "message": f"Candidate not applied: {cand.get('verdict')}"
                           + (f" ({cand.get('reason')})" if cand.get("reason") else " (no evidence it fixes anything)")}

    def candidate_archive(self, limit: int = 20) -> List[dict]:
        """Every candidate evaluated, with its verdict and cost, newest first."""
        conn = self.memory._get_connection()
        try:
            _ensure_failure_tables(conn)
            rows = conn.execute("SELECT id, file_path, description, status, verdict, hypothesis, cost_s, parent_id, timestamp FROM code_patches "
                                "WHERE verdict IS NOT NULL ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        finally:
            conn.close()
        names = ("id", "file", "description", "status", "verdict", "hypothesis", "cost_s", "parent_id", "timestamp")
        return [dict(zip(names, r)) for r in rows]

    def revert_patch(self, file_path: str) -> dict:
        """Restore the most recent .eli_bak backup for a file."""
        p = Path(file_path)
        if not p.is_absolute():
            p = _patch_root() / p
        p = p.resolve()
        backup = p.with_suffix(".py.eli_bak")
        if not backup.exists():
            return {"ok": False, "message": f"No backup found for {p.name}"}
        try:
            shutil.copy2(str(backup), str(p))
            return {"ok": True, "message": f"Reverted {p.name} from backup"}
        except Exception as exc:
            return {"ok": False, "message": f"Revert failed: {exc}"}

    def run_patch_cycle(
        self,
        max_patches: int = 3,
        dry_run: bool = False,
        *,
        days: int = DEFAULT_ANALYSIS_DAYS,
        min_cluster_size: int = PATCH_MIN_CLUSTER,
    ) -> dict:
        """
        Full automated patch cycle:
        1. Analyze recurring failures (default ≥2 occurrences for auto-apply)
        2. For each, try deterministic rules then LLM code fix
        3. Validate syntax and apply the fix
        4. Report results

        Returns a detailed dict with per-patch outcomes.
        """
        failures = self.analyze_failures(
            limit=20, days=int(days), min_cluster_size=int(min_cluster_size),
        )

        results: Dict[str, Any] = {
            "failures_analyzed": len(failures),
            "patches_generated": 0,
            "patches_applied": 0,
            "patches_skipped": 0,
            "patches_failed": 0,
            "dry_run": dry_run,
            "details": [],
        }
        try:
            from eli.core.paths import patch_capability
            results["patch_capability"] = patch_capability()
        except Exception:
            log.debug("patch_capability unavailable", exc_info=True)

        if not failures:
            _need = "≥1 occurrence" if int(min_cluster_size) <= 1 else f"≥{int(min_cluster_size)} occurrences"
            results["summary"] = f"No failures in the analysis window ({_need}). System appears stable."
            return results

        _cap = results.get("patch_capability") or {}
        if _cap.get("install_kind") in {"frozen", "packaged"}:
            results["packaged_install"] = True

        for failure in failures[:max_patches]:
            err_preview = (failure.get("error") or failure.get("user_input") or "?")[:80]
            count = failure.get("occurrence_count", 1)

            try:
                from eli.runtime.failure_taxonomy import is_actionable
                tags = {}
                try:
                    from eli.runtime.failure_taxonomy import classify
                    tags = classify(
                        _safe_str(failure.get("error")),
                        _safe_str(failure.get("command")),
                        _safe_str(failure.get("user_input")),
                    )
                except Exception:
                    log.debug("failure classify skipped", exc_info=True)
                if tags and not is_actionable(tags.get("category", "")):
                    results["patches_skipped"] += 1
                    _cat = tags.get("category", "network/resource")
                    _reason = (
                        "user_input_validation"
                        if _cat == "user_input"
                        else tags.get("category", "network/resource")
                    )
                    results["details"].append({
                        "failure": err_preview,
                        "count": count,
                        "status": "skipped_non_actionable",
                        "reason": _reason,
                    })
                    continue
            except Exception:
                log.debug("actionable filter skipped", exc_info=True)

            try:
                patch = self._try_deterministic_patch(failure)
                if patch.get("already_applied"):
                    results["patches_skipped"] += 1
                    results["details"].append({
                        "failure": err_preview,
                        "count": count,
                        "status": "already_fixed_in_codebase",
                        "reason": patch.get("description") or "fix already present",
                    })
                    continue
                if not patch or not patch.get("ok"):
                    patch = self.generate_code_patch(failure)
                if not patch.get("ok"):
                    reason = patch.get("error") or patch.get("reason") or "unknown"
                    results["patches_skipped"] += 1
                    detail = {
                        "failure": err_preview,
                        "count": count,
                        "status": "patch_generation_failed",
                        "reason": reason,
                    }
                    if reason == "no_groundable_file":
                        detail["hint"] = (
                            "No Python traceback in this failure — it is a parameter or "
                            "routing bug, not a crash. Deterministic patches are tried first; "
                            "if none matched, say which failure to fix or run EXAMINE_CODE."
                        )
                    results["details"].append(detail)
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

                apply_result = self.apply_autonomously(patch, failure)
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
        if results.get("packaged_install") and applied == 0:
            _cap = results.get("patch_capability") or {}
            _hint = _cap.get("hint") or ""
            results["summary"] += (
                " Packaged install — patches write to the user eli/ tree when runtime overlay is active."
            )
            if _hint:
                results["summary"] += f" {_hint}"
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
                log.debug("suppressed exception", exc_info=True)
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

# Self-heal notices (recurring error -> proactive conversation surface). When an error recurs
# >=5x (flag) or >=10x (act + report), a user-facing notice is queued here. The engine pops the
# most pressing one at the start of a conversational turn and mentions it, so ELI raises
# recurring problems itself and reports what it tried instead of failing silently.
def _self_heal_notices_path() -> Path:
    # A write path. PROJECT_ROOT is the install tree, read-only in a packaged build, so the notice
    # queue could never persist there and ELI silently failed to raise recurring problems, the point
    # of this file. The artifacts dir is user-writable.
    try:
        from eli.core.paths import data_dir as _dd
        return Path(_dd()) / "runtime" / "self_heal_notices.json"
    except Exception:
        return PROJECT_ROOT / "artifacts" / "runtime" / "self_heal_notices.json"


def _read_notices() -> List[Dict[str, Any]]:
    try:
        p = _self_heal_notices_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
    except Exception:
        log.debug("suppressed exception", exc_info=True)
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
        log.debug("suppressed exception", exc_info=True)


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
