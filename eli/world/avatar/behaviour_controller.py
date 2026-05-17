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
