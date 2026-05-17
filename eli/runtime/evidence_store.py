from __future__ import annotations

import threading
from typing import Optional

from eli.runtime.pipeline_models import RouteDecision, ExecutionPlan, EvidencePacket, EvidenceItem

_tls = threading.local()


def clear_pipeline_state() -> None:
    for k in ("route_decision", "execution_plan", "evidence_packet"):
        try:
            delattr(_tls, k)
        except Exception:
            pass


def set_current_route_decision(rd: RouteDecision) -> RouteDecision:
    _tls.route_decision = rd
    return rd


def get_current_route_decision() -> Optional[RouteDecision]:
    return getattr(_tls, "route_decision", None)


def set_current_execution_plan(plan: ExecutionPlan) -> ExecutionPlan:
    _tls.execution_plan = plan
    if getattr(_tls, "evidence_packet", None) is None:
        _tls.evidence_packet = EvidencePacket(action=plan.action)
    return plan


def get_current_execution_plan() -> Optional[ExecutionPlan]:
    return getattr(_tls, "execution_plan", None)


def get_current_evidence_packet() -> EvidencePacket:
    ep = getattr(_tls, "evidence_packet", None)
    if ep is None:
        action = getattr(getattr(_tls, "route_decision", None), "action", "CHAT")
        ep = EvidencePacket(action=action)
        _tls.evidence_packet = ep
    return ep


def append_evidence(item: EvidenceItem) -> EvidencePacket:
    ep = get_current_evidence_packet()
    ep.add(item)
    return ep
