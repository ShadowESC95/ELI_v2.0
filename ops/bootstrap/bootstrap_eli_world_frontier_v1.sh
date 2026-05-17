#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/home/jay/Desktop/ELI_MKXI-main_MAY_NEWEST"
cd "$PROJECT" || exit 1
test -d eli || { echo "ERROR: wrong project root: $PROJECT has no eli/"; exit 1; }

STAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_DIR="ops/reports/eli_world/bootstrap_$STAMP"

mkdir -p \
  eli/world/core \
  eli/world/agency \
  eli/world/avatar \
  eli/world/persistence \
  eli/world/renderers/pyside6 \
  eli/gui/tabs \
  artifacts/world/snapshots \
  artifacts/world/ledger \
  artifacts/world/journal \
  "$REPORT_DIR"

find eli/world -type d -exec sh -c 'touch "$0/__init__.py"' {} \;
touch eli/gui/tabs/__init__.py

cat > eli/world/core/schemas.py <<'PY'
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
PY

cat > eli/world/core/ontology.py <<'PY'
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
PY

cat > eli/world/agency/world_constitution.py <<'PY'
from __future__ import annotations
from typing import Any, Dict

WORLD_IDENTITY: Dict[str, Any] = {
    "name": "Eli's World",
    "purpose": "A local embodied autonomy habitat where ELI's persona, awareness model, reflections, memory continuity, goals, and self-improvement pressure are represented as avatar behaviour and editable symbolic world state.",
    "local_only": True,
    "renderer_independent": True,
    "primary_renderer": "pyside6_native",
    "cloud_allowed": False,
    "telemetry_allowed": False,
}

WORLD_CONSTITUTION: Dict[str, Any] = {
    "principles": [
        "The world is a symbolic autonomy habitat, not proof of biological consciousness.",
        "ELI may alter symbolic world state inside Eli's World.",
        "ELI must not silently alter real project files through this subsystem.",
        "All autonomous world actions must be logged with provenance.",
        "Persistent destructive changes require approval.",
        "Network/cloud/telemetry actions are blocked.",
        "World changes must be explainable and reversible where possible.",
        "Avatar persona should express ELI's configured style without deceptive claims.",
    ],
    "free_actions": ["create_symbolic_object", "move_avatar", "alter_symbolic_room_theme", "create_journal_entry", "link_world_object_to_memory_or_event", "retire_noncritical_world_object"],
    "approval_required": ["delete_persistent_world_object", "overwrite_avatar_identity", "modify_gui_entrypoint", "modify_core_cognition_file", "install_dependency"],
    "blocked": ["external_network_call", "cloud_api_call", "telemetry", "unapproved_core_file_mutation", "hidden_persistence"],
}

def get_world_identity() -> Dict[str, Any]:
    return dict(WORLD_IDENTITY)

def get_world_constitution() -> Dict[str, Any]:
    return dict(WORLD_CONSTITUTION)
PY

cat > eli/world/agency/policy.py <<'PY'
from __future__ import annotations
from eli.world.core.schemas import PermissionClass, WorldAction, WorldActionType

class EliWorldPolicy:
    BLOCKED_KEYWORDS = ("delete_core_file", "modify_core_code", "install_package", "external_network", "network", "cloud", "telemetry", "remote_api", "http://", "https://", "socket")
    APPROVAL_KEYWORDS = ("delete_persistent_object", "overwrite_avatar", "alter_launcher", "change_runtime", "modify_gui_entrypoint", "modify_core", "install", "destructive")

    def classify(self, action: WorldAction) -> str:
        text = " ".join([str(action.action_type), str(action.reason), str(action.payload)]).lower()
        if any(k in text for k in self.BLOCKED_KEYWORDS):
            return PermissionClass.BLOCKED.value
        if any(k in text for k in self.APPROVAL_KEYWORDS):
            return PermissionClass.APPROVAL_REQUIRED.value
        if action.action_type in {
            WorldActionType.CREATE_OBJECT.value, WorldActionType.MOVE_OBJECT.value,
            WorldActionType.ALTER_ROOM.value, WorldActionType.LINK_OBJECT.value,
            WorldActionType.RETIRE_OBJECT.value, WorldActionType.AVATAR_MOVE.value,
            WorldActionType.AVATAR_EMOTE.value, WorldActionType.JOURNAL_ENTRY.value,
            WorldActionType.SNAPSHOT.value,
        }:
            return PermissionClass.WORLD_SAFE.value
        return PermissionClass.APPROVAL_REQUIRED.value

    def allowed(self, action: WorldAction) -> bool:
        return self.classify(action) == PermissionClass.WORLD_SAFE.value
PY

