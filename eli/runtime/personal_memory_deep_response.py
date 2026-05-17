from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

CATEGORY_PATTERNS = {
    "ELI / MKXI / local assistant engineering": re.compile(
        r"\b(eli|mkxi|mkix|jarvis|agent|orchestrator|gguf|llama|runtime|router|executor|"
        r"memory|faiss|sqlite|tts|stt|voice|piper|wake word|proactive|habit|reflection|"
        r"self[- ]?upgrade|capability|plugin|pyqt|gui|ollama)\b",
        re.I,
    ),
    "local hardware / OS / deployment": re.compile(
        r"\b(ubuntu|fedora|linux|nvidia|rtx|gtx|cuda|vram|gpu|cpu|i7|ram|wine|steam|"
        r"flatpak|virtualbox|vm|driver|alma|m1 mac|mac)\b",
        re.I,
    ),
    "physics / mathematics / research framework": re.compile(
        r"\b(xi|χ|chi|phi|stueckelberg|scalar|lagrangian|field|entropy|coherence|"
        r"photon|mass|gauge|feynman|simulation|fenics|dealii|meep|openfoam|paraview|"
        r"quantum|relativity|thermodynamic|cosmology)\b",
        re.I,
    ),
    "writing / publication / documents": re.compile(
        r"\b(paper|latex|tex|pdf|publication|submission|journal|cover letter|report|"
        r"summary|outreach|manuscript|book|chapter|document)\b",
        re.I,
    ),
    "tone / interaction preferences": re.compile(
        r"\b(direct|truth|bullshit|honest|rigorous|brutal|no vague|in depth|"
        r"personalised|personalized|sarcasm|dark wit|no bro|adversarial|challenge)\b",
        re.I,
    ),
    "audio / media / desktop control": re.compile(
        r"\b(spotify|netflix|youtube|soundcloud|prime|volume|pause|resume|screen|window|"
        r"tile|grid|microphone|whisper|speech|stt|tts)\b",
        re.I,
    ),
    "career / education / work": re.compile(
        r"\b(wayfair|clinic|ace consultants|asbestos|apprenticeship|lab technician|"
        r"survey|cv|resume|job|application|course|diploma|haccp|coshh|first aid)\b",
        re.I,
    ),
}

TEXT_COL_PRIORITY = (
    "content", "text", "memory", "value", "summary", "body", "message",
    "user_message", "assistant_message", "observation", "details", "description",
)

def _root() -> Path:
    return Path(os.environ.get("ELI_PROJECT_ROOT", Path.cwd())).resolve()

def _db_paths() -> Dict[str, Path]:
    root = _root()
    return {
        "user": root / "artifacts" / "db" / "user.sqlite3",
        "agent": root / "artifacts" / "db" / "agent.sqlite3",
    }

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone() is not None
    except Exception:
        return False

def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        return []

def _tables(conn: sqlite3.Connection) -> List[str]:
    try:
        return [
            str(r[0])
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    except Exception:
        return []

def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] or 0)
    except Exception:
        return 0

def _pick_text_cols(cols: List[str]) -> List[str]:
    chosen = [c for c in TEXT_COL_PRIORITY if c in cols]
    if chosen:
        return chosen[:3]
    return [c for c in cols if any(k in c.lower() for k in ("text", "content", "message", "summary", "memory"))][:3]

def _order_clause(cols: List[str]) -> str:
    for c in ("timestamp", "ts", "created_at", "updated_at", "id"):
        if c in cols:
            return f" ORDER BY {c} DESC"
    return ""

def _sanitize_snippet(s: Any, max_len: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(s or "")).strip()
    text = text.replace("\x00", "")
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text

def _fetch_text_rows(conn: sqlite3.Connection, table: str, limit: int = 160) -> List[str]:
    if not _table_exists(conn, table):
        return []
    cols = _columns(conn, table)
    text_cols = _pick_text_cols(cols)
    if not text_cols:
        return []

    select_cols = ", ".join(text_cols)
    where = ""
    if "role" in cols and table == "conversation_turns":
        where = " WHERE role='user'"

    sql = f"SELECT {select_cols} FROM {table}{where}{_order_clause(cols)} LIMIT ?"
    out: List[str] = []
    try:
        for row in conn.execute(sql, (limit,)).fetchall():
            merged = " | ".join(_sanitize_snippet(x, 320) for x in row if str(x or "").strip())
            merged = _sanitize_snippet(merged, 320)
            if merged and merged not in out:
                out.append(merged)
    except Exception:
        return []
    return out

