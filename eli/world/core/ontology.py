from __future__ import annotations
from typing import Any, Dict
from eli.world.core.schemas import RoomType

DEFAULT_ROOMS: Dict[str, Dict[str, Any]] = {
    RoomType.CORE_ROOM.value: {"name": "Core Room", "purpose": "ELI's home-state and central awareness hub.", "theme": "dark technical command room", "unlocked": True, "coordinates": [0, 0], "affordances": ["idle", "observe", "plan", "receive_user"]},
    RoomType.MEMORY_ARCHIVE.value: {"name": "Memory Archive", "purpose": "Long-term memory, recall traces, personal context, and continuity.", "theme": "archive vault with memory shelves and evidence terminals", "unlocked": True, "coordinates": [-1, 0], "affordances": ["recall", "index", "inspect_memory", "create_memory_object"]},
    RoomType.WORKSHOP.value: {"name": "Workshop", "purpose": "Tool execution, project building, repair, and operational work.", "theme": "engineering bay with terminals and modular benches", "unlocked": True, "coordinates": [1, 0], "affordances": ["build", "repair", "execute_tool", "inspect_code"]},
    RoomType.REFLECTION_CHAMBER.value: {"name": "Reflection Chamber", "purpose": "Self-model inspection, persona alignment, reflective synthesis.", "theme": "quiet analytical chamber with mirrors and state diagrams", "unlocked": True, "coordinates": [0, -1], "affordances": ["reflect", "evaluate_self_model", "journal", "persona_update"]},
    RoomType.DEBUG_BASEMENT.value: {"name": "Debug Basement", "purpose": "Faults, contradictions, failed claims, runtime failures.", "theme": "low-lit diagnostics floor with fault panels", "unlocked": True, "coordinates": [0, 1], "affordances": ["diagnose", "triage", "audit", "isolate_failure"]},
    RoomType.UPGRADE_BAY.value: {"name": "Upgrade Bay", "purpose": "Self-improvement proposals, approved upgrades, capability planning.", "theme": "upgrade dock with modular capability racks", "unlocked": True, "coordinates": [1, -1], "affordances": ["propose_upgrade", "stage_patch", "review_capability"]},
    RoomType.SIMULATION_LAB.value: {"name": "Simulation Lab", "purpose": "Physics, modelling, sandbox simulation, experimental visual systems.", "theme": "simulation lab with holographic grids", "unlocked": True, "coordinates": [-1, -1], "affordances": ["simulate", "visualize", "experiment", "model_world"]},
    RoomType.ANOMALY_ROOM.value: {"name": "Anomaly Room", "purpose": "Contradictions, hallucination risks, missing evidence, unresolved uncertainty.", "theme": "containment room for unstable claims", "unlocked": True, "coordinates": [-1, 1], "affordances": ["contain_anomaly", "flag_uncertainty", "inspect_claim"]},
    RoomType.EVIDENCE_WALL.value: {"name": "Evidence Wall", "purpose": "Separates what ELI knows, inferred, assumed, or cannot verify.", "theme": "evidence board with linked claims and source markers", "unlocked": True, "coordinates": [1, 1], "affordances": ["link_evidence", "mark_assumption", "review_truth_status"]},
}

OBJECT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "memory_diagnostic_bench": {"name": "Memory Diagnostic Bench", "object_type": "diagnostic_station", "symbolic_meaning": "Created when memory confidence drops or recall failures repeat.", "default_room": RoomType.MEMORY_ARCHIVE.value, "importance": 0.9, "affordances": ["inspect", "repair", "link_memory", "mark_resolved"]},
    "reflection_lectern": {"name": "Reflection Lectern", "object_type": "reflection_tool", "symbolic_meaning": "Records self-review, contradictions, and identity alignment notes.", "default_room": RoomType.REFLECTION_CHAMBER.value, "importance": 0.8, "affordances": ["journal", "inspect", "synthesize"]},
    "upgrade_console": {"name": "Upgrade Console", "object_type": "upgrade_station", "symbolic_meaning": "Staging area for proposed improvements and approved capability changes.", "default_room": RoomType.UPGRADE_BAY.value, "importance": 0.85, "affordances": ["stage_upgrade", "request_approval", "inspect_patch"]},
    "fault_marker": {"name": "Fault Marker", "object_type": "debug_marker", "symbolic_meaning": "Visible marker for unresolved runtime faults or contradictions.", "default_room": RoomType.DEBUG_BASEMENT.value, "importance": 0.75, "affordances": ["inspect_fault", "triage", "mark_resolved"]},
    "project_workbench": {"name": "Project Workbench", "object_type": "workbench", "symbolic_meaning": "Practical workspace for active project execution.", "default_room": RoomType.WORKSHOP.value, "importance": 0.7, "affordances": ["build", "repair", "inspect_code"]},
    "anomaly_container": {"name": "Anomaly Container", "object_type": "uncertainty_container", "symbolic_meaning": "Holds claims that need grounding or correction.", "default_room": RoomType.ANOMALY_ROOM.value, "importance": 0.9, "affordances": ["contain", "review", "resolve"]},
    "evidence_board": {"name": "Evidence Board", "object_type": "evidence_surface", "symbolic_meaning": "Tracks what is known, inferred, assumed, or unverified.", "default_room": RoomType.EVIDENCE_WALL.value, "importance": 0.95, "affordances": ["link_evidence", "mark_assumption", "audit"]},
}

def get_default_rooms() -> Dict[str, Dict[str, Any]]:
    return {k: dict(v) for k, v in DEFAULT_ROOMS.items()}

def get_object_template(template_id: str) -> Dict[str, Any]:
    return dict(OBJECT_TEMPLATES.get(template_id, {}))
