import json
from pathlib import Path

import pytest

from eli.learning.export_trainable_dataset import export_for_target


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def read_jsonl(path: Path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_targeted_export_keeps_only_matching_reviewed_rows(tmp_path):
    src = tmp_path / "candidate.jsonl"
    out = tmp_path / "phi.trainable.jsonl"

    write_jsonl(src, [
        {
            "instruction": "Who are you?",
            "response": "I maintain a Phi-targeted ELI self-model.",
            "tags": ["reviewed", "self_model"],
            "targets": ["eli_phi"],
            "weight": 0.8,
        },
        {
            "instruction": "Who are you, Ultra?",
            "response": "I maintain an Ultra-targeted ELI self-model.",
            "tags": ["reviewed", "self_model"],
            "targets": ["eli_phi_ultra"],
            "weight": 0.8,
        },
        {
            "instruction": "Generic unreviewed row",
            "response": "This must not train.",
            "tags": ["needs_review"],
            "targets": ["eli_phi"],
            "weight": 0.35,
        },
    ])

    report = export_for_target(src=src, target="eli_phi", out=out)
    rows = read_jsonl(out)

    assert report["count"] == 1
    assert len(rows) == 1
    assert rows[0]["instruction"] == "Who are you?"
    assert rows[0]["target"] == "eli_phi"
    assert rows[0]["training_scope"] == "phi_targeted_lora_only"


def test_targeted_export_rejects_reviewed_rows_without_explicit_target(tmp_path):
    src = tmp_path / "candidate.jsonl"
    out = tmp_path / "phi.trainable.jsonl"

    write_jsonl(src, [
        {
            "instruction": "Who are you?",
            "response": "Reviewed but targetless. Should not export.",
            "tags": ["reviewed", "self_model"],
            "weight": 0.8,
        }
    ])

    report = export_for_target(src=src, target="eli_phi", out=out)

    assert report["count"] == 0
    assert report["rejected"]["missing_or_wrong_target"] == 1
    assert read_jsonl(out) == []


def test_targeted_export_refuses_generic_target(tmp_path):
    src = tmp_path / "candidate.jsonl"
    out = tmp_path / "generic.trainable.jsonl"

    write_jsonl(src, [
        {
            "instruction": "Who are you?",
            "response": "This should never export to generic GGUF.",
            "tags": ["reviewed"],
            "targets": ["generic_gguf"],
        }
    ])

    with pytest.raises(SystemExit):
        export_for_target(src=src, target="generic_gguf", out=out)
