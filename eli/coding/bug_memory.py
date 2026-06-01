"""Semantic bug classification + long-term memory of bugs and fixes.

Two capabilities:

1. `classify_bug(...)` — map a failure (traceback / error text / code) to a
   semantic `BugClass` with a stable, fuzzy-matchable *signature*. Exception-type
   detection is deterministic; the semantic classes (logic inversion, state
   corruption, resource leak, concurrency) use code/diff heuristics.

2. `BugMemory` — a local SQLite store of (signature → class → fix) so the agent
   accumulates, and on a new failure can recall, how a similar bug was fixed
   before. Matching is exact-signature first, then fuzzy over normalized
   signatures within the same class (difflib — no heavy deps).
"""

from __future__ import annotations

import difflib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


class BugClass(str, Enum):
    SYNTAX = "syntax_error"
    NULL_DEREF = "null_handling"              # None/null dereference
    TYPE_ERROR = "type_error"
    INDEX_OOB = "index_out_of_bounds"         # incl. off-by-one
    KEY_MISSING = "key_missing"
    NAME_UNDEFINED = "name_undefined"         # NameError / UnboundLocalError
    IMPORT_ERROR = "import_error"
    ZERO_DIVISION = "zero_division"
    VALUE_ERROR = "value_error"
    ASSERTION = "assertion_failure"
    RECURSION = "recursion_depth"
    INFINITE_LOOP = "infinite_loop_or_timeout"
    LOGIC_INVERSION = "logic_inversion"       # semantic: inverted condition/boolean
    STATE_CORRUPTION = "state_corruption"     # semantic: mutation/aliasing
    CONCURRENCY = "concurrency"               # race/deadlock
    RESOURCE_LEAK = "resource_leak"
    IO_ERROR = "io_error"
    UNKNOWN = "unknown"


@dataclass
class BugDiagnosis:
    bug_class: BugClass
    confidence: float
    signature: str
    exception_type: str = ""
    message: str = ""
    hint: str = ""               # repair hint fed to the implementer
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bug_class": self.bug_class.value, "confidence": round(self.confidence, 3),
            "signature": self.signature, "exception_type": self.exception_type,
            "message": self.message, "hint": self.hint, "evidence": self.evidence,
        }


# exception type -> (class, repair hint)
_EXC_MAP: Dict[str, tuple] = {
    "AttributeError": (BugClass.NULL_DEREF, "a value was None/unset where an attribute was accessed; add a None-guard or ensure initialisation"),
    "TypeError": (BugClass.TYPE_ERROR, "an operation got the wrong type; check argument types, None, and call signatures"),
    "IndexError": (BugClass.INDEX_OOB, "index past sequence end — likely an off-by-one; check loop bounds and len()"),
    "KeyError": (BugClass.KEY_MISSING, "missing dict key; use .get() or guard membership before access"),
    "NameError": (BugClass.NAME_UNDEFINED, "undefined name; fix the typo or define/import it before use"),
    "UnboundLocalError": (BugClass.NAME_UNDEFINED, "local used before assignment; initialise it or use the right scope"),
    "ModuleNotFoundError": (BugClass.IMPORT_ERROR, "missing import; install the dependency or correct the module name"),
    "ImportError": (BugClass.IMPORT_ERROR, "bad import; verify the symbol exists in that module"),
    "ZeroDivisionError": (BugClass.ZERO_DIVISION, "division by zero; guard the denominator"),
    "ValueError": (BugClass.VALUE_ERROR, "invalid value/argument; validate inputs and ranges"),
    "AssertionError": (BugClass.ASSERTION, "an assertion/test failed; the logic does not meet the expected contract"),
    "RecursionError": (BugClass.RECURSION, "unbounded recursion; add a base case or convert to iteration"),
    "SyntaxError": (BugClass.SYNTAX, "invalid syntax; fix the offending line"),
    "IndentationError": (BugClass.SYNTAX, "bad indentation; fix the block structure"),
    "FileNotFoundError": (BugClass.IO_ERROR, "missing file/path; check existence and create or guard"),
    "PermissionError": (BugClass.IO_ERROR, "permission denied; check path permissions"),
    "TimeoutError": (BugClass.INFINITE_LOOP, "operation timed out; check for blocking or an unbounded loop"),
}

_EXC_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*Error|StopIteration|KeyboardInterrupt)\b:?\s*(.*)$", re.MULTILINE)
_LAST_FRAME_RE = re.compile(r'File "[^"]+", line \d+, in (\S+)')
_NUM_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b\d+\b")
_PATH_RE = re.compile(r"(/[^\s'\"]+)+")
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def _normalize_message(msg: str) -> str:
    s = _PATH_RE.sub("<path>", msg or "")
    s = _QUOTED_RE.sub("<x>", s)
    s = _NUM_RE.sub("<n>", s)
    return re.sub(r"\s+", " ", s).strip().lower()[:200]


