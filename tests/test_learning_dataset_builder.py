import json
import sqlite3
from pathlib import Path

from eli.learning.dataset_builder import build_dataset


def make_db(path: Path, pairs):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE conversation_turns (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            user_id TEXT,
            role TEXT,
            content TEXT,
            ts REAL,
            timestamp REAL
        )
        """
    )

    i = 1
    for user_text, assistant_text in pairs:
        con.execute(
            "INSERT INTO conversation_turns(id, role, content) VALUES (?, ?, ?)",
            (i, "user", user_text),
        )
        i += 1
        con.execute(
            "INSERT INTO conversation_turns(id, role, content) VALUES (?, ?, ?)",
            (i, "assistant", assistant_text),
        )
        i += 1

    con.commit()
    con.close()


def read_jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_dataset_builder_extracts_basic_pairs(tmp_path):
    db = tmp_path / "user.sqlite3"
    out = tmp_path / "dataset.jsonl"
    report = tmp_path / "report.json"

    make_db(
        db,
        [
            (
                "What is ELI?",
                "ELI is the local assistant runtime connected to memory, tools, and the local model.",
            )
        ],
    )

    result = build_dataset(db, out, report)

    assert result["ok"] is True
    assert result["count"] == 1

    rows = read_jsonl(out)
    assert rows[0]["instruction"] == "What is ELI?"
    assert "local assistant runtime" in rows[0]["response"]


def test_dataset_builder_redacts_private_paths(tmp_path):
    db = tmp_path / "user.sqlite3"
    out = tmp_path / "dataset.jsonl"
    report = tmp_path / "report.json"

    make_db(
        db,
        [
            (
                "Where was the script saved?",
                "The script was saved at /home/jay/Desktop/ELI_MKXI/artifacts/scripts/example.py.",
            )
        ],
    )

    result = build_dataset(db, out, report)

    assert result["ok"] is True
    assert result["count"] == 1

    rows = read_jsonl(out)
    assert "/home/jay" not in rows[0]["response"]
    assert "<PROJECT_ROOT>" in rows[0]["response"]


def test_dataset_builder_rejects_old_ai_language_model_identity_poison(tmp_path):
    db = tmp_path / "user.sqlite3"
    out = tmp_path / "dataset.jsonl"
    report = tmp_path / "report.json"

    make_db(
        db,
        [
            (
                "Who are you?",
                "This assistant is an AI language model developed to assist and engage in conversations.",
            )
        ],
    )

    result = build_dataset(db, out, report)

    assert result["ok"] is True
    assert result["count"] == 0
    assert result["rejected"].get("bad_surface_or_traceback", 0) >= 1
