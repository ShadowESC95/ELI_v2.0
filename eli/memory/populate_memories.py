#!/usr/bin/env python3
"""
Populate memories from existing conversations.
Run it from the project root.
"""

import os
import sys
import sqlite3
from pathlib import Path

# Ensure we can import from the project
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("ELI_ROOT", str(project_root / "eli"))

from eli.core.paths import get_paths
from eli.memory import Memory

DB_PATH = get_paths().user_db

def get_recent_conversations(limit=500):
    """Fetch recent conversation turns."""
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return []
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    # Adjust table/column names if needed – your schema likely matches
    cur.execute("""
        SELECT role, content, timestamp FROM conversations
        ORDER BY timestamp DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows

def main():
    mem = Memory()
    convs = get_recent_conversations()
    if not convs:
        print("No conversations found.")
        return

    stored = 0
    for role, content, ts in convs:
        if role.lower() == "user":   # store only user messages (optional)
            result = mem.store_memory(content, tags=["conversation"])
            if result.get("ok"):
                stored += 1
                print(f"Stored ({stored}): {content[:60]}...")
            else:
                print(f"Failed: {content[:60]}...")

    print(f"\nStored {stored} memories from conversations.")

if __name__ == "__main__":
    main()