def _signature(exc_type: str, last_frame: str, norm_msg: str, bug_class: BugClass) -> str:
    return f"{bug_class.value}|{exc_type}|{last_frame}|{norm_msg}"


def classify_bug(traceback_text: str = "", code: str = "", message: str = "",
                 timed_out: bool = False) -> BugDiagnosis:
    """Classify a failure into a semantic BugClass with a matchable signature.

    Deterministic for exception-typed crashes; heuristic for the semantic classes
    when only code/diff is available (no exception).
    """
    tb = traceback_text or ""
    evidence: List[str] = []

    if timed_out:
        return BugDiagnosis(BugClass.INFINITE_LOOP, 0.8,
                            _signature("Timeout", "", "", BugClass.INFINITE_LOOP),
                            exception_type="Timeout",
                            hint="execution did not terminate; add a bound/base-case or fix a blocking call",
                            evidence=["timed out"])

    exc_type, exc_msg = "", message or ""
    m = None
    for m in _EXC_RE.finditer(tb):
        pass  # take the LAST exception line (the actual raised one)
    if m:
        exc_type, exc_msg = m.group(1).split(".")[-1], (m.group(2) or "").strip()

    last_frame = ""
    frames = _LAST_FRAME_RE.findall(tb)
    if frames:
        last_frame = frames[-1]

    if exc_type:
        bug_class, hint = _EXC_MAP.get(exc_type, (BugClass.UNKNOWN, "investigate the raised exception"))
        # AttributeError specifically on None → null handling (high confidence)
        if exc_type == "AttributeError" and "NoneType" in exc_msg:
            evidence.append("AttributeError on NoneType")
        norm = _normalize_message(exc_msg)
        sig = _signature(exc_type, last_frame, norm, bug_class)
        conf = 0.9 if bug_class is not BugClass.UNKNOWN else 0.4
        return BugDiagnosis(bug_class, conf, sig, exception_type=exc_type,
                            message=exc_msg[:200], hint=hint, evidence=evidence or [f"raised {exc_type}"])

    # ── No exception: semantic heuristics over code (for review/repair) ──────
    low = (code or "")
    semantic: List[tuple] = []
    if re.search(r"\bthreading\.|asyncio\.|multiprocessing\.|\.acquire\(|Lock\(", low):
        if re.search(r"\.acquire\(\)(?![\s\S]{0,400}\.release\()", low) or "deadlock" in (message or "").lower():
            semantic.append((BugClass.CONCURRENCY, 0.45, "lock acquired without a guaranteed release; use a context manager"))
        else:
            semantic.append((BugClass.CONCURRENCY, 0.3, "shared state under concurrency; check for races"))
    if re.search(r"\bopen\(", low) and "with " not in low and ".close()" not in low:
        semantic.append((BugClass.RESOURCE_LEAK, 0.5, "file opened without `with`/close(); use a context manager"))
    if re.search(r"\bif\s+not\s+.+:\s*$", low, re.MULTILINE) and "expected" in (message or "").lower():
        semantic.append((BugClass.LOGIC_INVERSION, 0.35, "a condition may be inverted; re-check boolean polarity"))
    if re.search(r"\b(global|nonlocal)\b|\.append\(|\.pop\(|\.update\(", low) and "mutat" in (message or "").lower():
        semantic.append((BugClass.STATE_CORRUPTION, 0.35, "shared/mutable state mutated unexpectedly; copy or isolate it"))

    if semantic:
        semantic.sort(key=lambda t: t[1], reverse=True)
        bc, conf, hint = semantic[0]
        norm = _normalize_message(message)
        return BugDiagnosis(bc, conf, _signature("", "", norm, bc), message=(message or "")[:200],
                            hint=hint, evidence=[f"heuristic: {bc.value}"])

    norm = _normalize_message(message or tb)
    return BugDiagnosis(BugClass.UNKNOWN, 0.2, _signature("", last_frame, norm, BugClass.UNKNOWN),
                        message=(exc_msg or message)[:200], hint="no clear classification; inspect manually")


