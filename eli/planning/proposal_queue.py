from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from eli.runtime.approval_engine import evaluate_record
from eli.planning.proposal_models import ProposalRecord


def queue_path() -> Path:
    override = os.environ.get("ELI_PROPOSAL_QUEUE_PATH", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    root = Path(__file__).resolve().parents[3]
    p = root / "artifacts" / "proactive" / "proposal_queue.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def archive_path() -> Path:
    override = os.environ.get("ELI_PROPOSAL_ARCHIVE_PATH", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    root = Path(__file__).resolve().parents[3]
    p = root / "artifacts" / "proactive" / "proposal_queue.archive.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_record(record: ProposalRecord) -> ProposalRecord:
    q = queue_path()
    with q.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return record


def append_proposal(
    kind: str,
    payload: Dict,
    source: str = "unknown",
    priority: int = 50,
    cwd: Optional[str] = None,
) -> ProposalRecord:
    rec = ProposalRecord(
        kind=kind,
        payload=dict(payload or {}),
        source=source,
        priority=priority,
        cwd=cwd,
    )
    return append_record(rec)


def append_governed_proposal(
    kind: str,
    payload: Dict,
    source: str = "unknown",
    priority: int = 50,
    cwd: Optional[str] = None,
    action_class: str = "observe-only",
    emitter: str = "unknown",
    requested_by: str = "system",
    user_confirmed: bool = False,
    approver: str = "user",
) -> ProposalRecord:
    rec = ProposalRecord(
        kind=kind,
        payload=dict(payload or {}),
        source=source,
        priority=priority,
        cwd=cwd,
        action_class=action_class,
        emitter=emitter,
        requested_by=requested_by,
    )
    rec = evaluate_record(rec, user_confirmed=user_confirmed, approver=approver)
    return append_record(rec)


def read_records() -> List[ProposalRecord]:
    q = queue_path()
    if not q.exists():
        return []
    out: List[ProposalRecord] = []
    for line in q.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(ProposalRecord.from_dict(json.loads(line)))
        except Exception:
            continue
    return out


def drain_records(limit: int = 100, archive: bool = True) -> List[ProposalRecord]:
    q = queue_path()
    if not q.exists():
        return []

    rows = read_records()
    drained = rows[: max(0, int(limit))]
    remaining = rows[len(drained):]

    if archive and drained:
        ap = archive_path()
        with ap.open("a", encoding="utf-8") as fh:
            for rec in drained:
                fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")

    if remaining:
        q.write_text(
            "".join(json.dumps(r.to_dict(), ensure_ascii=False) + "\n" for r in remaining),
            encoding="utf-8",
        )
    else:
        q.unlink(missing_ok=True)

    return drained


def summarize_by_state() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for rec in read_records():
        out[rec.approval_state] = out.get(rec.approval_state, 0) + 1
    return out
