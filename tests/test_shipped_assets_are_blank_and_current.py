"""Every download ships the current structure with none of the owner's data."""
import hashlib
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "config" / "templates" / "db"
FTS_INTERNALS = ("_fts_data", "_fts_idx", "_fts_docsize", "_fts_config")

# sha256 of identifiers that must never appear in a tracked text file (stored hashed on purpose).
DENIED = {
    "4c1001c251c1c923bca00789638afb17e908d526bf3e9975407c65d2b03f4b10",
    "fdee276f3cb6a67d315d6edc3e1f3c84a82703caf8b240ec08b726100d79e27b",
    "ba951dcb04651f7ff984fdd1be47cb6a1282fbc1c4f27fb2864635873423c417",
    "814569a1cf26a1c710faa80b51f2774759d11d84970c75e2f85b1def11e2a428",
    "23b03680d49f6dbf3c24f83a47037024616c3f383a3d4fedd50429a1b3d48b7a",
    "049c4c6467b13c6e9cea71a2bf8e57ffba34131bf2cbd3c20bb534b71d0a1726",
}
HOME_PATH = "/home/" + "jay"
ALLOWED_HOME_MENTION = {"docs/REDISTRIBUTABILITY_AUDIT.md"}   # states that no such path is present
TOKEN = re.compile(r"[A-Za-z0-9-]{4,40}")
SKIP_DIRS = ("models/", "build/", "dist/", ".github/", "blueprints/_md_backup")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".sh", ".iss", ".cfg", ".ini", ".bat", ".ps1"}


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    return [p for p in out if p and not p.startswith(SKIP_DIRS) and Path(p).suffix in TEXT_SUFFIXES]


def _templates():
    return sorted(TEMPLATES.glob("*.sqlite3"))


def test_the_four_blank_databases_are_shipped():
    assert {p.name for p in _templates()} == {
        "agent.sqlite3", "coding_memory.sqlite3", "system_index.sqlite3", "user.sqlite3"}


def test_no_template_holds_a_single_row_of_data():
    for db in _templates():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if table.endswith(FTS_INTERNALS):
                continue
            n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            assert n == 0, f"{db.name}.{table} ships {n} row(s)"
        con.close()


def test_templates_match_the_current_schema_columns_included():
    res = subprocess.run([sys.executable, "tools/seed_template_dbs.py", "--check"], cwd=ROOT,
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_the_memory_storage_policy_structure_is_in_the_template():
    con = sqlite3.connect(f"file:{TEMPLATES / 'user.sqlite3'}?mode=ro", uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(memories)")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"event_ts", "seen_count", "last_seen", "last_recalled", "recall_count", "origin", "text_key",
            "provenance_kind", "verification_status"} <= cols
    assert {"memories_archive", "memory_meta"} <= tables
    sem = {r[1] for r in con.execute("PRAGMA table_info(semantic)")}
    assert {"evidence_count", "last_seen", "evidence"} <= sem
    con.close()


def test_no_tracked_file_carries_the_owners_identifiers():
    hits = []
    for rel in _tracked():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if HOME_PATH in text and rel not in ALLOWED_HOME_MENTION:
            hits.append((rel, "home path"))
        for tok in set(TOKEN.findall(text.lower())):
            if hashlib.sha256(tok.encode()).hexdigest() in DENIED:
                hits.append((rel, "denied identifier"))
    assert not hits, hits[:10]


def test_local_run_artifacts_are_ignored():
    for path in ("runtime/x", "test_reports/x", "models/_download.log"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0, path
