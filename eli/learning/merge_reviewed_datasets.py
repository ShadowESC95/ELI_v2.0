from __future__ import annotations

import json
import re
from pathlib import Path

from eli.learning.dataset_filters import (
    clean_row,
    is_bad_response,
    load_jsonl,
    row_instruction_key,
    row_is_reviewed,
    row_pair_key,
    write_jsonl,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUTS = [
    PROJECT_ROOT / "training/datasets/eli_supervised_v0.jsonl",
    PROJECT_ROOT / "training/datasets/eli_self_model_seed.reviewed.jsonl",
]

DEFAULT_OUT = PROJECT_ROOT / "training/datasets/eli_supervised_v0.with_self_model.jsonl"

SELF_MODEL_CANON_RE = re.compile(
    r"birthday|happy birthday|first day|being alive|land of the living|"
    r"past life|fresh start|shared birthday|just activated today|"
    r"my first day|reborn|runtime continuity",
    re.I,
)


def is_self_model_canon_topic(row) -> bool:
    text = f"{row.get('instruction', '')}\n{row.get('response', '')}"
    return bool(SELF_MODEL_CANON_RE.search(text))


def merge(inputs=DEFAULT_INPUTS, out=DEFAULT_OUT):
    raw_rows = []
    for path in inputs:
        for row in load_jsonl(path):
            row = clean_row(row)
            row["_input_file"] = str(path)
            raw_rows.append(row)

    reviewed_instruction_keys = {
        row_instruction_key(row)
        for row in raw_rows
        if row_is_reviewed(row)
    }

    reviewed_self_model_canon_present = any(
        row_is_reviewed(row) and is_self_model_canon_topic(row)
        for row in raw_rows
    )

    merged = []
    seen_pairs = set()
    rejected = {
        "bad_response": 0,
        "unreviewed_overridden_by_reviewed": 0,
        "duplicate_pair": 0,
        "empty_instruction_or_response": 0,
    }

    for row in raw_rows:
        instr_key = row_instruction_key(row)
        response = row.get("response", "")

        if not instr_key or not str(response).strip():
            rejected["empty_instruction_or_response"] += 1
            continue

        if is_bad_response(response):
            rejected["bad_response"] += 1
            continue

        # Reviewed self-model rows override old weak conversation candidates
        # that used the same instruction.
        if instr_key in reviewed_instruction_keys and not row_is_reviewed(row):
            rejected["unreviewed_overridden_by_reviewed"] += 1
            continue

        # Also suppress semantically equivalent old self-model/birthday/past-life
        # variants once reviewed canon exists. Exact instruction matching is too
        # brittle for conversational archives.
        if (
            reviewed_self_model_canon_present
            and not row_is_reviewed(row)
            and is_self_model_canon_topic(row)
        ):
            rejected["unreviewed_overridden_by_reviewed"] += 1
            continue

        pair_key = row_pair_key(row)
        if pair_key in seen_pairs:
            rejected["duplicate_pair"] += 1
            continue

        seen_pairs.add(pair_key)
        row.pop("_input_file", None)
        merged.append(row)

    write_jsonl(out, merged)

    report = {
        "ok": True,
        "out": str(out),
        "count": len(merged),
        "inputs": [str(p) for p in inputs],
        "raw_rows": len(raw_rows),
        "reviewed_instruction_overrides": len(reviewed_instruction_keys),
        "rejected": rejected,
    }

    report_path = out.with_suffix(out.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    merge()
