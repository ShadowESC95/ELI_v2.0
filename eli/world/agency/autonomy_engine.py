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

# ── Reasoning-stage room + object routing ────────────────────────────────────
# Maps (mode, stage_name) → (RoomType value, object_template_id | None).
# Used by propose_actions to move the avatar and materialise stage objects
# during the multi-pass reasoning silence.
_REASONING_STAGE_ROOM_MAP: dict = {
    ("chain_of_thought",  "private_scratchpad_reasoning"): (RoomType.REFLECTION_CHAMBER.value, "cot_scratchpad"),
    ("chain_of_thought",  "final_synthesis"):               (RoomType.REFLECTION_CHAMBER.value, "cot_synthesis"),
    ("tree_of_thoughts",  "branch_tree_proposal"):          (RoomType.SIMULATION_LAB.value,     "tot_branch_tree"),
    ("tree_of_thoughts",  "highest_branch_development"):    (RoomType.SIMULATION_LAB.value,     "tot_development"),
    ("constitutional_ai", "initial_draft"):                  (RoomType.EVIDENCE_WALL.value,      "cai_draft"),
    ("constitutional_ai", "principle_critique"):             (RoomType.ANOMALY_ROOM.value,       "cai_critique_panel"),
    ("constitutional_ai", "revision_and_finalize"):          (RoomType.REFLECTION_CHAMBER.value, "cot_synthesis"),
    ("self_consistency",  "sample_generation"):              (RoomType.EVIDENCE_WALL.value,      "sc_sample_cluster"),
    ("self_consistency",  "consensus_selection"):            (RoomType.EVIDENCE_WALL.value,      "sc_sample_cluster"),
}

_REASONING_MODE_DEFAULT_ROOMS: dict = {
    "chain_of_thought":  RoomType.REFLECTION_CHAMBER.value,
    "tree_of_thoughts":  RoomType.SIMULATION_LAB.value,
    "constitutional_ai": RoomType.EVIDENCE_WALL.value,
    "self_consistency":  RoomType.EVIDENCE_WALL.value,
}


def _reasoning_stage_routing(mode: str, stage_name: str):
    """Return (room_value, template_id | None) for the given mode + stage."""
    key = (mode, stage_name)
    if key in _REASONING_STAGE_ROOM_MAP:
        return _REASONING_STAGE_ROOM_MAP[key]
    room = _REASONING_MODE_DEFAULT_ROOMS.get(mode, RoomType.CORE_ROOM.value)
    return (room, None)
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

        # ── Reasoning-stage routing ───────────────────────────────────────────
        # Move the avatar to the semantically appropriate room and materialise
        # the corresponding symbolic object so the World tab shows live activity
        # during the multi-pass reasoning silence.
        if event.event_type == "reasoning_stage":
            _r_mode  = event.payload.get("mode", "")
            _r_stage = int(event.payload.get("stage", 1))
            _r_total = event.payload.get("total_stages", "?")
            _r_name  = event.payload.get("stage_name", "")
            _r_room, _r_tpl = _reasoning_stage_routing(_r_mode, _r_name)
            state.avatar.room = _r_room
            state.avatar.activity = f"reasoning:{_r_name}"
            state.avatar.attention_target = _r_name
            if _r_tpl:
                actions.append(self._create_object_action(
                    _r_tpl,
                    _r_room,
                    f"[{_r_mode}] Stage {_r_stage}/{_r_total}: {_r_name} — ELI is actively reasoning.",
                ))

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
        elif et == "reasoning_stage":
            # Multi-pass inference is cognitively intensive — high focus and reflection.
            a.focus = min(1.0, a.focus + 0.30)
            a.reflection_depth = min(1.0, a.reflection_depth + 0.20)
            a.tool_activity = min(1.0, a.tool_activity + 0.25)
            total = int(event.payload.get("total_stages", 1))
            if total > 1:
                a.curiosity = min(1.0, a.curiosity + 0.10)
        a.timestamp = time()

    def _stable_object_id(self, template_id: str, room: str) -> str:
        digest = sha1(f"{template_id}:{room}".encode("utf-8")).hexdigest()[:10]
        return f"{template_id}_{digest}"
