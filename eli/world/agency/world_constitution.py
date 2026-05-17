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