# ── Long-term memory ─────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_bug_fixes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    signature    TEXT NOT NULL,
    bug_class    TEXT NOT NULL,
    language     TEXT DEFAULT 'python',
    error_excerpt TEXT DEFAULT '',
    fix_summary  TEXT DEFAULT '',
    fix_diff     TEXT DEFAULT '',
    success_count INTEGER DEFAULT 1,
    created_ts   REAL,
    last_ts      REAL
);
CREATE INDEX IF NOT EXISTS coding_bug_sig  ON coding_bug_fixes(signature);
CREATE INDEX IF NOT EXISTS coding_bug_class ON coding_bug_fixes(bug_class);
"""


def _default_db_path() -> Path:
    try:
        from eli.core.paths import get_paths
        base = Path(get_paths().db_dir)
    except Exception:
        try:
            from eli.core.paths import data_dir
            base = Path(data_dir())
        except Exception:
            base = Path(__file__).resolve().parents[2] / "artifacts"
    base.mkdir(parents=True, exist_ok=True)
    return base / "coding_memory.sqlite3"


@dataclass
class FixRecord:
    signature: str
    bug_class: str
    fix_summary: str
    fix_diff: str = ""
    language: str = "python"
    error_excerpt: str = ""
    success_count: int = 1
    similarity: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["similarity"] = round(self.similarity, 3)
        return d


class BugMemory:
    """Local SQLite store of bugs and the fixes that resolved them."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path))
        return c

    def _init(self) -> None:
        try:
            c = self._conn()
            try:
                c.executescript(_SCHEMA)
                c.commit()
            finally:
                c.close()
        except Exception as exc:
            log.debug(f"[BUG_MEMORY] init failed: {exc}")

    def record_fix(self, diagnosis: BugDiagnosis, fix_summary: str, *,
                   fix_diff: str = "", language: str = "python") -> bool:
        """Record (or reinforce) that `diagnosis` was fixed by `fix_summary`."""
        try:
            c = self._conn()
            try:
                row = c.execute(
                    "SELECT id, success_count FROM coding_bug_fixes WHERE signature=? AND fix_summary=?",
                    (diagnosis.signature, fix_summary),
                ).fetchone()
                now = time.time()
                if row:
                    c.execute("UPDATE coding_bug_fixes SET success_count=success_count+1, last_ts=? WHERE id=?",
                              (now, row[0]))
                else:
                    c.execute(
                        "INSERT INTO coding_bug_fixes (signature, bug_class, language, error_excerpt, "
                        "fix_summary, fix_diff, success_count, created_ts, last_ts) VALUES (?,?,?,?,?,?,?,?,?)",
                        (diagnosis.signature, diagnosis.bug_class.value, language,
                         (diagnosis.message or "")[:500], fix_summary[:2000], fix_diff[:8000], 1, now, now),
                    )
                c.commit()
                return True
            finally:
                c.close()
        except Exception as exc:
            log.debug(f"[BUG_MEMORY] record_fix failed: {exc}")
            return False

    def recall(self, diagnosis: BugDiagnosis, *, limit: int = 3, min_similarity: float = 0.6) -> List[FixRecord]:
        """Recall prior fixes: exact signature first, then fuzzy within the same
        bug class (difflib over normalized signatures)."""
        out: List[FixRecord] = []
        try:
            c = self._conn()
            try:
                exact = c.execute(
                    "SELECT signature, bug_class, fix_summary, fix_diff, language, error_excerpt, success_count "
                    "FROM coding_bug_fixes WHERE signature=? ORDER BY success_count DESC, last_ts DESC LIMIT ?",
                    (diagnosis.signature, limit),
                ).fetchall()
                for r in exact:
                    out.append(FixRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6], similarity=1.0))
                if len(out) >= limit:
                    return out[:limit]
                seen = {r.fix_summary for r in out}
                cand = c.execute(
                    "SELECT signature, bug_class, fix_summary, fix_diff, language, error_excerpt, success_count "
                    "FROM coding_bug_fixes WHERE bug_class=? ORDER BY success_count DESC LIMIT 50",
                    (diagnosis.bug_class.value,),
                ).fetchall()
                scored = []
                for r in cand:
                    if r[2] in seen:
                        continue
                    sim = difflib.SequenceMatcher(None, diagnosis.signature, r[0]).ratio()
                    if sim >= min_similarity:
                        scored.append((sim, r))
                scored.sort(key=lambda t: (t[0], t[1][6]), reverse=True)
                for sim, r in scored[: limit - len(out)]:
                    out.append(FixRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6], similarity=sim))
                return out[:limit]
            finally:
                c.close()
        except Exception as exc:
            log.debug(f"[BUG_MEMORY] recall failed: {exc}")
            return out

    def stats(self) -> Dict[str, Any]:
        try:
            c = self._conn()
            try:
                total = c.execute("SELECT COUNT(*) FROM coding_bug_fixes").fetchone()[0]
                by_class = c.execute(
                    "SELECT bug_class, COUNT(*) FROM coding_bug_fixes GROUP BY bug_class ORDER BY 2 DESC"
                ).fetchall()
                return {"total_fixes": total, "by_class": {k: v for k, v in by_class}}
            finally:
                c.close()
        except Exception:
            return {"total_fixes": 0, "by_class": {}}


_memory_singleton: Optional[BugMemory] = None


def get_bug_memory() -> BugMemory:
    global _memory_singleton
    if _memory_singleton is None:
        _memory_singleton = BugMemory()
    return _memory_singleton
