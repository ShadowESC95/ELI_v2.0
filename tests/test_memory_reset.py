"""memory_reset — the factory-reset / fresh-slate file+DB operations. Real sqlite &
json, all isolated to tmp. These are load-bearing for privacy (wiping personal data).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from eli.core import memory_reset as mr


def test_counts():
    t = {"db": [Path("a"), Path("b")], "json": [Path("c")]}
    assert mr.counts(t) == {"db": 2, "json": 1}


def test_clear_db_wipes_rows_keeps_schema(tmp_path):
    p = tmp_path / "m.sqlite3"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, text TEXT)")
    c.executemany("INSERT INTO facts(text) VALUES(?)", [("a",), ("b",), ("c",)])
    c.commit(); c.close()
    assert mr.clear_db(p) == 3                       # 3 rows cleared
    c = sqlite3.connect(str(p))
    assert c.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0     # rows gone
    assert c.execute("SELECT name FROM sqlite_master WHERE name='facts'").fetchone()  # schema kept
    c.close()


def test_clear_db_keep_tables(tmp_path):
    p = tmp_path / "m.sqlite3"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, t TEXT)")
    c.execute("CREATE TABLE habits(id INTEGER PRIMARY KEY, t TEXT)")
    c.execute("INSERT INTO facts(t) VALUES('x')")
    c.execute("INSERT INTO habits(t) VALUES('keep')")
    c.commit(); c.close()
    mr.clear_db(p, keep_tables={"habits"})
    c = sqlite3.connect(str(p))
    assert c.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0     # wiped
    assert c.execute("SELECT COUNT(*) FROM habits").fetchone()[0] == 1    # kept
    c.close()


def test_scrub_json_names(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"user_name": "Alex", "nested": {"name": "Bob", "keep": "ok"}}),
                 encoding="utf-8")
    assert mr.scrub_json_names(p) == 2               # user_name + nested.name
    d = json.loads(p.read_text())
    assert d["user_name"] == "" and d["nested"]["name"] == "" and d["nested"]["keep"] == "ok"


def test_clear_settings_name(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"user_name": "Alex", "theme": "dark"}), encoding="utf-8")
    assert mr.clear_settings_name(p) is True
    assert json.loads(p.read_text())["user_name"] == ""
    assert mr.clear_settings_name(p) is False        # nothing left to clear
