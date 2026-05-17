from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eli.learning.dataset_filters import (
    clean_row,
    is_bad_response,
    load_jsonl,
    row_is_reviewed,
    row_pair_key,
    write_jsonl,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_IN = PROJECT_ROOT / "training/datasets/eli_supervised_v0.with_self_model.jsonl"
REGISTRY = PROJECT_ROOT / "models/lora/registry/eli_phi_targets.json"

ALLOWED_TARGETS = {"eli_phi", "eli_phi_ultra"}


def _load_allowed_targets() -> set[str]:
    if not REGISTRY.exists():
        return set(ALLOWED_TARGETS)
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    allowed = data.get("allowed_targets", {})
    if isinstance(allowed, dict):
        return set(allowed.keys()) & ALLOWED_TARGETS
    return set(ALLOWED_TARGETS)


def _row_targets(row: dict[str, Any]) -> set[str]:
    raw = row.get("targets") or row.get("target_models") or row.get("adapter_targets") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {str(x).strip() for x in raw if str(x).strip()}


def _target_allowed_for_row(row: dict[str, Any], target: str) -> bool:
    targets = _row_targets(row)

    # Reviewed legacy rows without explicit targets are NOT allowed.
    # This prevents accidental training against generic conversation rows.
    if not targets:
        return False

    return target in targets


def export_for_target(
    src: Path = DEFAULT_IN,
    target: str = "eli_phi_ultra",
    out: Path | None = None,
) -> dict[str, Any]:
    allowed_targets = _load_allowed_targets()

    if target not in allowed_targets:
        raise SystemExit(
            f"Refusing export for target={target!r}. "
            f"Allowed targets: {sorted(allowed_targets)}"
        )

    if out is None:
        out = PROJECT_ROOT / f"training/datasets/eli_supervised_v0.{target}.trainable.jsonl"

    rows = load_jsonl(src)
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    rejected = {
        "not_reviewed_or_approved": 0,
        "missing_or_wrong_target": 0,
        "bad_response": 0,
        "duplicate_pair": 0,
        "empty_instruction_or_response": 0,
    }

    for row in rows:
        row = clean_row(row)

        instruction = str(row.get("instruction") or "").strip()
        response = str(row.get("response") or "").strip()

        if not instruction or not response:
            rejected["empty_instruction_or_response"] += 1
            continue

        if not row_is_reviewed(row):
            rejected["not_reviewed_or_approved"] += 1
            continue

        if not _target_allowed_for_row(row, target):
            rejected["missing_or_wrong_target"] += 1
            continue

        if is_bad_response(response):
            rejected["bad_response"] += 1
            continue

        key = row_pair_key(row)
        if key in seen:
            rejected["duplicate_pair"] += 1
            continue
        seen.add(key)

        row["target"] = target
        row["training_scope"] = "phi_targeted_lora_only"
        kept.append(row)

    write_jsonl(out, kept)

    report = {
        "ok": True,
        "target": target,
        "src": str(src),
        "out": str(out),
        "count": len(kept),
        "allowed_targets": sorted(allowed_targets),
        "rejected": rejected,
    }

    report_path = out.with_suffix(out.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_IN)
    ap.add_argument(
        "--target",
        choices=sorted(ALLOWED_TARGETS),
        default=None,
        help="Target adapter/runtime family. If omitted, exports both allowed Phi targets.",
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.target:
        print(json.dumps(export_for_target(args.src, args.target, args.out), indent=2))
        return

    reports = [
        export_for_target(args.src, "eli_phi", None),
        export_for_target(args.src, "eli_phi_ultra", None),
    ]
    print(json.dumps({"ok": True, "reports": reports}, indent=2))


if __name__ == "__main__":
    main()
