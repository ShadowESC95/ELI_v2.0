"""
ELI learning dataset builder.

Purpose:
- Build supervised JSONL candidate examples from local ELI data.
- Produce reviewable training data, not automatic weight updates.
- Redact local/private paths and reject secrets, tracebacks, and broken surfaces.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Read the SQLite stores from the SAME directory the runtime writes them to.
# The runtime uses paths.db_dir() (= data_dir()/db); hardcoding
# PROJECT_ROOT/artifacts/db here diverged on any redistributed / per-user
# install where data_dir() is NOT the project tree — the builder then opened
# empty databases and produced a zero-example dataset (the adapter trained on
# nothing). Same latent bug already fixed for CONV_DIR just below.
try:
    from eli.core.paths import db_dir as _db_dir
    _DB_DIR = _db_dir()
except Exception:
    _DB_DIR = PROJECT_ROOT / "artifacts" / "db"
USER_DB = _DB_DIR / "user.sqlite3"
AGENT_DB = _DB_DIR / "agent.sqlite3"
# Read conversation logs from the SAME directory the runtime writes them to.
# The writers (log_rotation / executor convlog) use paths.conversations_dir()
# (= data_dir()/conversations); hardcoding PROJECT_ROOT/artifacts/conversations
# here diverged on any redistributed install where data_dir() is a per-user
# directory rather than the project tree — the builder then saw an empty folder.
try:
    from eli.core.paths import conversations_dir as _conversations_dir
    CONV_DIR = _conversations_dir()
except Exception:
    CONV_DIR = PROJECT_ROOT / "artifacts" / "conversations"

DEFAULT_OUT = PROJECT_ROOT / "training" / "datasets" / "eli_supervised_v0.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "training" / "datasets" / "eli_supervised_v0.report.json"


SECRET_PATTERNS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"\bapi[_-]?key\b", re.I),
    re.compile(r"\bpassword\b", re.I),
    re.compile(r"\bprivate key\b", re.I),
    re.compile(r"\bBEGIN [A-Z ]*PRIVATE KEY\b"),
]

REJECT_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\bSyntaxError\b|\bIndentationError\b|\bNameError\b"),
    re.compile(r"^\s*(route:|ok\s*\{|input:|mode:|render_preview:)", re.I),
    re.compile(r"\bAs an AI\b", re.I),
    re.compile(r"\bI am a large language model\b", re.I),
    re.compile(r"\btrained by OpenAI\b", re.I),
    # Router/search/command-surface artifacts. These are execution traces,
    # not model behaviour to imitate as assistant prose.
    re.compile(r"^\s*Searching\s+for\s*:", re.I),
    re.compile(r"^\s*Search\s+query\s*:", re.I),
    re.compile(r"^\s*Looking\s+up\s*:", re.I),
    re.compile(r"^\s*Script\s+generated\s*:", re.I),
    re.compile(r'"event"\s*:\s*"artifact_generated"', re.I),
    re.compile(r"^\s*Action\s+.+\s+not\s+implemented", re.I),


    # ELI-specific bad identity/persona surfaces from earlier broken runs.
    # These must never become LoRA training examples.
    re.compile(r"\bI\s+am\s+ELI,?\s+an?\s+AI\s+language\s+model\b", re.I),
    re.compile(r"\bI['’]m\s+ELI,?\s+an?\s+AI\s+language\s+model\b", re.I),
    re.compile(r"\bAI\s+language\s+model\s+developed\s+to\s+assist\b", re.I),
    re.compile(r"\bstarting\s+a\s+new\s+conversation\b", re.I),
    re.compile(r"\bprevious\s+interactions\s+may\s+not\s+be\s+readily\s+available\b", re.I),
    re.compile(r"\brest\s+assured\b", re.I),
]

# PHASE16C_DYNAMIC_PROJECT_ROOT_REDACTION
# Redact the actual local checkout dynamically. Do not assume a username,
# a Desktop checkout, a Linux-only host, or a historical checkout folder name.
PROJECT_PATH_RE = re.compile(re.escape(str(PROJECT_ROOT)))
PROJECT_ALIAS_PATH_RE = re.compile(
    r"(?:"
    r"/home/[A-Za-z0-9._-]+/[^\s]*?ELI_MKXI[^/\s]*"
    r"|/Users/[A-Za-z0-9._-]+/[^\s]*?ELI_MKXI[^/\s]*"
    r"|[A-Za-z]:\\Users\\[^\\\s]+\\[^\s]*?ELI_MKXI[^\\\s]*"
    r")"
)

# Sanitisation patterns for common user-home path shapes. These are redaction
# rules, not operational filesystem defaults.
HOME_PATH_RE = re.compile(
    r"(?:"
    r"/home/[A-Za-z0-9._-]+"
    r"|/Users/[A-Za-z0-9._-]+"
    r"|[A-Za-z]:\\Users\\[^\\\s]+"
    r")"
)


@dataclass
class SupervisedExample:
    source: str
    instruction: str
    response: str
    weight: float = 1.0
    tags: list[str] | None = None


class BuildStats:
    def __init__(self) -> None:
        self.seen = 0
        self.accepted = 0
        self.rejected: dict[str, int] = {}

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1


def clean_text(text: object) -> str:
    return str(text or "").replace("\x00", "").strip()


def redact_text(text: str) -> str:
    text = PROJECT_PATH_RE.sub("<PROJECT_ROOT>", text)
    text = PROJECT_ALIAS_PATH_RE.sub("<PROJECT_ROOT>", text)
    text = HOME_PATH_RE.sub("<HOME>", text)
    return text.strip()


def reject_reason(instruction: str, response: str) -> Optional[str]:
    joined = f"{instruction}\n{response}"

    if not instruction or not response:
        return "empty"
    if len(instruction) < 4:
        return "instruction_too_short"
    if len(response) < 12:
        return "response_too_short"
    if len(response) > 12000:
        return "response_too_long"
    if any(p.search(joined) for p in SECRET_PATTERNS):
        return "secret_pattern"
    if any(p.search(joined) for p in REJECT_PATTERNS):
        return "bad_surface_or_traceback"
    return None


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def list_tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def pick(d: dict[str, Any], names: list[str]) -> str:
    lower = {k.lower(): k for k in d}
    for name in names:
        k = lower.get(name.lower())
        if k is not None:
            v = clean_text(d.get(k))
            if v:
                return v
    return ""


def rows_as_dicts(conn: sqlite3.Connection, table: str, limit: int = 2000) -> list[dict[str, Any]]:
    cols = columns(conn, table)
    if not cols:
        return []
    qcols = ", ".join([f'"{c}"' for c in cols])
    rows = conn.execute(f"SELECT {qcols} FROM {table} ORDER BY rowid ASC LIMIT {int(limit)}").fetchall()
    return [dict(zip(cols, row)) for row in rows]


def make_example(
    stats: BuildStats,
    *,
    source: str,
    instruction: str,
    response: str,
    weight: float,
    tags: list[str],
) -> Optional[SupervisedExample]:
    stats.seen += 1

    instruction = redact_text(clean_text(instruction))
    response = redact_text(clean_text(response))

    reason = reject_reason(instruction, response)
    if reason:
        stats.reject(reason)
        return None

    stats.accepted += 1
    return SupervisedExample(
        source=source,
        instruction=instruction,
        response=response,
        weight=weight,
        tags=tags,
    )


def examples_from_corrections(conn: sqlite3.Connection, stats: BuildStats) -> list[SupervisedExample]:
    out: list[SupervisedExample] = []

    for table in list_tables(conn):
        if "correction" not in table.lower():
            continue

        for d in rows_as_dicts(conn, table):
            bad = pick(d, ["original", "bad", "wrong", "input", "prompt", "question", "user_text", "text"])
            good = pick(d, ["correction", "corrected", "good", "fixed", "answer", "response", "assistant_text"])

            if not good:
                continue

            instruction = (
                f"The previous answer was wrong or unsuitable:\n{bad}\n\nProvide the corrected response."
                if bad else
                "Provide the corrected response."
            )

            ex = make_example(
                stats,
                source=f"sqlite:{table}",
                instruction=instruction,
                response=good,
                weight=1.0,
                tags=["correction", "high_value", "needs_review"],
            )
            if ex:
                out.append(ex)

    return out


def examples_from_turn_tables(conn: sqlite3.Connection, stats: BuildStats) -> list[SupervisedExample]:
    out: list[SupervisedExample] = []

    role_keys = ["role", "speaker", "sender", "author", "kind", "source"]
    text_keys = ["text", "content", "message", "body", "value", "utterance"]

    for table in list_tables(conn):
        low_table = table.lower()
        if not any(k in low_table for k in ["conversation", "turn", "message"]):
            continue

        rows = rows_as_dicts(conn, table, limit=5000)

        prev_user: Optional[str] = None

        for d in rows:
            role = pick(d, role_keys).lower()
            text = pick(d, text_keys)

            # Some schemas use explicit user/assistant columns in one row.
            user_inline = pick(d, ["user", "user_text", "prompt", "input", "question"])
            assistant_inline = pick(d, ["assistant", "assistant_text", "response", "answer", "output"])

            if user_inline and assistant_inline:
                ex = make_example(
                    stats,
                    source=f"sqlite:{table}",
                    instruction=user_inline,
                    response=assistant_inline,
                    weight=0.45,
                    tags=["conversation_candidate", "needs_review"],
                )
                if ex:
                    out.append(ex)
                continue

            if not text:
                continue

            if role in {"user", "human", "operator"}:
                prev_user = text
                continue

            if role in {"assistant", "eli", "bot", "ai", "model"} and prev_user:
                ex = make_example(
                    stats,
                    source=f"sqlite:{table}",
                    instruction=prev_user,
                    response=text,
                    weight=0.35,
                    tags=["conversation_candidate", "needs_review"],
                )
                if ex:
                    out.append(ex)
                prev_user = None

    return out


def load_jsonish_file(path: Path) -> list[Any]:
    try:
        if path.suffix == ".gz":
            raw = gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
        else:
            raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    raw = raw.strip()
    if not raw:
        return []

    # JSON array/object.
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, list) else [obj]
    except Exception:
        pass

    # JSONL.
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def flatten_messages(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        msgs = []
        for item in obj:
            msgs.extend(flatten_messages(item))
        return msgs

    if not isinstance(obj, dict):
        return []

    for key in ["messages", "turns", "conversation", "history", "items"]:
        val = obj.get(key)
        if isinstance(val, list):
            return flatten_messages(val)

    if any(k in obj for k in ["role", "speaker", "sender", "author"]) and any(
        k in obj for k in ["text", "content", "message", "body"]
    ):
        return [obj]

    # Some saved conversations use direct fields.
    if any(k in obj for k in ["user", "user_text", "prompt"]) and any(
        k in obj for k in ["assistant", "assistant_text", "response"]
    ):
        return [obj]

    return []


def examples_from_conversation_files(stats: BuildStats) -> list[SupervisedExample]:
    out: list[SupervisedExample] = []
    if not CONV_DIR.exists():
        return out

    files = sorted(CONV_DIR.rglob("*.json")) + sorted(CONV_DIR.rglob("*.jsonl")) + sorted(CONV_DIR.rglob("*.jsonl.gz"))

    for path in files[-200:]:
        objs = load_jsonish_file(path)
        msgs = flatten_messages(objs)

        prev_user: Optional[str] = None

        for m in msgs:
            role = pick(m, ["role", "speaker", "sender", "author"]).lower()
            text = pick(m, ["text", "content", "message", "body"])

            user_inline = pick(m, ["user", "user_text", "prompt", "input", "question"])
            assistant_inline = pick(m, ["assistant", "assistant_text", "response", "answer", "output"])

            if user_inline and assistant_inline:
                ex = make_example(
                    stats,
                    source=f"file:{path.relative_to(PROJECT_ROOT)}",
                    instruction=user_inline,
                    response=assistant_inline,
                    weight=0.40,
                    tags=["conversation_file_candidate", "needs_review"],
                )
                if ex:
                    out.append(ex)
                continue

            if not text:
                continue

            if role in {"user", "human", "operator"}:
                prev_user = text
                continue

            if role in {"assistant", "eli", "bot", "ai", "model"} and prev_user:
                ex = make_example(
                    stats,
                    source=f"file:{path.relative_to(PROJECT_ROOT)}",
                    instruction=prev_user,
                    response=text,
                    weight=0.35,
                    tags=["conversation_file_candidate", "needs_review"],
                )
                if ex:
                    out.append(ex)
                prev_user = None

    return out


def dedupe(examples: Iterable[SupervisedExample]) -> list[SupervisedExample]:
    seen = set()
    out = []
    for ex in examples:
        key = (ex.instruction.strip(), ex.response.strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(ex)
    return out


def write_jsonl(examples: Iterable[SupervisedExample], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(asdict(ex), ensure_ascii=False) + "\n")
            count += 1
    return count



def _normalise_db_paths(db_paths: Any) -> list[Path]:
    """
    Backward-compatible DB path handling.

    Accepts:
    - None                  -> default user + agent DBs
    - Path / str            -> single DB
    - list[Path | str]      -> explicit DB list
    """
    if db_paths is None:
        return [USER_DB, AGENT_DB]
    if isinstance(db_paths, (str, Path)):
        return [Path(db_paths)]
    return [Path(x) for x in db_paths]


def build_dataset(
    db_paths: list[Path] | None = None,
    out_path: Path = DEFAULT_OUT,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    stats = BuildStats()
    examples: list[SupervisedExample] = []

    explicit_db_paths = db_paths is not None
    db_paths = _normalise_db_paths(db_paths)

    db_reports = []

    for db_path in db_paths:
        if not db_path.exists():
            db_reports.append({"db": str(db_path), "exists": False})
            continue

        con = sqlite3.connect(str(db_path))
        try:
            before = len(examples)
            examples.extend(examples_from_corrections(con, stats))
            examples.extend(examples_from_turn_tables(con, stats))
            db_reports.append({
                "db": str(db_path),
                "exists": True,
                "added": len(examples) - before,
            })
        finally:
            con.close()

    file_added = 0
    if not explicit_db_paths:
        before_files = len(examples)
        examples.extend(examples_from_conversation_files(stats))
        file_added = len(examples) - before_files

    examples = dedupe(examples)
    count = write_jsonl(examples, out_path)

    report = {
        "ok": True,
        "out": str(out_path),
        "count": count,
        "seen_candidates": stats.seen,
        "accepted_before_dedupe": stats.accepted,
        "rejected": stats.rejected,
        "db_reports": db_reports,
        "conversation_file_added_before_dedupe": file_added,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--db", action="append", default=[])
    args = ap.parse_args()

    dbs = [Path(x) for x in args.db] if args.db else None
    result = build_dataset(dbs, Path(args.out), Path(args.report))
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
