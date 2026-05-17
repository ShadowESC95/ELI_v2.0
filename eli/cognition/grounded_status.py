from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eli.runtime.identity_validation import normalize_identity_candidate


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _profile_paths() -> List[Path]:
    paths: List[Path] = []
    try:
        from eli.kernel.state import _profile_path
        paths.append(Path(_profile_path()))
    except Exception:
        paths.append(PROJECT_ROOT / "artifacts" / "runtime" / "user_profile.json")
    paths.extend([
        PROJECT_ROOT / "artifacts" / "user_profile.json",
        PROJECT_ROOT / "config" / "user_profile.json",
        PROJECT_ROOT / "user_profile.json",
    ])
    seen = set()
    out = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _db_paths() -> List[Path]:
    try:
        from eli.core.paths import user_db_path, agent_db_path
        return [Path(user_db_path()), Path(agent_db_path())]
    except Exception:
        return [
            PROJECT_ROOT / "artifacts" / "db" / "user.sqlite3",
            PROJECT_ROOT / "artifacts" / "db" / "agent.sqlite3",
        ]


def _load_profile() -> Dict[str, Any]:
    for p in _profile_paths():
        if p.exists() and p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data["_source"] = str(p)
                    return data
            except Exception:
                pass
    return {}


def _connect(db: Path) -> Optional[sqlite3.Connection]:
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        return con
    except Exception:
        return None


def _tables(con: sqlite3.Connection) -> List[str]:
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return [str(r[0]) for r in rows]
    except Exception:
        return []


