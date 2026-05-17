from __future__ import annotations

from typing import Dict, List, Tuple

from eli.planning.proposal_models import ProposalRecord

ACTION_CLASSES = {
    "observe-only",
    "memory-write",
    "local-file-write",
    "shell-exec",
    "self-modification",
    "external-network",
}

EMITTER_POLICY: Dict[str, List[str]] = {
    "awareness": ["observe-only", "memory-write", "local-file-write"],
    "proactive": ["observe-only", "memory-write", "local-file-write", "shell-exec"],
    "reflection": ["observe-only", "memory-write", "local-file-write", "self-modification"],
    "self_improvement": ["observe-only", "memory-write", "local-file-write", "self-modification"],
    "autonomy_controller": ["observe-only", "memory-write"],
    "grounded_remediation": ["local-file-write", "shell-exec", "external-network"],
    "router": ["observe-only", "memory-write"],
    "executor": ["observe-only", "memory-write"],
    "unknown": ["observe-only"],
}

AUTO_APPROVE = {"observe-only", "memory-write"}
MANUAL_APPROVE = {"local-file-write", "shell-exec", "self-modification", "external-network"}


def normalize_action_class(value: str) -> str:
    v = (value or "").strip().lower()
    return v if v in ACTION_CLASSES else "observe-only"


def normalize_emitter(value: str) -> str:
    v = (value or "").strip()
    return v if v in EMITTER_POLICY else "unknown"


def can_emitter_propose(emitter: str, action_class: str) -> Tuple[bool, str]:
    emitter = normalize_emitter(emitter)
    action_class = normalize_action_class(action_class)
    allowed = EMITTER_POLICY.get(emitter, EMITTER_POLICY["unknown"])
    if action_class in allowed:
        return True, f"{emitter} may emit {action_class}"
    return False, f"{emitter} may not emit {action_class}"


def evaluate_record(record: ProposalRecord, user_confirmed: bool = False, approver: str = "user") -> ProposalRecord:
    record.action_class = normalize_action_class(record.action_class)
    record.emitter = normalize_emitter(record.emitter)

    ok, reason = can_emitter_propose(record.emitter, record.action_class)
    if not ok:
        record.approval_state = "blocked"
        record.requires_confirmation = False
        record.policy_reason = reason
        return record

    if record.action_class in AUTO_APPROVE:
        record.approval_state = "approved"
        record.requires_confirmation = False
        record.approved_by = "policy:auto"
        record.policy_reason = f"auto-approved: {record.action_class}"
        return record

    if record.action_class in MANUAL_APPROVE:
        if user_confirmed:
            record.approval_state = "approved"
            record.requires_confirmation = False
            record.approved_by = approver
            record.policy_reason = f"manually approved: {record.action_class}"
            return record

        record.approval_state = "pending_confirmation"
        record.requires_confirmation = True
        record.policy_reason = f"manual approval required: {record.action_class}"
        return record

    record.approval_state = "pending"
    record.requires_confirmation = True
    record.policy_reason = "unknown approval path"
    return record


def evaluate_dict(obj: Dict, user_confirmed: bool = False, approver: str = "user") -> Dict:
    rec = ProposalRecord.from_dict(obj)
    rec = evaluate_record(rec, user_confirmed=user_confirmed, approver=approver)
    return rec.to_dict()