def _schema_summary(conn: sqlite3.Connection) -> List[str]:
    lines = []
    for table in _tables(conn):
        cols = _columns(conn, table)
        n = _count(conn, table)
        if table.endswith("_fts_config") or table.endswith("_fts_data") or table.endswith("_fts_docsize") or table.endswith("_fts_idx"):
            continue
        lines.append(f"- {table}: {n} rows; columns: {', '.join(cols[:10])}{'…' if len(cols) > 10 else ''}")
    return lines

def _static_memory_functions() -> List[str]:
    root = _root()
    files = [
        root / "eli" / "memory" / "memory.py",
        root / "eli" / "memory" / "memory_adapter.py",
        root / "eli" / "memory" / "memory_service.py",
        root / "eli" / "memory" / "vector_store.py",
        root / "eli" / "memory" / "knowledge_graph.py",
        root / "eli" / "cognition" / "agent_bus.py",
        root / "eli" / "cognition" / "orchestrator.py",
        root / "eli" / "cognition" / "context_synthesiser.py",
        root / "eli" / "cognition" / "user_info_builder.py",
        root / "eli" / "runtime" / "personal_memory_surface.py",
        root / "eli" / "runtime" / "memory_evidence.py",
    ]

    found: List[str] = []
    for path in files:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        defs = re.findall(r"(?m)^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        key_defs = [
            d for d in defs
            if re.search(r"(memory|recall|store|search|fetch|vector|embed|context|profile|user|evidence|synth|agent)", d, re.I)
        ]
        if key_defs:
            rel = path.relative_to(root)
            found.append(f"- {rel}: {', '.join(key_defs[:18])}{'…' if len(key_defs) > 18 else ''}")
    return found

def _collect_personal_evidence() -> Dict[str, List[str]]:
    dbs = _db_paths()
    snippets: List[str] = []

    for db_name, db_path in dbs.items():
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path))
        except Exception:
            continue
        with conn:
            for table in ("memories", "observations", "conversation_turns", "habits", "improvements"):
                snippets.extend(_fetch_text_rows(conn, table, limit=220 if table == "memories" else 80))

    buckets: Dict[str, List[str]] = {name: [] for name in CATEGORY_PATTERNS}
    other: List[str] = []

    for s in snippets:
        placed = False
        for name, pat in CATEGORY_PATTERNS.items():
            if pat.search(s):
                if len(buckets[name]) < 8:
                    buckets[name].append(s)
                placed = True
        if not placed and len(other) < 8:
            other.append(s)

    buckets["other recent memory evidence"] = other
    return buckets

def _runtime_counts() -> List[str]:
    lines = []
    for name, db in _db_paths().items():
        if not db.exists():
            lines.append(f"- {name}.sqlite3: missing at {db}")
            continue
        try:
            conn = sqlite3.connect(str(db))
            with conn:
                tables = _tables(conn)
                lines.append(f"- {name}.sqlite3: {len(tables)} tables at {db}")
                for t in ("memories", "conversation_turns", "observations", "recall_log", "habits", "improvements"):
                    if t in tables:
                        lines.append(f"  - {t}: {_count(conn, t)} rows")
        except Exception as e:
            lines.append(f"- {name}.sqlite3: read failed: {type(e).__name__}: {e}")
    vec = _root() / "artifacts" / "vectors" / "index.faiss"
    meta = _root() / "artifacts" / "vectors" / "meta.pkl"
    lines.append(f"- FAISS index: {vec} ({'exists' if vec.exists() else 'missing'})")
    lines.append(f"- FAISS metadata: {meta} ({'exists' if meta.exists() else 'missing'})")
    return lines

def _schema_blocks() -> List[str]:
    out = []
    for name, db in _db_paths().items():
        if not db.exists():
            continue
        try:
            conn = sqlite3.connect(str(db))
            with conn:
                out.append(f"{name}.sqlite3 schema:")
                out.extend(_schema_summary(conn)[:40])
        except Exception as e:
            out.append(f"{name}.sqlite3 schema read failed: {type(e).__name__}: {e}")
    return out

