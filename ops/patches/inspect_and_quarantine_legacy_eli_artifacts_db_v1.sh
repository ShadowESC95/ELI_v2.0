#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="ops/reports/legacy_wrong_memory_db_${STAMP}.txt"
WRONG_DB="eli/artifacts/user.sqlite3"
QUARANTINE="ops/quarantine_db/eli_artifacts_user_${STAMP}.sqlite3"

python3 - <<PY
from pathlib import Path
import sqlite3
import subprocess

wrong = Path("$WRONG_DB")
report = Path("$REPORT")
quarantine = Path("$QUARANTINE")

lines = []
lines.append(f"wrong_db={wrong}")
lines.append(f"exists={wrong.exists()}")

if wrong.exists():
    lines.append(f"size_bytes={wrong.stat().st_size}")
    con = sqlite3.connect(str(wrong))
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    lines.append(f"tables={tables!r}")

    row_counts = {}
    for t in tables:
        try:
            row_counts[t] = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        except Exception as e:
            row_counts[t] = f"ERR:{e}"
    lines.append(f"row_counts={row_counts!r}")

    dump_path = report.with_suffix(".sql")
    with dump_path.open("w", encoding="utf-8") as f:
        for line in con.iterdump():
            f.write(line + "\\n")
    lines.append(f"sql_dump={dump_path}")
    con.close()

    non_sqlite_tables = [t for t in tables if t != "sqlite_sequence"]
    has_payload = False
    for t, n in row_counts.items():
        if t == "sqlite_sequence":
            continue
        if isinstance(n, int) and n > 0:
            has_payload = True
        elif not isinstance(n, int):
            has_payload = True

    if not has_payload:
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        wrong.rename(quarantine)
        lines.append(f"action=quarantined_empty_or_nonpayload_db")
        lines.append(f"quarantine_path={quarantine}")
    else:
        lines.append("action=left_in_place_payload_present")
        lines.append("note=do_not_delete_until payload is reviewed/migrated")

report.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("\\n".join(lines))
PY

echo
echo "=== git status ==="
git status -sb

echo
echo "Report: $REPORT"
