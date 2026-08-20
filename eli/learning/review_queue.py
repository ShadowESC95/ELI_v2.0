"""The human review gate that had no way to be passed.

The trainer's contract is that a row trains only if a person approved it and scoped
it to a target (`lora_trainer_guard._validate_dataset_rows`). That contract was
enforced but unreachable: `dataset_builder` writes every candidate tagged
`needs_review`, and nothing in the product could ever retag one `reviewed`. Live
state before this module existed: 615 candidate rows, 0 trainable.

This is the queue behind the Training tab. Assisted triage does the obvious
rejections up front — `is_bad_response` already knew what a broken reply looks
like — so the operator reads the rows that actually need judgement instead of all
of them. Approval still happens one row at a time, by a person. Nothing here can
mark a row reviewed on its own.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from eli.utils.log import get_logger

from eli.learning.dataset_filters import (
    clean_row, is_bad_response, load_jsonl, normalise_text, row_pair_key, write_jsonl,
)

log = get_logger(__name__)

# Verdicts from triage — advisory only; the operator's decision is stored separately.
VERDICT_REJECT = "reject"   # provably unusable
VERDICT_FLAG = "flag"       # needs a human eye
VERDICT_OK = "ok"           # nothing suspicious found

DECISION_PENDING = "pending"
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"

MIN_INSTRUCTION_CHARS = 8
LONG_RESPONSE_CHARS = 4000


def candidates_path() -> Path:
    """Where dataset_builder drops raw candidates."""
    from eli.core.paths import learning_dir
    return Path(learning_dir()) / "datasets" / "eli_supervised_v0.jsonl"


def build_candidates(db_paths: Optional[list[Path]] = None) -> dict[str, Any]:
    """Re-mine the SQLite stores for candidate pairs. Returns the builder's report."""
    from eli.learning.dataset_builder import build_dataset
    out = candidates_path()
    report = out.parent / "eli_supervised_v0.report.json"
    return build_dataset(db_paths, out, report)


def _triage_row(row: dict[str, Any], seen: set) -> tuple[str, str]:
    """(verdict, reason). Cheap, deterministic, no model involved."""
    instruction = normalise_text(row.get("instruction", ""))
    response = normalise_text(row.get("response", ""))

    if not instruction or not response:
        return VERDICT_REJECT, "empty instruction or response"
    if is_bad_response(response):
        return VERDICT_REJECT, "response matches a known-bad surface (error text, scaffold leak, too short)"
    if len(instruction) < MIN_INSTRUCTION_CHARS:
        return VERDICT_REJECT, f"instruction under {MIN_INSTRUCTION_CHARS} characters"

    key = row_pair_key(row)
    if key in seen:
        return VERDICT_REJECT, "duplicate of an earlier row"
    seen.add(key)

    if len(response) > LONG_RESPONSE_CHARS:
        return VERDICT_FLAG, f"response over {LONG_RESPONSE_CHARS} characters — check it is not a dump"
    if "<PROJECT_ROOT>" in response or "<HOME>" in response:
        return VERDICT_FLAG, "contains a redacted path — check it still reads naturally"
    if response.count("\n") > 40:
        return VERDICT_FLAG, "very long structured output — check it suits conversational training"
    if instruction.strip().endswith(("?", "?")) is False and len(instruction) < 20:
        return VERDICT_FLAG, "terse non-question instruction"
    return VERDICT_OK, ""


