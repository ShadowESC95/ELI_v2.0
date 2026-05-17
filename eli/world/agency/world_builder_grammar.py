from __future__ import annotations
from typing import Dict, Any

VALID_WORLD_VERBS = {"create_object", "move_object", "alter_room", "link_object", "retire_object", "avatar_move", "avatar_emote", "journal_entry"}

def validate_world_action_dict(action: Dict[str, Any]) -> bool:
    return isinstance(action, dict) and action.get("action_type") in VALID_WORLD_VERBS and isinstance(action.get("reason", ""), str) and isinstance(action.get("payload", {}), dict)