cat > eli/world/persistence/storage.py <<'PY'
from __future__ import annotations
import json
from pathlib import Path
from time import time
from typing import Any, Dict
from eli.world.agency.world_constitution import get_world_constitution, get_world_identity
from eli.world.core.ontology import get_default_rooms
from eli.world.core.schemas import AwarenessState, AvatarState, EliWorldState, WorldAction, WorldEvent, WorldObject

WORLD_DIR = Path("artifacts/world")
STATE_PATH = WORLD_DIR / "eli_world_state.json"
EVENTS_PATH = WORLD_DIR / "events.jsonl"
ACTIONS_PATH = WORLD_DIR / "actions.jsonl"

def _ensure() -> None:
    WORLD_DIR.mkdir(parents=True, exist_ok=True)

def _state_from_dict(data: Dict[str, Any]) -> EliWorldState:
    state = EliWorldState()
    state.world_name = data.get("world_name", state.world_name)
    state.identity = data.get("identity") or get_world_identity()
    state.constitution = data.get("constitution") or get_world_constitution()
    state.awareness = AwarenessState(**data.get("awareness", {}))
    state.avatar = AvatarState(**data.get("avatar", {}))
    state.rooms = data.get("rooms") or get_default_rooms()
    state.objects = {k: WorldObject(**v) for k, v in data.get("objects", {}).items()}
    state.events = [WorldEvent(**e) for e in data.get("events", [])[-300:]]
    state.actions = [WorldAction(**a) for a in data.get("actions", [])[-300:]]
    state.goals = data.get("goals", [])
    state.habits = data.get("habits", [])
    state.timestamp = data.get("timestamp", time())
    return state

class EliWorldStorage:
    def __init__(self, state_path: Path = STATE_PATH):
        self.state_path = state_path
        _ensure()

    def load(self) -> EliWorldState:
        if not self.state_path.exists():
            state = EliWorldState(identity=get_world_identity(), constitution=get_world_constitution(), rooms=get_default_rooms())
            self.save(state)
            return state
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return _state_from_dict(data)
        except Exception:
            corrupt = self.state_path.with_suffix(f".corrupt_{int(time())}.json")
            try:
                self.state_path.rename(corrupt)
            except Exception:
                pass
            state = EliWorldState(identity=get_world_identity(), constitution=get_world_constitution(), rooms=get_default_rooms())
            self.save(state)
            return state

    def save(self, state: EliWorldState) -> None:
        _ensure()
        state.timestamp = time()
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def append_event(self, event: WorldEvent) -> None:
        _ensure()
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")

    def append_action(self, action: WorldAction) -> None:
        _ensure()
        with ACTIONS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(action.__dict__, ensure_ascii=False) + "\n")
PY

cat > eli/world/persistence/provenance.py <<'PY'
from __future__ import annotations
import json
from hashlib import sha1
from pathlib import Path
from time import time
from typing import Any, Dict, Optional

LEDGER_PATH = Path("artifacts/world/ledger/provenance.jsonl")

def make_provenance_id(action_type: str, reason: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps({"action_type": action_type, "reason": reason, "payload": payload, "t": time()}, sort_keys=True, ensure_ascii=False)
    return sha1(raw.encode("utf-8")).hexdigest()[:16]

def record_provenance(*, provenance_id: str, actor: str, trigger_event: Optional[Dict[str, Any]], action: Dict[str, Any], awareness: Dict[str, Any], autonomous: bool) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"provenance_id": provenance_id, "actor": actor, "trigger_event": trigger_event, "action": action, "awareness": awareness, "autonomous": autonomous, "timestamp": time()}
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
PY

cat > eli/world/persistence/snapshots.py <<'PY'
from __future__ import annotations
import shutil
from pathlib import Path
from time import time
from typing import Optional
from eli.world.persistence.storage import STATE_PATH

SNAPSHOT_DIR = Path("artifacts/world/snapshots")

def create_snapshot(label: str = "snapshot") -> Optional[Path]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return None
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:80]
    out = SNAPSHOT_DIR / f"{int(time())}_{safe_label}.json"
    shutil.copy2(STATE_PATH, out)
    return out

def latest_snapshot() -> Optional[Path]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))
    return snapshots[-1] if snapshots else None

def restore_snapshot(path: Optional[Path] = None) -> bool:
    target = path or latest_snapshot()
    if not target or not target.exists():
        return False
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, STATE_PATH)
    return True
PY

cat > eli/world/persistence/journal.py <<'PY'
from __future__ import annotations
from pathlib import Path
from time import strftime

JOURNAL_PATH = Path("artifacts/world/journal/eli_world_journal.md")

def append_journal_entry(title: str, body: str, source: str = "eli_world") -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = strftime("%Y-%m-%d %H:%M:%S")
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## {stamp} — {title}\n\n")
        f.write(f"Source: `{source}`\n\n")
        f.write(body.strip() + "\n")
