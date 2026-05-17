#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import ast
import json
import re
import sqlite3
import subprocess
import time

root = Path(".")
stamp = time.strftime("%Y%m%d_%H%M%S")
out = root / "ops" / "reports" / f"memory_runtime_contract_audit_{stamp}"
out.mkdir(parents=True, exist_ok=True)

def write(name: str, text: str) -> None:
    (out / name).write_text(text, encoding="utf-8")

def sh(cmd: str, timeout: int = 30) -> str:
    try:
        return subprocess.check_output(
            cmd,
            shell=True,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as e:
        return (e.output or "") + f"\n[exit {e.returncode}]\n"
    except Exception as e:
        return f"[{type(e).__name__}: {e}]\n"

git_state = sh(
    "git status -sb && echo && git log --oneline --decorate -12 && echo && git tag --points-at HEAD",
    timeout=30,
)
write("00_git_state.txt", git_state)

tracked = [
    line.strip()
    for line in sh("git ls-files", timeout=30).splitlines()
    if line.strip()
]

scan_files = []
for rel in tracked:
    p = root / rel
    if not p.is_file():
        continue
    if rel.startswith(("artifacts/", ".git/", ".venv/", "ops/reports/")):
        continue
    if p.suffix.lower() not in {".py", ".sh", ".json", ".md", ".txt", ".yaml", ".yml"}:
        continue
    if rel.startswith("eli/") or rel.startswith("ops/probes/") or rel.startswith("ops/patches/"):
        scan_files.append(rel)

contract_re = re.compile(
    r"EXPLAIN_MEMORY_RUNTIME|MEMORY_STATUS|MEMORY_RECALL|MEMORY_COUNT|"
    r"PERSONAL_MEMORY_SUMMARY|PERSONAL_MEMORY_DEEP_EXPLAIN|"
    r"get_memory_status|resolve_db_paths|get_memory\(|get_agent_memory|get_search_memory|"
    r"memory_truth_report|_runtime_memory_snapshot|_build_grounded_evidence_context|"
    r"recall_recent|memory_recent_fn|memory_search_fn|memory_store_fn|"
    r"user\.sqlite3|agent\.sqlite3|memory\.sqlite3|"
    r"conversation_turns|conversations|memories|memories_fts|recall_log|"
    r"learning_replay|runtime_events|observations|habit_events|improvements|failures|"
    r"ELI_MEMORY_DB|ELI_MEMORY_DB_PATH|memory_db_path|user_db_path|agent_db_path",
    re.IGNORECASE,
)

bad_surface_re = re.compile(
    r"Tree of Thoughts Memory Model|mental model of past interactions|"
    r"does not rely on specific files|complex network of interconnected thoughts|"
    r"cannot confirm.*without further evidence|not readily available|"
    r"previous interactions may not be readily available|always here to help|"
    r"dynamic persona layer.*memories|generic memory system|"
    r"memory system uses SQLite databases.*various types of information",
    re.IGNORECASE,
)

hits_by_file = {}
bad_by_file = {}

for rel in scan_files:
    p = root / rel
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        continue

    hits = []
    bads = []

    for n, line in enumerate(lines, 1):
        if contract_re.search(line):
            hits.append(f"{rel}:{n}: {line[:240]}")
        if bad_surface_re.search(line):
            bads.append(f"{rel}:{n}: {line[:240]}")

    if hits:
        hits_by_file[rel] = hits
    if bads:
        bad_by_file[rel] = bads

focused = []
for rel in sorted(hits_by_file):
    hits = hits_by_file[rel]
    focused.append(f"\n### {rel} ({len(hits)} hits, capped at 45)")
    focused.extend(hits[:45])
    if len(hits) > 45:
        focused.append(f"... capped: {len(hits) - 45} more hits omitted")
write("01_focused_memory_contract_hits_capped.txt", "\n".join(focused).strip() + "\n")

counts = [
    f"{len(v):5d}  {k}"
    for k, v in sorted(hits_by_file.items(), key=lambda kv: (-len(kv[1]), kv[0]))
]
write("02_hit_counts_by_file.txt", "\n".join(counts) + "\n")

bad = []
for rel in sorted(bad_by_file):
    entries = bad_by_file[rel]
    bad.append(f"\n### {rel} ({len(entries)} suspicious generic-memory strings)")
    bad.extend(entries[:80])
    if len(entries) > 80:
        bad.append(f"... capped: {len(entries) - 80} more suspicious lines omitted")
write("03_suspicious_generic_memory_surfaces.txt", "\n".join(bad).strip() + ("\n" if bad else "NONE\n"))

defs = []
name_re = re.compile(
    r"memory|recall|store|sqlite|db|status|runtime|grounded|truth|working|habit|conversation",
    re.IGNORECASE,
)

for rel in scan_files:
    if not rel.endswith(".py"):
        continue
    p = root / rel
    try:
        src = p.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
    except Exception as e:
        if "memory" in rel.lower():
            defs.append(f"{rel}: AST_PARSE_FAILED: {type(e).__name__}: {e}")
        continue

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = getattr(node, "name", "")
            if name_re.search(name) or "memory" in rel.lower():
                kind = type(node).__name__
                start = getattr(node, "lineno", "?")
                end = getattr(node, "end_lineno", "?")
                defs.append(f"{rel}:{start}-{end}: {kind} {name}")

write("04_relevant_defs_classes.txt", "\n".join(sorted(defs)) + "\n")

inventory = []
for rel in tracked:
    low = rel.lower()
    if (
        rel.startswith("eli/memory/")
        or "memory" in low
        or "recall" in low
        or "habit" in low
        or "runtime_status" in low
        or "grounded_control" in low
    ):
        inventory.append(rel)
write("05_memory_file_inventory.txt", "\n".join(sorted(set(inventory))) + "\n")

def schema_summary(db_path: Path) -> str:
    lines = [f"\n## {db_path}"]
    lines.append(f"exists: {db_path.exists()}")
    if not db_path.exists():
        return "\n".join(lines)

    try:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()

        rows = cur.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        ).fetchall()

        lines.append(f"tables/views: {len(rows)}")

        for name, typ in rows:
            try:
                count = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except Exception:
                count = "?"
            try:
                cols = [
                    r[1]
                    for r in cur.execute(f'PRAGMA table_info("{name}")').fetchall()
                ]
            except Exception:
                cols = []
            lines.append(f"- {typ} {name} rows={count} cols={cols}")

        con.close()
    except Exception as e:
        lines.append(f"ERROR: {type(e).__name__}: {e}")

    return "\n".join(lines)