class ReviewQueue:
    """In-memory review session over one target's candidate rows."""

    def __init__(self, target: str, rows: list[dict[str, Any]], dataset_path: Path):
        self.target = str(target)
        self.dataset_path = Path(dataset_path)
        self.items: list[dict[str, Any]] = []
        seen: set = set()
        for i, raw in enumerate(rows):
            row = clean_row(raw)
            verdict, reason = _triage_row(row, seen)
            self.items.append({
                "index": i,
                "instruction": row.get("instruction", ""),
                "response": row.get("response", ""),
                "source": row.get("source", ""),
                "tags": [str(t) for t in (row.get("tags") or [])],
                "weight": row.get("weight", 0.35),
                "verdict": verdict,
                "reason": reason,
                # Triage pre-rejects; it never pre-approves. Approval is a person's act.
                "decision": DECISION_REJECTED if verdict == VERDICT_REJECT else DECISION_PENDING,
                "edited": False,
            })

    # ── construction ──────────────────────────────────────────────────────────
    @classmethod
    def for_target(cls, target: str, *, candidate_path: Optional[Path] = None) -> "ReviewQueue":
        """Load candidates, resuming any decisions already saved for this target."""
        from eli.learning.lora_trainer_guard import resolve_target, _project_path
        cfg = resolve_target(target)
        dataset_path = _project_path(cfg.dataset_path)

        src = Path(candidate_path) if candidate_path else candidates_path()
        rows = load_jsonl(src) if src.is_file() else []
        if not rows and dataset_path.is_file():
            # No fresh candidate file — review whatever the target already points at.
            rows = load_jsonl(dataset_path)
            src = dataset_path

        q = cls(target, rows, dataset_path)
        q.source_path = src
        q._restore_decisions()
        return q

    def _restore_decisions(self) -> None:
        """Rows already approved for this target keep their approval across sessions."""
        if not self.dataset_path.is_file():
            return
        approved = set()
        for row in load_jsonl(self.dataset_path):
            tags = [str(t).lower() for t in (row.get("tags") or [])]
            if "reviewed" in tags:
                approved.add(row_pair_key(row))
        if not approved:
            return
        for item in self.items:
            if row_pair_key(item) in approved:
                item["decision"] = DECISION_APPROVED

    # ── inspection ────────────────────────────────────────────────────────────
    def rows(self, *, verdict: Optional[str] = None, decision: Optional[str] = None) -> list[dict[str, Any]]:
        out = self.items
        if verdict:
            out = [x for x in out if x["verdict"] == verdict]
        if decision:
            out = [x for x in out if x["decision"] == decision]
        return out

    def stats(self) -> dict[str, Any]:
        s = {"total": len(self.items), "approved": 0, "rejected": 0, "pending": 0,
             "auto_rejected": 0, "flagged": 0, "clean": 0, "edited": 0}
        for x in self.items:
            s[{DECISION_APPROVED: "approved", DECISION_REJECTED: "rejected",
               DECISION_PENDING: "pending"}[x["decision"]]] += 1
            if x["verdict"] == VERDICT_REJECT:
                s["auto_rejected"] += 1
            elif x["verdict"] == VERDICT_FLAG:
                s["flagged"] += 1
            else:
                s["clean"] += 1
            if x["edited"]:
                s["edited"] += 1
        s["to_review"] = s["pending"]
        return s

    # ── mutation ──────────────────────────────────────────────────────────────
    def set_decision(self, index: int, decision: str) -> bool:
        if decision not in (DECISION_APPROVED, DECISION_REJECTED, DECISION_PENDING):
            raise ValueError(f"unknown decision: {decision!r}")
        for item in self.items:
            if item["index"] == index:
                item["decision"] = decision
                return True
        return False

    def set_decisions(self, indices: Iterable[int], decision: str) -> int:
        wanted = set(int(i) for i in indices)
        n = 0
        for item in self.items:
            if item["index"] in wanted:
                item["decision"] = decision
                n += 1
        return n

    def edit(self, index: int, *, instruction: Optional[str] = None,
             response: Optional[str] = None) -> bool:
        """Fix a row in place. An edited row is re-triaged — an edit can rescue a row
        triage had rejected, and can equally break one it had passed."""
        for item in self.items:
            if item["index"] != index:
                continue
            if instruction is not None:
                item["instruction"] = normalise_text(instruction)
            if response is not None:
                item["response"] = normalise_text(response)
            item["edited"] = True
            verdict, reason = _triage_row(item, set())
            item["verdict"], item["reason"] = verdict, reason
            if verdict == VERDICT_REJECT:
                item["decision"] = DECISION_REJECTED
            return True
        return False

    def approve_clean(self) -> int:
        """Bulk-approve rows triage found nothing wrong with. Still an operator action —
        it is one click that stands for reading a filtered list, not an auto-approve."""
        return self.set_decisions(
            [x["index"] for x in self.items
             if x["verdict"] == VERDICT_OK and x["decision"] == DECISION_PENDING],
            DECISION_APPROVED)

    # ── output ────────────────────────────────────────────────────────────────
    def to_trainable_rows(self) -> list[dict[str, Any]]:
        """Approved rows, tagged `reviewed` and scoped to this target — the exact shape
        `lora_trainer_guard._validate_dataset_rows` demands."""
        out = []
        for item in self.items:
            if item["decision"] != DECISION_APPROVED:
                continue
            tags = [t for t in item["tags"] if str(t).lower() not in ("needs_review", "reviewed")]
            tags.append("reviewed")
            if item["edited"]:
                tags.append("operator_edited")
            out.append({
                "instruction": item["instruction"],
                "response": item["response"],
                "source": item["source"] or "review_queue",
                "weight": item.get("weight", 0.35),
                "tags": tags,
                "target": self.target,
                "targets": [self.target],
                "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        return out

    def save(self) -> dict[str, Any]:
        """Write the approved set to the target's trainable dataset.

        Overwrites rather than appends: the queue holds the full picture for this
        target, so appending would duplicate every row on a second pass.
        """
        rows = self.to_trainable_rows()
        self.dataset_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(self.dataset_path, rows)
        report = {
            "ok": True,
            "target": self.target,
            "written": len(rows),
            "path": str(self.dataset_path),
            "stats": self.stats(),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        try:
            side = self.dataset_path.with_suffix(".review.json")
            side.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            log.debug("[REVIEW] could not write the review sidecar report", exc_info=True)
        return report


__all__ = [
    "ReviewQueue", "build_candidates", "candidates_path",
    "VERDICT_OK", "VERDICT_FLAG", "VERDICT_REJECT",
    "DECISION_PENDING", "DECISION_APPROVED", "DECISION_REJECTED",
]
