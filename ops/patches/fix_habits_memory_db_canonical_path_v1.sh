#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import re

p = Path("eli/memory/habits_memory_db.py")
src = p.read_text(encoding="utf-8")
orig = src

helper = r'''
def _eli_canonical_user_db_path() -> Path:
    """
    Canonical user memory DB path.

    Memory/habit storage must resolve to:
        <project_root>/artifacts/db/user.sqlite3

    Do not fall back to:
        <project_root>/artifacts/user.sqlite3
        <project_root>/eli/artifacts/user.sqlite3
    """
    try:
        from eli.core.paths import user_db_path
        return Path(user_db_path())
    except Exception:
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "artifacts" / "db").exists() or (parent / "eli").exists():
                return parent / "artifacts" / "db" / "user.sqlite3"
        return Path.cwd() / "artifacts" / "db" / "user.sqlite3"

'''

if "_eli_canonical_user_db_path" not in src:
    m = re.search(r"\ndef\s+", src)
    if not m:
        raise SystemExit("[PATCH] Could not find first function boundary for helper insertion")
    src = src[:m.start()+1] + helper + src[m.start()+1:]

replacements = {
    'str(_artifacts_dir() / "user.sqlite3")':
        'str(_eli_canonical_user_db_path())',

    'str(Path(__file__).resolve().parent.parent / "artifacts" / "user.sqlite3")':
        'str(_eli_canonical_user_db_path())',

    'str(Path(__file__).resolve().parent.parent / "artifacts" / "db" / "user.sqlite3")':
        'str(_eli_canonical_user_db_path())',
}

for old, new in replacements.items():
    src = src.replace(old, new)

if src == orig:
    raise SystemExit("[PATCH] No changes made; inspect habits_memory_db.py manually")

p.write_text(src, encoding="utf-8")
print("[PATCH] habits_memory_db.py now uses canonical user DB fallback")
PY

python3 -m py_compile \
  eli/memory/habits_memory_db.py \
  eli/memory/memory.py \
  eli/memory/__init__.py \
  eli/core/paths.py

echo
echo "=== remaining suspicious habits DB path strings ==="
grep -nE 'parent\.parent.*/?"artifacts".*/?"user\.sqlite3"|_artifacts_dir\(\).*/?"user\.sqlite3"|artifacts.*/user\.sqlite3' \
  eli/memory/habits_memory_db.py || true

echo
echo "=== canonical path sanity ==="
python3 - <<'PY'
from pathlib import Path
from eli.core.paths import user_db_path, agent_db_path, memory_db_path
from eli.memory import get_memory_status

print("user_db_path   =", user_db_path())
print("agent_db_path  =", agent_db_path())
print("memory_db_path =", memory_db_path())
print("user_exists    =", Path(user_db_path()).exists())
print("agent_exists   =", Path(agent_db_path()).exists())

st = get_memory_status(user_db_path())
print("memory_status_keys =", sorted(st.keys()))
print("memory_status =", st)
PY

git diff -- eli/memory/habits_memory_db.py
git diff --check