dbs = [
    Path("artifacts/db/user.sqlite3"),
    Path("artifacts/db/agent.sqlite3"),
    Path("artifacts/db/memory.sqlite3"),
    Path("artifacts/user.sqlite3"),
    Path("eli/artifacts/user.sqlite3"),
]
write("06_sqlite_schema_summary.txt", "\n".join(schema_summary(p) for p in dbs).strip() + "\n")

env_hits = sh(
    "git grep -nE 'ELI_MEMORY_DB|ELI_MEMORY_DB_PATH|user_db_path|agent_db_path|memory_db_path|resolve_db_paths|user.sqlite3|agent.sqlite3|memory.sqlite3' -- . ':!ops/reports' || true",
    timeout=30,
)
write("07_db_path_env_and_config_hits.txt", env_hits)

route_hits = sh(
    "git grep -nE 'EXPLAIN_MEMORY_RUNTIME|MEMORY_STATUS|MEMORY_RECALL|PERSONAL_MEMORY_SUMMARY|PERSONAL_MEMORY_DEEP_EXPLAIN|_evidence_action_for_prompt|_intent_requires_grounding|_classify_query|memory-runtime|memory runtime|memory_truth_report|_runtime_memory_snapshot|_build_grounded_evidence_context' -- eli ops/probes ops/patches ':!ops/reports' || true",
    timeout=30,
)
write("08_route_executor_memory_hits.txt", route_hits)

known_tables = [
    "memories",
    "memories_fts",
    "conversation_turns",
    "conversations",
    "recall_log",
    "learning_replay",
    "runtime_events",
    "observations",
    "habit_events",
    "habit_rules",
    "habits",
    "improvements",
    "failures",
    "session_summaries",
    "user_patterns",
]
table_probe = []
for db in [Path("artifacts/db/user.sqlite3"), Path("artifacts/db/agent.sqlite3")]:
    table_probe.append(f"\n## {db}")
    if not db.exists():
        table_probe.append("MISSING")
        continue
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    for table in known_tables:
        try:
            n = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            table_probe.append(f"{table}: {n}")
        except Exception as e:
            table_probe.append(f"{table}: unavailable ({type(e).__name__})")
    con.close()
write("09_known_memory_table_counts.txt", "\n".join(table_probe).strip() + "\n")

summary = []
summary.append(f"Memory-runtime contract audit: {out}")
summary.append("")
summary.append("Git head:")
summary.append(sh("git log --oneline --decorate -1", timeout=10).strip())
summary.append("")
summary.append("Focused contract hits by file:")
summary.extend(counts[:40] if counts else ["NONE"])
summary.append("")
summary.append(f"Relevant defs/classes found: {len(defs)}")
summary.append(f"Suspicious generic-memory files: {len(bad_by_file)}")
summary.append("")
summary.append("Core DB counts:")
summary.append((out / "09_known_memory_table_counts.txt").read_text(encoding="utf-8"))
summary.append("")
summary.append("Generated files:")
for child in sorted(out.iterdir()):
    summary.append(f"- {child}")

write("SUMMARY.txt", "\n".join(summary) + "\n")

print("\n".join(summary))
PY
