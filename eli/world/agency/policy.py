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