def build_personal_memory_deep_response(user_input: str = "", mode_label: str = "") -> str:
    buckets = _collect_personal_evidence()
    counts = _runtime_counts()
    schema = _schema_blocks()
    funcs = _static_memory_functions()

    lines: List[str] = []

    lines.append("You are right: that should not have been a raw memory-count dump.")
    lines.append("")
    lines.append(
        "The correct behaviour here is: use deterministic inspection as evidence, then answer in ELI's normal voice with the memory architecture, the actual files/tables/functions involved, and a personalised synthesis of what the memory store contains. The instant truth report is useful for quick diagnostics, but it is not enough when you explicitly ask for a full personalised answer."
    )
    lines.append("")

    lines.append("## How my memory system works internally")
    lines.append("")
    lines.append("At runtime, memory is split across three practical layers:")
    lines.append("")
    lines.append("1. **SQLite factual store** — durable rows for memories, conversation turns, observations, habits, recall logs, and related metadata.")
    lines.append("2. **FTS/vector retrieval layer** — SQLite FTS and FAISS/nomic embeddings for semantic recall over stored material.")
    lines.append("3. **Cognition assembly layer** — AgentBus, orchestrator, context synthesiser, user-info builder, response governance, and the final model prompt handoff.")
    lines.append("")

    lines.append("## Live storage paths")
    lines.extend(counts)
    lines.append("")

    lines.append("## Main DB tables I can see")
    lines.extend(schema[:70] or ["- No schema evidence found."])
    lines.append("")

    lines.append("## Main files/functions involved")
    lines.extend(funcs or ["- No static memory functions found by the scanner."])
    lines.append("")

    lines.append("## What I actually remember about you, grouped by evidence")
    lines.append("")
    any_bucket = False
    for category, items in buckets.items():
        if not items:
            continue
        any_bucket = True
        lines.append(f"### {category}")
        for item in items[:8]:
            lines.append(f"- {item}")
        lines.append("")

    if not any_bucket:
        lines.append("I found memory tables, but this scanner did not extract enough readable personal snippets to produce a reliable personalised summary.")
        lines.append("")

    lines.append("## Operational diagnosis")
    lines.append("")
    lines.append("- The low-level memory diagnostic surface is not a personalised memory answer.")
    lines.append("- Your non-quick modes should increase synthesis depth; they should not cause the router to dump raw counts.")
    lines.append("- For questions like this, the correct route is `PERSONAL_MEMORY_DEEP_EXPLAIN`, not `EXPLAIN_MEMORY_RUNTIME`, `MEMORY_STATUS`, browser/search, or generic chat.")
    lines.append("- If I do not have enough evidence to answer a specific part, I should say that directly instead of inventing browser, graph-database, or online-service explanations.")
    lines.append("")

    return "\n".join(lines).strip()

def build_routing_fault_explanation(user_input: str = "") -> str:
    return (
        "No, that should not have gone to browser/search.\n\n"
        "What actually happened: the router treated your complaint or personalised-memory request as a generic/search-style query instead of preserving it as a local cognition/memory question. Then the local model invented a bogus explanation about using an online service or graph database. That explanation is not grounded by the runtime evidence.\n\n"
        "Correct behaviour: for this kind of message I should answer locally, explain the routing fault, and either repair the action path or give you the exact file/function/table-level breakdown from the local SQLite/FAISS memory stack. No browser. No fake excuses. No data dump unless you explicitly ask for diagnostic counts."
    )

__all__ = [
    "build_personal_memory_deep_response",
    "build_routing_fault_explanation",
]

# =============================================================================
# FINAL CLEAN PERSONAL MEMORY RESPONSE OVERRIDE
# Replaces older schema-dump/reflection-spam response surfaces.
# =============================================================================
try:
    from eli.runtime.personal_memory_clean_response import build_clean_personal_memory_response as _eli_clean_personal_memory_response

    def build_personal_memory_deep_response(user_input: str = "", mode_label: str = "") -> str:  # type: ignore[override]
        return _eli_clean_personal_memory_response(user_input=user_input, mode_label=mode_label)

    print("[MEMORY] clean personal-memory response override installed", flush=True)

except Exception as _eli_clean_personal_memory_err:
    print(f"[MEMORY] clean personal-memory response override failed: {_eli_clean_personal_memory_err}", flush=True)
# =============================================================================