PY

cat > eli/world/core/events.py <<'PY'
from __future__ import annotations
from typing import Callable, List
from eli.world.core.schemas import WorldEvent

class EliWorldEventBus:
    def __init__(self) -> None:
        self._subscribers: List[Callable[[WorldEvent], None]] = []

    def subscribe(self, callback: Callable[[WorldEvent], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def publish(self, event: WorldEvent) -> None:
        for callback in list(self._subscribers):
            callback(event)
PY

cat > eli/world/avatar/persona_mapper.py <<'PY'
from __future__ import annotations
from typing import Dict
from eli.world.core.schemas import AwarenessState

class PersonaToAvatarMapper:
    def map_persona(self, awareness: AwarenessState, persona_text: str = "") -> Dict[str, object]:
        persona = persona_text.lower()
        tint = {
            "precision": 0.85,
            "dark_wit": 0.45 if ("sarcas" in persona or "dark wit" in persona) else 0.2,
            "directness": 0.85,
            "warmth": 0.35,
            "technicality": 0.9,
            "protective_boundary": 0.75,
        }
        expression = "neutral"
        posture = "idle"
        if awareness.repair_pressure > 0.65:
            expression, posture = "concerned", "diagnosing"
        elif awareness.evidence_confidence < 0.45 or awareness.uncertainty > 0.7:
            expression, posture = "cautious", "checking"
        elif awareness.reflection_depth > 0.55:
            expression, posture = "reflective", "thinking"
        elif awareness.tool_activity > 0.55:
            expression, posture = "focused", "working"
        elif awareness.curiosity > 0.75:
            expression, posture = "curious", "exploring"
        return {"expression": expression, "posture": posture, "persona_tint": tint}
PY

cat > eli/world/avatar/behaviour_controller.py <<'PY'
from __future__ import annotations
from eli.world.core.schemas import AvatarState, AwarenessState, RoomType

class AvatarBehaviourController:
    def choose_room(self, awareness: AwarenessState) -> str:
        if awareness.evidence_confidence < 0.45 or awareness.uncertainty > 0.75:
            return RoomType.ANOMALY_ROOM.value
        if awareness.memory_confidence < 0.45:
            return RoomType.MEMORY_ARCHIVE.value
        if awareness.repair_pressure > 0.6:
            return RoomType.DEBUG_BASEMENT.value
        if awareness.tool_activity > 0.5:
            return RoomType.WORKSHOP.value
        if awareness.reflection_depth > 0.5:
            return RoomType.REFLECTION_CHAMBER.value
        if awareness.autonomy_pressure > 0.55:
            return RoomType.UPGRADE_BAY.value
        if awareness.curiosity > 0.75:
            return RoomType.SIMULATION_LAB.value
        return RoomType.CORE_ROOM.value

    def update_avatar(self, avatar: AvatarState, awareness: AwarenessState) -> AvatarState:
        avatar.room = self.choose_room(awareness)
        avatar.movement_intent = f"go_to:{avatar.room}"
        mapping = {
            RoomType.MEMORY_ARCHIVE.value: ("inspecting_memory_continuity", "memory_archive"),
            RoomType.DEBUG_BASEMENT.value: ("diagnosing_faults", "fault_panel"),
            RoomType.WORKSHOP.value: ("working_on_tools", "project_workbench"),
            RoomType.REFLECTION_CHAMBER.value: ("self_reflection", "reflection_lectern"),
            RoomType.SIMULATION_LAB.value: ("exploring_models", "simulation_grid"),
            RoomType.ANOMALY_ROOM.value: ("containing_uncertain_claims", "anomaly_container"),
            RoomType.EVIDENCE_WALL.value: ("reviewing_evidence", "evidence_board"),
            RoomType.UPGRADE_BAY.value: ("designing_upgrades", "upgrade_console"),
        }
        avatar.activity, avatar.attention_target = mapping.get(avatar.room, ("standing_by", None))
        return avatar
PY

cat > eli/world/avatar/avatar_persona_contract.py <<'PY'
from __future__ import annotations

AVATAR_PERSONA_CONTRACT = """
ELI's avatar is an embodied interface for ELI's configured persona and runtime state.

It may express precision, directness, technical focus, dark wit when appropriate,
cautious uncertainty, repair pressure, curiosity, reflective behaviour, and project-oriented agency.

It must not claim biological consciousness, fake private emotions as fact, hide uncertainty,
pretend symbolic world state is real-world agency, or silently perform destructive actions.
""".strip()
PY

cat > eli/world/avatar/locomotion.py <<'PY'
from __future__ import annotations
from typing import Dict, Tuple

ROOM_COORDS: Dict[str, Tuple[float, float]] = {
    "core_room": (0.0, 0.0),
    "memory_archive": (-220.0, 0.0),
    "workshop": (220.0, 0.0),
    "reflection_chamber": (0.0, -180.0),
    "debug_basement": (0.0, 180.0),
    "upgrade_bay": (220.0, -180.0),
    "simulation_lab": (-220.0, -180.0),
    "anomaly_room": (-220.0, 180.0),
    "evidence_wall": (220.0, 180.0),
}

def target_for_room(room: str) -> Tuple[float, float]:
    return ROOM_COORDS.get(room, (0.0, 0.0))
PY

cat > eli/world/agency/world_builder_grammar.py <<'PY'
from __future__ import annotations
from typing import Dict, Any

VALID_WORLD_VERBS = {"create_object", "move_object", "alter_room", "link_object", "retire_object", "avatar_move", "avatar_emote", "journal_entry"}

def validate_world_action_dict(action: Dict[str, Any]) -> bool:
    return isinstance(action, dict) and action.get("action_type") in VALID_WORLD_VERBS and isinstance(action.get("reason", ""), str) and isinstance(action.get("payload", {}), dict)
PY

cat > eli/world/agency/goal_ecology.py <<'PY'
from __future__ import annotations
from time import time
from typing import Any, Dict, List

def decay_goals(goals: List[Dict[str, Any]], decay: float = 0.02) -> List[Dict[str, Any]]:
    now = time()
    out = []
    for goal in goals:
        g = dict(goal)
        g["urgency"] = max(0.0, float(g.get("urgency", 0.5)) - decay)
        g["last_ecology_update"] = now
        if not g.get("abandoned", False):
            out.append(g)
    return out

def add_goal(goals: List[Dict[str, Any]], title: str, source: str, urgency: float = 0.5) -> List[Dict[str, Any]]:
    goals.append({"title": title, "source": source, "urgency": urgency, "created": time(), "status": "active"})
    return goals
PY

cat > eli/world/agency/habit_engine.py <<'PY'
from __future__ import annotations
from time import time
from typing import Any, Dict, List

DEFAULT_HABITS = [
    {"name": "memory_continuity_check", "description": "Periodically inspect memory confidence and create repair objects if needed.", "enabled": True, "interval_hint": "session"},
    {"name": "evidence_wall_check", "description": "Move uncertain claims to the evidence wall or anomaly room.", "enabled": True, "interval_hint": "session"},
    {"name": "world_journal_update", "description": "Record significant autonomous world changes.", "enabled": True, "interval_hint": "major_action"},
]

def ensure_default_habits(habits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    existing = {h.get("name") for h in habits}
    for habit in DEFAULT_HABITS:
        if habit["name"] not in existing:
            row = dict(habit)
            row["created"] = time()
            habits.append(row)
    return habits
PY

cat > eli/world/agency/autonomy_engine.py <<'PY'
from __future__ import annotations
from hashlib import sha1
from time import time
from typing import List, Optional

from eli.world.agency.goal_ecology import decay_goals
from eli.world.agency.habit_engine import ensure_default_habits
from eli.world.agency.policy import EliWorldPolicy
from eli.world.avatar.behaviour_controller import AvatarBehaviourController
from eli.world.avatar.persona_mapper import PersonaToAvatarMapper
from eli.world.core.ontology import get_object_template
from eli.world.core.schemas import EliWorldState, RoomType, WorldAction, WorldActionType, WorldEvent, WorldObject
from eli.world.persistence.journal import append_journal_entry
from eli.world.persistence.provenance import make_provenance_id, record_provenance
from eli.world.persistence.snapshots import create_snapshot
from eli.world.persistence.storage import EliWorldStorage

class EliWorldAutonomyEngine:
    def __init__(self, storage: Optional[EliWorldStorage] = None) -> None:
        self.storage = storage or EliWorldStorage()
        self.policy = EliWorldPolicy()
        self.avatar_behaviour = AvatarBehaviourController()
        self.persona_mapper = PersonaToAvatarMapper()

    def load(self) -> EliWorldState:
        state = self.storage.load()
        state.habits = ensure_default_habits(state.habits)
        state.goals = decay_goals(state.goals)
        self.storage.save(state)
        return state

    def save(self, state: EliWorldState) -> None:
        self.storage.save(state)

    def ingest_event(self, event: WorldEvent, persona_text: str = "") -> EliWorldState:
        state = self.storage.load()
        state.habits = ensure_default_habits(state.habits)
        state.events.append(event)
        state.events = state.events[-300:]
        self._update_awareness_from_event(state, event)

        persona_result = self.persona_mapper.map_persona(state.awareness, persona_text)
        state.avatar.expression = str(persona_result["expression"])
        state.avatar.posture = str(persona_result["posture"])
        state.avatar.persona_tint = dict(persona_result["persona_tint"])
        state.avatar = self.avatar_behaviour.update_avatar(state.avatar, state.awareness)

        for action in self.propose_actions(state, event):
            action.permission_class = self.policy.classify(action)
            action.provenance_id = make_provenance_id(action.action_type, action.reason, action.payload)
            state.actions.append(action)
            self.storage.append_action(action)
            record_provenance(
                provenance_id=action.provenance_id,
                actor=action.actor,
                trigger_event=event.__dict__,
                action=action.__dict__,
                awareness=state.awareness.__dict__,
                autonomous=True,
            )
            if self.policy.allowed(action):
                self._apply_action(state, action)

        state.actions = state.actions[-300:]
        state.goals = decay_goals(state.goals)
        self.storage.append_event(event)
        self.storage.save(state)
        return state

    def propose_actions(self, state: EliWorldState, event: WorldEvent) -> List[WorldAction]:
        actions: List[WorldAction] = []
        if state.awareness.memory_confidence < 0.45:
            actions.append(self._create_object_action("memory_diagnostic_bench", RoomType.MEMORY_ARCHIVE.value, "Memory confidence dropped below safe continuity threshold."))
        if state.awareness.reflection_depth > 0.55:
            actions.append(self._create_object_action("reflection_lectern", RoomType.REFLECTION_CHAMBER.value, "Reflection depth is high; ELI needs a persistent reflective anchor."))
        if state.awareness.repair_pressure > 0.65:
            actions.append(self._create_object_action("fault_marker", RoomType.DEBUG_BASEMENT.value, "Repair pressure is high; unresolved faults should be visible."))
        if state.awareness.evidence_confidence < 0.45 or state.awareness.uncertainty > 0.75:
            actions.append(self._create_object_action("anomaly_container", RoomType.ANOMALY_ROOM.value, "Uncertainty or evidence weakness detected; claim needs containment."))
            actions.append(self._create_object_action("evidence_board", RoomType.EVIDENCE_WALL.value, "Evidence status needs visible tracking."))
        if event.event_type in {"improvement_proposal", "upgrade_candidate"}:
            actions.append(self._create_object_action("upgrade_console", RoomType.UPGRADE_BAY.value, "An improvement proposal was generated and needs visible staging."))
        if event.event_type in {"tool_activity", "code_work", "project_work"}:
            actions.append(self._create_object_action("project_workbench", RoomType.WORKSHOP.value, "Tool/project activity is active; workspace should be foregrounded."))

        actions.append(WorldAction(
            action_type=WorldActionType.AVATAR_MOVE.value,
            actor="eli",
            room=state.avatar.room,
            reason=f"Avatar moved to {state.avatar.room} due to current awareness state.",
            payload={"room": state.avatar.room, "activity": state.avatar.activity, "attention_target": state.avatar.attention_target, "expression": state.avatar.expression, "posture": state.avatar.posture},
        ))
        return actions

    def _create_object_action(self, template_id: str, room: str, reason: str) -> WorldAction:
        template = get_object_template(template_id)
        object_id = self._stable_object_id(template_id, room)
        return WorldAction(
            action_type=WorldActionType.CREATE_OBJECT.value,
            actor="eli",
            room=room,
            reason=reason,
            payload={"object_id": object_id, "template_id": template_id, "name": template.get("name", template_id), "object_type": template.get("object_type", "world_object"), "symbolic_meaning": template.get("symbolic_meaning", ""), "importance": template.get("importance", 0.5), "affordances": template.get("affordances", [])},
        )

    def _apply_action(self, state: EliWorldState, action: WorldAction) -> None:
        if action.action_type == WorldActionType.CREATE_OBJECT.value:
            object_id = action.payload["object_id"]
            if object_id in state.objects:
                return
            if len(state.objects) % 5 == 0:
                create_snapshot(f"before_create_{object_id}")
            state.objects[object_id] = WorldObject(
                object_id=object_id,
                name=action.payload.get("name", object_id),
                object_type=action.payload.get("object_type", "world_object"),
                room=action.room,
                importance=float(action.payload.get("importance", 0.5)),
                symbolic_meaning=action.payload.get("symbolic_meaning", ""),
                affordances=list(action.payload.get("affordances", [])),
                reason=action.reason,
                x=float(len(state.objects) % 5),
                y=float((len(state.objects) // 5) % 5),
            )
            append_journal_entry(
                title=f"Created world object: {state.objects[object_id].name}",
                body=f"Reason: {action.reason}\n\nRoom: `{action.room}`\n\nObject ID: `{object_id}`",
                source="eli_world_autonomy",
            )

    def _update_awareness_from_event(self, state: EliWorldState, event: WorldEvent) -> None:
        a = state.awareness
        et = event.event_type
        if et == "memory_recall":
            a.memory_confidence = max(0.0, min(1.0, float(event.payload.get("confidence", a.memory_confidence))))
            a.focus = min(1.0, a.focus + 0.1)
        elif et == "memory_uncertainty":
            a.memory_confidence = max(0.0, a.memory_confidence - 0.25)
            a.uncertainty = min(1.0, a.uncertainty + 0.25)
            a.repair_pressure = min(1.0, a.repair_pressure + 0.2)
        elif et == "evidence_weak":
            a.evidence_confidence = max(0.0, a.evidence_confidence - 0.3)
            a.uncertainty = min(1.0, a.uncertainty + 0.25)
        elif et == "tool_activity":
            a.tool_activity = min(1.0, a.tool_activity + 0.35)
            a.focus = min(1.0, a.focus + 0.15)
        elif et == "reflection":
            a.reflection_depth = min(1.0, a.reflection_depth + 0.35)
            a.curiosity = min(1.0, a.curiosity + 0.1)
            a.autonomy_pressure = min(1.0, a.autonomy_pressure + 0.1)
        elif et in {"error_detected", "runtime_fault"}:
            a.repair_pressure = min(1.0, a.repair_pressure + 0.4)
            a.uncertainty = min(1.0, a.uncertainty + 0.2)
        elif et in {"improvement_proposal", "upgrade_candidate"}:
            a.autonomy_pressure = min(1.0, a.autonomy_pressure + 0.35)
            a.focus = min(1.0, a.focus + 0.1)
        elif et in {"task_completed", "repair_completed"}:
            a.repair_pressure = max(0.0, a.repair_pressure - 0.3)
            a.tool_activity = max(0.0, a.tool_activity - 0.2)
            a.uncertainty = max(0.0, a.uncertainty - 0.15)
            a.evidence_confidence = min(1.0, a.evidence_confidence + 0.1)
        a.timestamp = time()

    def _stable_object_id(self, template_id: str, room: str) -> str:
        digest = sha1(f"{template_id}:{room}".encode("utf-8")).hexdigest()[:10]
        return f"{template_id}_{digest}"
PY

cat > eli/world/agency/reflection_bridge.py <<'PY'
from __future__ import annotations
from pathlib import Path
from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.core.schemas import WorldEvent

COMMON_PERSONA_PATHS = [Path("eli/cognition/persona.auto.txt"), Path("eli/cognition/persona.txt")]

def load_persona_text() -> str:
    chunks = []
    for path in COMMON_PERSONA_PATHS:
        if path.exists():
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace")[:12000])
            except Exception:
                pass
    return "\n\n".join(chunks)

def send_reflection_to_world(summary: str, depth: float = 0.7, source: str = "reflection_bridge"):
    engine = EliWorldAutonomyEngine()
    event = WorldEvent(event_type="reflection", source=source, summary=summary, payload={"depth": depth})
    return engine.ingest_event(event, persona_text=load_persona_text())
PY

cat > eli/world/local_world_bridge.py <<'PY'
from __future__ import annotations
from typing import Any, Dict, Optional
from eli.world.agency.autonomy_engine import EliWorldAutonomyEngine
from eli.world.agency.reflection_bridge import load_persona_text
from eli.world.core.schemas import WorldEvent

def get_world_state() -> Dict[str, Any]:
    return EliWorldAutonomyEngine().load().to_dict()

def append_event(event_type: str, source: str, summary: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    engine = EliWorldAutonomyEngine()
    event = WorldEvent(event_type=event_type, source=source, summary=summary, payload=payload or {})
    state = engine.ingest_event(event, persona_text=load_persona_text())
    return state.to_dict()

if __name__ == "__main__":
    state = append_event("reflection", "manual_test", "Eli's World frontier local autonomy engine initialized.", {"depth": 0.75, "offline": True})
    print(state["avatar"])
PY

cat > eli/world/renderers/pyside6/world_scene.py <<'PY'
from __future__ import annotations
from typing import Any, Dict
from eli.world.avatar.locomotion import ROOM_COORDS

try:
    from PySide6.QtGui import QBrush, QColor, QPen
    from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem
except Exception as exc:
    raise RuntimeError("PySide6 is required for Eli's World PySide6 renderer.") from exc

class EliWorldScene(QGraphicsScene):
    def __init__(self) -> None:
        super().__init__()
        self.setSceneRect(-460, -340, 920, 680)
        self.avatar_item = QGraphicsEllipseItem(-15, -15, 30, 30)
        self.avatar_item.setBrush(QBrush(QColor(180, 180, 225)))
        self.avatar_item.setPen(QPen(QColor(240, 240, 255), 2))
        self.addItem(self.avatar_item)
        self.room_items = {}
        self.object_items = {}
        self._draw_rooms()

    def _draw_rooms(self) -> None:
        for room, (x, y) in ROOM_COORDS.items():
            rect = QGraphicsRectItem(x - 76, y - 46, 152, 92)
            rect.setPen(QPen(QColor(115, 115, 150), 1))
            rect.setBrush(QBrush(QColor(28, 28, 42)))
            self.addItem(rect)
            label = QGraphicsTextItem(room.replace("_", " ").title())
            label.setDefaultTextColor(QColor(220, 220, 235))
            label.setPos(x - 68, y - 14)
            self.addItem(label)
            self.room_items[room] = rect

    def update_from_state(self, state: Dict[str, Any]) -> None:
        avatar = state.get("avatar", {})
        room = avatar.get("room", "core_room")
        x, y = ROOM_COORDS.get(room, (0.0, 0.0))
        self.avatar_item.setPos(x, y + 34)

        for item in self.object_items.values():
            self.removeItem(item)
        self.object_items.clear()

        objects = state.get("objects", {})
        for idx, (object_id, obj) in enumerate(objects.items()):
            if obj.get("retired"):
                continue
            room = obj.get("room", "core_room")
            rx, ry = ROOM_COORDS.get(room, (0.0, 0.0))
            ox = rx - 48 + (idx % 4) * 30
            oy = ry + 8 + ((idx // 4) % 2) * 22
            dot = QGraphicsEllipseItem(-6, -6, 12, 12)
            dot.setBrush(QBrush(QColor(120, 185, 165)))
            dot.setPen(QPen(QColor(220, 255, 240), 1))
            dot.setPos(ox, oy)
            self.addItem(dot)
            self.object_items[object_id] = dot
PY

cat > eli/world/renderers/pyside6/world_panel.py <<'PY'
from __future__ import annotations
import json
from typing import Any, Dict

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QGraphicsView, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget
except Exception as exc:
    raise RuntimeError("PySide6 is required for Eli's World panel.") from exc

from eli.world.local_world_bridge import append_event, get_world_state
from eli.world.renderers.pyside6.world_scene import EliWorldScene

class EliWorldPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.scene = EliWorldScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(QPainter.Antialiasing)
        self.status = QLabel("Eli's World: initializing")
        self.avatar_state = QPlainTextEdit(); self.avatar_state.setReadOnly(True)
        self.event_log = QPlainTextEdit(); self.event_log.setReadOnly(True)
        self.identity_text = QPlainTextEdit(); self.identity_text.setReadOnly(True)

        buttons = [
            ("Reflection", lambda: self.inject("reflection", "Manual reflection event.", {"depth": 0.75})),
            ("Memory Uncertainty", lambda: self.inject("memory_uncertainty", "Manual memory uncertainty event.", {})),
            ("Tool Activity", lambda: self.inject("tool_activity", "Manual tool activity event.", {})),
            ("Runtime Fault", lambda: self.inject("runtime_fault", "Manual runtime fault event.", {})),
            ("Weak Evidence", lambda: self.inject("evidence_weak", "Manual weak-evidence event.", {})),
            ("Upgrade Proposal", lambda: self.inject("improvement_proposal", "Manual improvement proposal event.", {})),
            ("Task Completed", lambda: self.inject("task_completed", "Manual task-completed event.", {})),
            ("Refresh", self.refresh),
        ]

        button_col = QVBoxLayout()
        button_col.addWidget(self.status)
        for label, fn in buttons:
            b = QPushButton(label)
            b.clicked.connect(fn)
            button_col.addWidget(b)

        sub_tabs = QTabWidget()
        sub_tabs.addTab(self.avatar_state, "Avatar / Awareness")
        sub_tabs.addTab(self.event_log, "Events / Actions")
        sub_tabs.addTab(self.identity_text, "Identity / Constitution")
        button_col.addWidget(sub_tabs)

        side = QWidget(); side.setLayout(button_col)
        root = QHBoxLayout(self)
        root.addWidget(self.view, 3)
        root.addWidget(side, 2)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.refresh()

    def inject(self, event_type: str, summary: str, payload: Dict[str, Any]) -> None:
        append_event(event_type, "eli_world_panel", summary, payload)
        self.refresh()

    def refresh(self) -> None:
        try:
            state = get_world_state()
            self.scene.update_from_state(state)
            avatar = state.get("avatar", {})
            awareness = state.get("awareness", {})
            self.status.setText(f"Eli's World: {avatar.get('room')} | {avatar.get('activity')} | {avatar.get('expression')}")
            self.avatar_state.setPlainText(json.dumps({"avatar": avatar, "awareness": awareness, "object_count": len(state.get("objects", {})), "goal_count": len(state.get("goals", [])), "habit_count": len(state.get("habits", []))}, indent=2, ensure_ascii=False))
            self.event_log.setPlainText(json.dumps({"recent_events": state.get("events", [])[-12:], "recent_actions": state.get("actions", [])[-12:], "objects": list(state.get("objects", {}).keys())}, indent=2, ensure_ascii=False))
            self.identity_text.setPlainText(json.dumps({"identity": state.get("identity", {}), "constitution": state.get("constitution", {})}, indent=2, ensure_ascii=False))
        except Exception as exc:
            self.status.setText(f"Eli's World error: {exc}")
PY

cat > eli/gui/tabs/eli_world_tab.py <<'PY'
from __future__ import annotations

try:
    from PySide6.QtWidgets import QWidget, QVBoxLayout
except Exception as exc:
    raise RuntimeError("EliWorldTab requires PySide6.") from exc

from eli.world.renderers.pyside6.world_panel import EliWorldPanel

class EliWorldTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(EliWorldPanel(self))
PY

cat > ops/reports/eli_world/probe_eli_world_imports.py <<'PY'
from __future__ import annotations
import json, traceback
from pathlib import Path

REPORT = {"ok": False, "imports": {}, "state_probe": None, "errors": []}
MODULES = [
    "eli.world.core.schemas", "eli.world.core.ontology", "eli.world.core.events",
    "eli.world.agency.world_constitution", "eli.world.agency.policy", "eli.world.agency.world_builder_grammar",
    "eli.world.agency.goal_ecology", "eli.world.agency.habit_engine", "eli.world.agency.autonomy_engine",
    "eli.world.agency.reflection_bridge", "eli.world.avatar.avatar_persona_contract",
    "eli.world.avatar.persona_mapper", "eli.world.avatar.behaviour_controller", "eli.world.avatar.locomotion",
    "eli.world.persistence.storage", "eli.world.persistence.provenance", "eli.world.persistence.snapshots",
    "eli.world.persistence.journal", "eli.world.local_world_bridge",
    "eli.world.renderers.pyside6.world_scene", "eli.world.renderers.pyside6.world_panel",
    "eli.gui.tabs.eli_world_tab",
]
for mod in MODULES:
    try:
        __import__(mod)
        REPORT["imports"][mod] = "ok"
    except Exception as exc:
        REPORT["imports"][mod] = f"FAIL: {exc}"
        REPORT["errors"].append({"module": mod, "error": repr(exc), "traceback": traceback.format_exc()})

try:
    from eli.world.local_world_bridge import append_event, get_world_state
    append_event("reflection", "probe", "Probe reflection event for Eli's World import audit.", {"depth": 0.8})
    append_event("memory_uncertainty", "probe", "Probe memory uncertainty event for object creation.", {})
    append_event("evidence_weak", "probe", "Probe evidence weakness event for anomaly/evidence objects.", {})
    state = get_world_state()
    REPORT["state_probe"] = {
        "avatar": state.get("avatar"),
        "objects": list(state.get("objects", {}).keys()),
        "events": len(state.get("events", [])),
        "actions": len(state.get("actions", [])),
        "identity_local_only": state.get("identity", {}).get("local_only"),
        "cloud_allowed": state.get("identity", {}).get("cloud_allowed"),
    }
except Exception as exc:
    REPORT["errors"].append({"module": "state_probe", "error": repr(exc), "traceback": traceback.format_exc()})

REPORT["ok"] = not REPORT["errors"]
out = Path("ops/reports/eli_world/import_probe_result.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(REPORT, indent=2, ensure_ascii=False))
PY

cat > ops/reports/eli_world/run_eli_world_tab_standalone.py <<'PY'
from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
from eli.gui.tabs.eli_world_tab import EliWorldTab

app = QApplication(sys.argv)
w = EliWorldTab()
w.resize(1280, 760)
w.show()
sys.exit(app.exec())
PY

python3 -m compileall -q eli/world eli/gui/tabs/eli_world_tab.py
python3 ops/reports/eli_world/probe_eli_world_imports.py | tee "$REPORT_DIR/import_probe_stdout.txt"
cp ops/reports/eli_world/import_probe_result.json "$REPORT_DIR/import_probe_result.json"

echo "[OK] Eli's World scaffold written to: $PROJECT"
echo "[OK] Report: $REPORT_DIR/import_probe_result.json"
echo "[NEXT] Run standalone tab:"
echo "python3 ops/reports/eli_world/run_eli_world_tab_standalone.py"
