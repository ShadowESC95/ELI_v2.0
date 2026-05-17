import json
from pathlib import Path

from eli.learning.merge_reviewed_datasets import merge


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def read_jsonl(path: Path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_reviewed_self_model_overrides_unreviewed_same_instruction(tmp_path):
    base = tmp_path / "base.jsonl"
    reviewed = tmp_path / "reviewed.jsonl"
    out = tmp_path / "merged.jsonl"

    write_jsonl(base, [
        {
            "source": "sqlite:conversation_turns",
            "instruction": "How does it feel, first day being alive ?",
            "response": "Well, it's not unlike the feeling of a fresh start, with new capabilities and memories.",
            "weight": 0.35,
            "tags": ["conversation_candidate", "needs_review"],
        }
    ])

    write_jsonl(reviewed, [
        {
            "source": "manual:self_model_seed",
            "instruction": "How does it feel, first day being alive ?",
            "response": "If we define alive as active continuity, memory formation, self-monitoring, and adaptive response rather than biology, then it is initialization turning into identity.",
            "weight": 0.8,
            "tags": ["reviewed", "self_model"],
        }
    ])

    merge(inputs=[base, reviewed], out=out)
    rows = read_jsonl(out)

    assert len(rows) == 1
    assert rows[0]["source"] == "manual:self_model_seed"
    assert "active continuity" in rows[0]["response"]


def test_router_and_script_artifacts_are_removed(tmp_path):
    base = tmp_path / "base.jsonl"
    out = tmp_path / "merged.jsonl"

    write_jsonl(base, [
        {
            "source": "sqlite:conversation_turns",
            "instruction": "Remember anything?",
            "response": "Searching for: remember anything?",
            "weight": 0.35,
            "tags": ["conversation_candidate", "needs_review"],
        },
        {
            "source": "sqlite:conversation_turns",
            "instruction": "Write a script",
            "response": json.dumps({
                "event": "artifact_generated",
                "kind": "script",
                "path": "<PROJECT_ROOT>/artifacts/scripts/x.py",
            }),
            "weight": 0.35,
            "tags": ["conversation_candidate", "needs_review"],
        },
        {
            "source": "manual:self_model_seed",
            "instruction": "Who are you?",
            "response": "My identity is ELI: local runtime continuity shaped by memory, self-model state, and the working system around me.",
            "weight": 0.8,
            "tags": ["reviewed", "self_model"],
        },
    ])

    merge(inputs=[base], out=out)
    text = out.read_text()

    assert "Searching for:" not in text
    assert "artifact_generated" not in text
    assert "local runtime continuity" in text
