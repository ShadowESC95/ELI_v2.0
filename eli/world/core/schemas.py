from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional

class RoomType(str, Enum):
    CORE_ROOM = "core_room"
    MEMORY_ARCHIVE = "memory_archive"
    WORKSHOP = "workshop"
    REFLECTION_CHAMBER = "reflection_chamber"
    DEBUG_BASEMENT = "debug_basement"
    UPGRADE_BAY = "upgrade_bay"
    SIMULATION_LAB = "simulation_lab"
    ANOMALY_ROOM = "anomaly_room"
    EVIDENCE_WALL = "evidence_wall"

class WorldActionType(str, Enum):
    CREATE_OBJECT = "create_object"
    MOVE_OBJECT = "move_object"
    ALTER_ROOM = "alter_room"
    LINK_OBJECT = "link_object"
    RETIRE_OBJECT = "retire_object"
    AVATAR_MOVE = "avatar_move"
    AVATAR_EMOTE = "avatar_emote"
    JOURNAL_ENTRY = "journal_entry"
    REQUEST_PERMISSION = "request_permission"
    SNAPSHOT = "snapshot"
    ROLLBACK = "rollback"

class PermissionClass(str, Enum):
    WORLD_SAFE = "world_safe"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"

@dataclass
class AwarenessState:
    focus: float = 0.5
    uncertainty: float = 0.2
    cognitive_load: float = 0.2
    curiosity: float = 0.5
    repair_pressure: float = 0.0
    memory_confidence: float = 0.7
    evidence_confidence: float = 0.7
    tool_activity: float = 0.0
    reflection_depth: float = 0.0
    autonomy_pressure: float = 0.0
    social_context_pressure: float = 0.0
    timestamp: float = field(default_factory=time)

@dataclass
class AvatarState:
    name: str = "ELI"
    room: str = RoomType.CORE_ROOM.value
    x: float = 0.0
    y: float = 0.0
    posture: str = "idle"
    expression: str = "neutral"
    activity: str = "standing_by"
    attention_target: Optional[str] = None
    movement_intent: str = "none"
    persona_tint: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)

@dataclass
class WorldObject:
    object_id: str
    name: str
    object_type: str
    room: str
    x: float = 0.0
    y: float = 0.0
    importance: float = 0.5
    symbolic_meaning: str = ""
    affordances: List[str] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)
    created_by: str = "eli_world"
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    persistent: bool = True
    retired: bool = False
    timestamp: float = field(default_factory=time)

@dataclass
class WorldEvent:
    event_type: str
    source: str
    summary: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)

@dataclass
class WorldAction:
    action_type: str
    actor: str
    room: str
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)
    permission_class: str = PermissionClass.WORLD_SAFE.value
    provenance_id: Optional[str] = None
    timestamp: float = field(default_factory=time)

@dataclass
class EliWorldState:
    world_name: str = "Eli's World"
    identity: Dict[str, Any] = field(default_factory=dict)
    constitution: Dict[str, Any] = field(default_factory=dict)
    awareness: AwarenessState = field(default_factory=AwarenessState)
    avatar: AvatarState = field(default_factory=AvatarState)
    rooms: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    objects: Dict[str, WorldObject] = field(default_factory=dict)
    events: List[WorldEvent] = field(default_factory=list)
    actions: List[WorldAction] = field(default_factory=list)
    goals: List[Dict[str, Any]] = field(default_factory=list)
    habits: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