def _columns(con: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [str(r[1]) for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []


def _best_text_column(con: sqlite3.Connection, table: str) -> Optional[str]:
    """
    Choose the best populated text-bearing column for a table.

    Important: some ELI tables contain multiple text-like columns where
    `content` exists but is empty while `text` or `value` carries the real data.
    Do not choose by name alone.
    """
    cols = _columns(con, table)

    preferred = (
        "text",
        "value",
        "content",
        "memory",
        "memory_text",
        "summary",
        "body",
        "message",
        "observation",
        "note",
        "description",
        "data",
        "payload",
    )

    candidates = [c for c in preferred if c in cols]

    # Add any declared TEXT-ish columns not already included.
    try:
        info = con.execute(f"PRAGMA table_info({table})").fetchall()
        for r in info:
            col_name = str(r[1])
            col_type = str(r[2] or "").upper()
            if col_name in candidates:
                continue
            if col_name.lower() in {"id", "rowid", "created_at", "updated_at", "timestamp", "ts"}:
                continue
            if "TEXT" in col_type or "CHAR" in col_type or "CLOB" in col_type:
                candidates.append(col_name)
    except Exception:
        pass

    best_col: Optional[str] = None
    best_score = -1

    for col in candidates:
        try:
            row = con.execute(
                f"""
                SELECT
                    COUNT(*) AS n,
                    COALESCE(AVG(length(trim(cast({col} AS text)))), 0) AS avg_len
                FROM {table}
                WHERE {col} IS NOT NULL
                  AND length(trim(cast({col} AS text))) > 0
                """
            ).fetchone()

            n = int(row[0] or 0)
            avg_len = float(row[1] or 0.0)

            # Prefer populated columns with meaningful text length.
            score = n * max(avg_len, 1.0)

            if score > best_score:
                best_score = score
                best_col = col
        except Exception:
            continue

    return best_col



def _count_table(con: sqlite3.Connection, table: str) -> int:
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0


def _memory_like_rows(limit: int = 16) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []

    preferred_tables = [
        "memories",
        "observations",
        "habits",
        "improvements",
        "conversation_turns",
        "conversations",
    ]

    poison = (
        "the user's name is the",
        "your name is the",
        "i don't remember your name",
        "i have 1,442 memories stored",
        "what is my preferred name or nickname",
        "how do you have 1442 memories",
        "what the fuck is in the memories",
        "traditional file-based persona",
        "--- eli persona ---",
        "i'm an artificial intelligence",
        "i am an artificial intelligence",

        # Low-value auto-noise; valid internally, useless for user-facing inventory.
        "proactive daemon started",
        "reflection (24h): conversation volume",
        "reflection (0h):",
        "recent issues:",
        "session context:",
    )

    for db in DB_PATHS:
        con = _connect(db)
        if con is None:
            continue

        try:
            tables = set(_tables(con))

            for table in preferred_tables:
                if table not in tables:
                    continue

                col = _best_text_column(con, table)
                if not col:
                    continue

                try:
                    q = f"""
                    SELECT {col} AS txt
                    FROM {table}
                    WHERE {col} IS NOT NULL AND length(trim({col})) > 0
                    ORDER BY rowid DESC
                    LIMIT ?
                    """
                    for r in con.execute(q, (limit * 6,)).fetchall():
                        txt = " ".join(str(r["txt"]).split())
                        low = txt.lower()

                        if not txt:
                            continue
                        if any(bad in low for bad in poison):
                            continue

                        rows.append((db.name, table, txt[:260]))

                        if len(rows) >= limit:
                            return rows
                except Exception:
                    continue
        finally:
            con.close()

    return rows[:limit]



def _memory_counts() -> Dict[str, Any]:
    out: Dict[str, Any] = {"databases": [], "total_rows": 0}

    for db in DB_PATHS:
        db_info: Dict[str, Any] = {
            "path": str(db),
            "exists": db.exists(),
            "tables": {},
        }

        con = _connect(db)
        if con is None:
            out["databases"].append(db_info)
            continue

        try:
            for table in _tables(con):
                count = _count_table(con, table)
                db_info["tables"][table] = count

                if table in {"memories", "conversation_turns", "observations", "habits", "improvements"}:
                    out["total_rows"] += count
        finally:
            con.close()

        out["databases"].append(db_info)

    return out



def _clean_identity_candidate(value: str) -> str:
    return normalize_identity_candidate(value)


def _extract_identity_candidates_from_text(txt: str) -> dict:
    txt = " ".join(str(txt or "").split())
    low = txt.lower()

    poison = (
        "the user's name is the",
        "your name is the",
        "name is the",
        "traditional file-based persona",
        "--- eli persona ---",
        "i'm an artificial intelligence",
        "i am an artificial intelligence",
        "what is my name",
        "what is my preferred name",
        "preferred name or nickname",
    )

    if not txt or any(bad in low for bad in poison):
        return {}

    # Avoid treating questions/corrections as evidence.
    if "?" in txt and not any(x in low for x in ("my name is", "call me", "i go by")):
        return {}

    patterns = {
        "preferred_name": [
            r"\bpreferred name is\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
            r"\bnickname is\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
            r"\bcall me\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
            r"\bi go by\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
            r"\buser goes by\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
        ],
        "name": [
            r"\bmy name is\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
            r"\buser'?s name is\s+([A-Za-z][A-Za-z0-9_\-']{1,40})",
        ],
    }

    out = {}

    for key, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, txt, flags=re.I)
            if not m:
                continue
            candidate = _clean_identity_candidate(m.group(1))
            if candidate:
                out[key] = candidate
                break

    return out


def _infer_identity_from_memory() -> tuple[dict, list[str]]:
    found = {}
    evidence = []

    for db in _db_paths():
        con = _connect(db)
        if con is None:
            continue

        try:
            for table in _tables(con):
                col = _best_text_column(con, table)
                if not col:
                    continue
                cols = set(_columns(con, table))
                source_filter = ""
                if "role" in cols:
                    source_filter = "AND lower(COALESCE(role,'')) = 'user'"
                elif table == "memories" and "source" in cols:
                    source_filter = (
                        "AND lower(COALESCE(source,'')) IN "
                        "('user','runtime_identity_extractor','working_memory','identity')"
                    )

                try:
                    q = f"""
                    SELECT {col} AS txt
                    FROM {table}
                    WHERE (
                       lower({col}) LIKE '%my name is%'
                       OR lower({col}) LIKE '%user''s name is%'
                       OR lower({col}) LIKE '%preferred name is%'
                       OR lower({col}) LIKE '%nickname is%'
                       OR lower({col}) LIKE '%call me%'
                       OR lower({col}) LIKE '%go by%'
                    )
                    {source_filter}
                    ORDER BY rowid DESC
                    LIMIT 80
                    """
                    for r in con.execute(q).fetchall():
                        txt = " ".join(str(r["txt"]).split())
                        extracted = _extract_identity_candidates_from_text(txt)
                        if not extracted:
                            continue

                        for k, v in extracted.items():
                            found.setdefault(k, v)

                        evidence.append(f"- {db.name}:{table}: {txt[:240]}")

                        if found.get("preferred_name") and found.get("name"):
                            return found, evidence[:12]
                except Exception:
                    pass
        finally:
            con.close()

    return found, evidence[:12]


def format_user_identity() -> str:
    """
    Dynamic user identity report.

    Redistributable rule:
    - Never hardcode a user's name.
    - Never infer a personal name from the Linux username.
    - Only report a name/preferred_name when it exists in a local profile
      or grounded memory evidence.
    """
    import getpass

    profile = _load_profile()
    source = profile.get("_source", "")

    preferred = (
        _clean_identity_candidate(profile.get("preferred_name", ""))
        or _clean_identity_candidate(profile.get("nickname", ""))
    )
    name = _clean_identity_candidate(profile.get("name", ""))

    memory_identity, evidence_rows = _infer_identity_from_memory()

    if not preferred:
        preferred = memory_identity.get("preferred_name", "")

    if not name:
        name = memory_identity.get("name", "")

    system_user = getpass.getuser()

    lines = ["Grounded user identity:"]
    lines.append(f"- preferred_name: {preferred or 'unknown'}")
    lines.append(f"- name: {name or 'unknown'}")
    lines.append(f"- profile_source: {source or 'none'}")
    lines.append(f"- linux_user: {system_user}")
    lines.append("")
    lines.append("Evidence snippets:")

    if evidence_rows:
        lines.extend(evidence_rows[:12])
    else:
        lines.append("- No verified identity evidence found in profile or memory.")

    return "\n".join(lines).strip()



def format_memory_inventory(limit: int = 16) -> str:
    """
    Structured memory inventory.

    Redistributable rule:
    - Do not hardcode user facts.
    - Do not pretend recent chat turns are long-term memory.
    - Separate actual memory rows from volatile conversation history.
    """
    counts = _memory_counts()

    noise = (
        "the user's name is the",
        "your name is the",
        "i don't remember your name",
        "i have 1,442 memories stored",
        "what is my preferred name or nickname",
        "how do you have 1442 memories",
        "what the fuck is in the memories",
        "traditional file-based persona",
        "--- eli persona ---",
        "i'm an artificial intelligence",
        "i am an artificial intelligence",
        "proactive daemon started",
        "reflection (24h): conversation volume",
        "reflection (0h):",
        "recent issues:",
        "session context:",
    )

    def clean(txt: str) -> str:
        return " ".join(str(txt or "").split())

    def is_noise(txt: str) -> bool:
        low = clean(txt).lower()
        return (not low) or any(x in low for x in noise)

    def collect_samples(table: str, max_rows: int, db_name: str = "user.sqlite3") -> list[str]:
        db = PROJECT_ROOT / "artifacts" / "db" / db_name
        con = _connect(db)
        if con is None:
            return []

        out: list[str] = []
        try:
            if table not in _tables(con):
                return []

            col = _best_text_column(con, table)
            if not col:
                return []

            q = f"""
            SELECT {col} AS txt
            FROM {table}
            WHERE {col} IS NOT NULL
              AND length(trim(cast({col} AS text))) > 0
            ORDER BY rowid DESC
            LIMIT ?
            """

            # Pull deep enough to skip auto-noise.
            for r in con.execute(q, (max_rows * 80,)).fetchall():
                txt = clean(r["txt"])
                if is_noise(txt):
                    continue
                out.append(txt[:300])
                if len(out) >= max_rows:
                    break
        finally:
            con.close()

        return out

    def table_distribution(table: str, column: str, db_name: str = "user.sqlite3", max_rows: int = 12) -> list[str]:
        db = PROJECT_ROOT / "artifacts" / "db" / db_name
        con = _connect(db)
        if con is None:
            return []

        out: list[str] = []
        try:
            if table not in _tables(con):
                return []
            if column not in _columns(con, table):
                return []

            q = f"""
            SELECT COALESCE(NULLIF(trim(cast({column} AS text)), ''), '<empty>') AS item,
                   COUNT(*) AS n
            FROM {table}
            GROUP BY item
            ORDER BY n DESC
            LIMIT ?
            """

            for r in con.execute(q, (max_rows,)).fetchall():
                out.append(f"- {r['item']}: {r['n']}")
        finally:
            con.close()

        return out

    memory_samples = collect_samples("memories", limit)
    observation_samples = collect_samples("observations", min(6, limit))
    conversation_samples = collect_samples("conversation_turns", min(6, limit))

    lines = [
        "Grounded memory inventory:",
        f"- counted_memory_rows: {counts.get('total_rows', 0)}",
        "",
        "Databases:",
    ]

    for db in counts["databases"]:
        lines.append(f"- {db['path']} exists={db['exists']}")
        interesting = {
            k: v for k, v in db.get("tables", {}).items()
            if k in {"memories", "conversation_turns", "observations", "habits", "improvements", "recall_log"}
        }
        for k, v in interesting.items():
            suffix = " [not counted as memory]" if k == "recall_log" else ""
            lines.append(f"  - {k}: {v}{suffix}")

    lines.append("")
    lines.append("Memory table distribution:")
    kind_dist = table_distribution("memories", "kind")
    source_dist = table_distribution("memories", "source")

    if kind_dist:
        lines.append("- kind:")
        lines.extend(f"  {x}" for x in kind_dist)

    if source_dist:
        lines.append("- source:")
        lines.extend(f"  {x}" for x in source_dist)

    lines.append("")
    lines.append("Long-term memory samples:")

    if memory_samples:
        for item in memory_samples:
            lines.append(f"- user.sqlite3:memories: {item}")
    else:
        lines.append("- No non-noise long-term memory samples found.")

    lines.append("")
    lines.append("Observation samples:")

    if observation_samples:
        for item in observation_samples:
            lines.append(f"- user.sqlite3:observations: {item}")
    else:
        lines.append("- No non-noise observation samples found.")

    lines.append("")
    lines.append("Recent conversation samples:")
    if conversation_samples:
        for item in conversation_samples:
            lines.append(f"- user.sqlite3:conversation_turns: {item}")
    else:
        lines.append("- No non-noise conversation samples found.")

    return "\n".join(lines).strip()



def direct_grounded_answer(user_text: str) -> Optional[str]:
    low = (user_text or "").lower().strip()

    identity_triggers = (
        "what is my name",
        "who am i",
        "preferred name",
        "nickname",
        "do you know my name",
        "you do not know my name",
        "you don't know my name",
    )

    memory_inventory_triggers = (
        "what do they contain",
        "what is in the memories",
        "what's in the memories",
        "what the fuck is in the memories",
        "tell me everything from your memory",
        "what do your memories contain",
        "what is stored in memory",
        "memory contents",
    )

    if any(x in low for x in identity_triggers):
        return format_user_identity()

    if any(x in low for x in memory_inventory_triggers):
        return format_memory_inventory(limit=18)

    return None
